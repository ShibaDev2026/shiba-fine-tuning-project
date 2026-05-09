# layer_2_chamber/backend/api/routes_router.py
"""Phase 0 路由層 API — router_decisions 查詢、統計、狀態與採納更新"""

import json
import sqlite3
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from ..core.config import get_db
from shiba_config import CONFIG

# yaml 目錄（相對專案根）
_MODELS_DIR: Path = Path(__file__).resolve().parent.parent.parent.parent / "config" / "models"

# 推論型 role 清單（供 /status 遍歷）
_INFERENCE_ROLES = ["classifier", "compressor", "responder"]

router = APIRouter(prefix="/api/v1/router", tags=["router"])

_DRIFT_THRESHOLD = 0.35  # 對齊 trigger_policy


# ── B-1 + B-2：補欄位、加日期篩選 ───────────────────────────────────────────
@router.get("/decisions")
def list_decisions(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    date_from: str = Query(None),   # e.g. "2026-04-22"
    date_to: str = Query(None),
    conn: sqlite3.Connection = Depends(get_db),
):
    """列出路由決策紀錄（含 prompt_hash、local_output，支援日期範圍篩選）"""
    where_clauses = []
    params: list = []

    if date_from:
        where_clauses.append("created_at >= ?")
        params.append(date_from)
    if date_to:
        # date_to 當天結束
        where_clauses.append("created_at < date(?, '+1 day')")
        params.append(date_to)

    where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
    params += [limit, offset]

    rows = conn.execute(
        f"""SELECT id, session_id, prompt_hash, classification, reason,
                   local_output, user_accepted, latency_ms,
                   tokens_prompt, tokens_response, created_at
            FROM router_decisions
            {where_sql}
            ORDER BY id DESC
            LIMIT ? OFFSET ?""",
        params,
    ).fetchall()
    return [dict(r) for r in rows]


# ── B-3 + B-4：採納率修正、Qwen 失敗率 ─────────────────────────────────────
@router.get("/stats")
def router_stats(conn: sqlite3.Connection = Depends(get_db)):
    """今日路由統計（qwen_error_count、acceptance_rate_7d、acceptance_rate_today）"""
    today = conn.execute(
        """SELECT
            COUNT(*) AS total_decisions,
            SUM(CASE WHEN classification='local' THEN 1 ELSE 0 END) AS local_count,
            SUM(CASE WHEN classification='claude' THEN 1 ELSE 0 END) AS claude_count,
            SUM(CASE WHEN reason='qwen_error' THEN 1 ELSE 0 END) AS qwen_error_count,
            AVG(latency_ms) AS avg_latency_ms,
            AVG(tokens_prompt) AS avg_prompt_tokens,
            MAX(created_at) AS last_decision_at
           FROM router_decisions
           WHERE date(created_at) = date('now')"""
    ).fetchone()

    total = today["total_decisions"] or 0
    local = today["local_count"] or 0
    claude = today["claude_count"] or 0
    qwen_error = today["qwen_error_count"] or 0

    # 近 7 天採納率
    acc_7d = conn.execute(
        """SELECT COUNT(*) AS total_local,
                  SUM(CASE WHEN user_accepted=1 THEN 1 ELSE 0 END) AS accepted
           FROM router_decisions
           WHERE classification='local'
             AND created_at >= datetime('now', '-7 days')"""
    ).fetchone()

    # 今日採納率
    acc_today = conn.execute(
        """SELECT COUNT(*) AS total_local,
                  SUM(CASE WHEN user_accepted=1 THEN 1 ELSE 0 END) AS accepted
           FROM router_decisions
           WHERE classification='local'
             AND date(created_at) = date('now')"""
    ).fetchone()

    def safe_rate(acc_row) -> float | None:
        t = acc_row["total_local"] or 0
        a = acc_row["accepted"] or 0
        return round(a / t, 4) if t > 0 else None

    return {
        "total_decisions": total,
        "local_count": local,
        "claude_count": claude,
        "qwen_error_count": qwen_error,
        "local_pct": round(local / total * 100, 1) if total > 0 else 0,
        "claude_pct": round(claude / total * 100, 1) if total > 0 else 0,
        "acceptance_rate_7d": safe_rate(acc_7d),
        "acceptance_rate_today": safe_rate(acc_today),
        "avg_latency_ms": round(today["avg_latency_ms"]) if today["avg_latency_ms"] else None,
        "avg_prompt_tokens": round(today["avg_prompt_tokens"]) if today["avg_prompt_tokens"] else None,
        "last_decision_at": today["last_decision_at"],
    }


# ── 對話脈絡：透過 session_id 撈 Layer 1 messages ──────────────────────────
@router.get("/decisions/{decision_id}/context")
def decision_context(decision_id: int, conn: sqlite3.Connection = Depends(get_db)):
    """取得決策對應的對話內容（決策時間點前 8 筆有內容訊息）"""
    dec = conn.execute(
        "SELECT session_id, created_at FROM router_decisions WHERE id=?",
        (decision_id,),
    ).fetchone()
    if not dec or not dec["session_id"]:
        return {"messages": [], "error": "no session_id"}

    # sessions.uuid = router_decisions.session_id
    sess = conn.execute(
        "SELECT id FROM sessions WHERE uuid=?", (dec["session_id"],)
    ).fetchone()
    if not sess:
        return {"messages": [], "error": "session not found in Layer 1"}

    # message_time 是 ISO8601（2026-04-21T22:26:07Z），created_at 是 SQLite datetime
    # 用 REPLACE 對齊格式後比較
    msgs = conn.execute(
        """SELECT role, content, message_time, has_tool_use, tool_names
           FROM messages
           WHERE session_id = ?
             AND content IS NOT NULL AND content != ''
             AND REPLACE(REPLACE(message_time,'T',' '),'Z','') <= ?
           ORDER BY message_time DESC
           LIMIT 8""",
        (sess["id"], dec["created_at"]),
    ).fetchall()

    return {
        "session_uuid": dec["session_id"],
        "decision_at": dec["created_at"],
        "messages": [dict(m) for m in reversed(msgs)],
    }


# ── B-5：系統狀態 ────────────────────────────────────────────────────────────
@router.get("/status")
def router_status(conn: sqlite3.Connection = Depends(get_db)):
    """檢查 Ollama 是否在線，回傳路由器設定 + 各 role yaml 狀態（Step 4 擴充）"""
    try:
        urllib.request.urlopen(CONFIG.services.ollama_base_url, timeout=2)
        ollama_online = True
    except Exception:
        ollama_online = False

    # 從 router_config + model_registry snapshot 讀當前模型（yaml 化後唯一真相來源）
    try:
        from layer_0_router._config import load_active_snapshot
        classifier_model = load_active_snapshot("classifier")["ollama_tag"]
        local_model = load_active_snapshot("responder")["ollama_tag"]
    except Exception:
        classifier_model = "unknown"
        local_model = "unknown"

    # 各推論 role 詳細狀態（供前端「yaml 已修改」徽章）
    roles: dict = {}
    for role in _INFERENCE_ROLES:
        try:
            cfg_row = conn.execute(
                "SELECT value, updated_at FROM router_config WHERE key=?",
                (f"{role}_model_yaml",),
            ).fetchone()
            if cfg_row is None:
                continue
            stem = cfg_row["value"]
            reg_row = conn.execute(
                "SELECT display_name, recorded_at FROM model_registry "
                "WHERE model_name=? AND is_current=1",
                (stem,),
            ).fetchone()
            if reg_row is None:
                continue

            yaml_path = _MODELS_DIR / f"{stem}.yaml"
            yaml_exists = yaml_path.exists()
            yaml_modified = False
            if yaml_exists and reg_row["recorded_at"]:
                try:
                    recorded_ts = datetime.fromisoformat(reg_row["recorded_at"]).timestamp()
                    yaml_modified = yaml_path.stat().st_mtime > recorded_ts
                except Exception:
                    pass

            roles[role] = {
                "stem": stem,
                "display_name": reg_row["display_name"],
                "snapshot_at": reg_row["recorded_at"],
                "yaml_exists": yaml_exists,
                "yaml_modified": yaml_modified,
            }
        except Exception:
            pass

    return {
        "ollama_online": ollama_online,
        "classifier_model": classifier_model,
        "local_model": local_model,
        "router_enabled": True,
        "roles": roles,
    }


# ── B-6：手動採納更新 ────────────────────────────────────────────────────────
class AcceptanceBody(BaseModel):
    accepted: bool


@router.put("/decisions/{decision_id}/acceptance")
def update_decision_acceptance(
    decision_id: int,
    body: AcceptanceBody,
    conn: sqlite3.Connection = Depends(get_db),
):
    """手動更新決策採納狀態"""
    conn.execute(
        "UPDATE router_decisions SET user_accepted=?, acceptance_source='manual' WHERE id=?",
        (1 if body.accepted else 0, decision_id),
    )
    conn.commit()
    return {"ok": True, "decision_id": decision_id, "accepted": body.accepted}


# ── B-2：分布偏移趨勢（trigger_policy signal C 監控）──────────────────────────
@router.get("/stats/drift")
def get_drift_stats(conn: sqlite3.Connection = Depends(get_db)):
    """
    各 adapter block 的分布偏移狀態。
    對每個 block：
      - 取近 7 天 embedding（新樣本）
      - 取上次訓練前的 embedding（歷史樣本）
      - 計算 centroid cosine distance
    回傳 {block, cosine_dist, threshold, passed}；無法計算時 None。
    """
    import math

    def _mean_vec(vecs: list[list[float]]) -> list[float]:
        n = len(vecs)
        return [sum(v[i] for v in vecs) / n for i in range(len(vecs[0]))]

    def _cosine_dist(a: list[float], b: list[float]) -> float:
        dot = sum(x * y for x, y in zip(a, b))
        na = math.sqrt(sum(x * x for x in a))
        nb = math.sqrt(sum(x * x for x in b))
        return 1.0 - dot / (na * nb + 1e-8)

    results = {}
    for adapter_block in [1, 2]:
        # 最近 7 天的 embedding
        new_rows = conn.execute(
            "SELECT embedding FROM exchange_embeddings "
            "WHERE created_at >= datetime('now', '-7 days') AND embedding IS NOT NULL"
        ).fetchall()

        if len(new_rows) < 5:
            results[f"block{adapter_block}"] = {
                "cosine_dist": None,
                "error": f"新樣本不足（{len(new_rows)} < 5）",
            }
            continue

        # 上次訓練的時間點
        last_run = conn.execute(
            "SELECT started_at FROM finetune_runs WHERE adapter_block=? AND status='done' "
            "ORDER BY id DESC LIMIT 1",
            (adapter_block,),
        ).fetchone()
        if not last_run:
            results[f"block{adapter_block}"] = {
                "cosine_dist": None,
                "error": "未有訓練歷史",
            }
            continue

        last_run_dt = last_run[0]
        old_rows = conn.execute(
            "SELECT embedding FROM exchange_embeddings "
            "WHERE created_at < ? AND embedding IS NOT NULL",
            (last_run_dt,),
        ).fetchall()

        if len(old_rows) < 5:
            results[f"block{adapter_block}"] = {
                "cosine_dist": None,
                "error": f"歷史樣本不足（{len(old_rows)} < 5）",
            }
            continue

        def to_vecs(rows):
            vecs = []
            for r in rows:
                try:
                    v = json.loads(r[0])
                    if isinstance(v, list) and v:
                        vecs.append([float(x) for x in v])
                except Exception:
                    pass
            return vecs or None

        new_vecs = to_vecs(new_rows)
        old_vecs = to_vecs(old_rows)
        if new_vecs is None or old_vecs is None:
            results[f"block{adapter_block}"] = {
                "cosine_dist": None,
                "error": "embedding 解析失敗",
            }
            continue

        new_centroid = _mean_vec(new_vecs)
        old_centroid = _mean_vec(old_vecs)
        cos_dist = _cosine_dist(new_centroid, old_centroid)

        results[f"block{adapter_block}"] = {
            "cosine_dist": round(cos_dist, 4),
            "threshold": _DRIFT_THRESHOLD,
            "passed": cos_dist <= _DRIFT_THRESHOLD,
            "new_samples": len(new_rows),
            "old_samples": len(old_rows),
        }

    return {
        "blocks": results,
        "threshold": _DRIFT_THRESHOLD,
        "status": "ok",
    }


# ── Step 4：模型清單與設定切換 ────────────────────────────────────────────────

def _fetch_ollama_tags() -> tuple[bool, set[str]]:
    """Proxy Ollama /api/tags；回 (reachable, installed_tag_set)。"""
    try:
        req = urllib.request.Request(f"{CONFIG.services.ollama_base_url}/api/tags")
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read())
        return True, {m["name"] for m in data.get("models", [])}
    except Exception:
        return False, set()


@router.get("/models/installed")
def models_installed():
    """比對 yaml 清單 vs Ollama 已安裝，分三類回傳。

    - yaml_configured：yaml 有且 Ollama 已下載（可用）
    - yaml_orphan：yaml 有但 Ollama 未下載（dropdown 灰選）
    - installed_no_yaml：Ollama 有但無 yaml（dropdown 灰選，需補寫 yaml）
    """
    from models_loader import MODELS

    reachable, installed_tags = _fetch_ollama_tags()

    yaml_configured = []
    yaml_orphan = []
    yaml_tag_set: set[str] = set()

    for cfg in MODELS.list_all():
        if cfg.ollama_tag is None:  # training_base 無 ollama_tag，跳過
            continue
        yaml_tag_set.add(cfg.ollama_tag)
        entry = {
            "stem": cfg.stem,
            "display_name": cfg.display_name,
            "ollama_tag": cfg.ollama_tag,
            "role": cfg.role,
        }
        if cfg.ollama_tag in installed_tags:
            yaml_configured.append(entry)
        else:
            yaml_orphan.append(entry)

    installed_no_yaml = [
        {"ollama_tag": tag}
        for tag in sorted(installed_tags)
        if tag not in yaml_tag_set
    ]

    return {
        "ollama_reachable": reachable,
        "yaml_configured": yaml_configured,
        "yaml_orphan": yaml_orphan,
        "installed_no_yaml": installed_no_yaml,
    }


@router.get("/models/by-role")
def models_by_role(role: str = Query(..., description="classifier | compressor | responder | training_base")):
    """回該 role 所有 yaml 清單，每筆含 status（installed / not_downloaded）。"""
    from models_loader import MODELS

    _VALID = {"classifier", "compressor", "responder", "embedder", "training_base"}
    if role not in _VALID:
        raise HTTPException(status_code=400, detail=f"role={role!r} 不合法，可選：{sorted(_VALID)}")

    _, installed_tags = _fetch_ollama_tags()

    result = []
    for cfg in MODELS.by_role(role):
        status = (
            "installed" if cfg.ollama_tag and cfg.ollama_tag in installed_tags
            else "not_downloaded" if cfg.ollama_tag
            else "no_ollama_tag"  # training_base
        )
        result.append({
            "stem": cfg.stem,
            "display_name": cfg.display_name,
            "ollama_tag": cfg.ollama_tag,
            "status": status,
        })

    return result


class RouterConfigBody(BaseModel):
    key: str    # e.g. classifier_model_yaml
    value: str  # new stem，e.g. classifier-gemma3-4b


@router.put("/config")
def put_router_config(
    body: RouterConfigBody,
    conn: sqlite3.Connection = Depends(get_db),
):
    """切換某 role 的 active model（body: {key, value=new_stem}）。

    1. 驗 stem yaml 存在（models_loader）
    2. 驗 model_registry 有此 stem is_current=1（若無則先 sync）
    3. 原子更新 router_config.value + updated_at
    4. 清 in-process snapshot cache
    """
    from models_loader import MODELS
    from models_db import sync_model_registry
    from layer_0_router._config import invalidate_cache

    # 1. 驗 yaml 存在
    try:
        MODELS.get_by_stem(body.value)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))

    # 2. 驗 router_config key 存在
    cfg_row = conn.execute(
        "SELECT value FROM router_config WHERE key=?", (body.key,)
    ).fetchone()
    if cfg_row is None:
        raise HTTPException(status_code=404, detail=f"router_config key={body.key!r} 不存在")

    # 3. 確保 model_registry 有此 stem（不在就先 sync）
    reg = conn.execute(
        "SELECT id FROM model_registry WHERE model_name=? AND is_current=1",
        (body.value,),
    ).fetchone()
    if reg is None:
        sync_model_registry(conn)
        reg = conn.execute(
            "SELECT id FROM model_registry WHERE model_name=? AND is_current=1",
            (body.value,),
        ).fetchone()
        if reg is None:
            raise HTTPException(
                status_code=409,
                detail=f"sync 後仍找不到 model_name={body.value!r}；請確認 yaml 檔名與 role 一致",
            )

    # 4. 原子更新
    conn.execute(
        "UPDATE router_config SET value=?, updated_at=datetime('now') WHERE key=?",
        (body.value, body.key),
    )
    conn.commit()
    invalidate_cache()

    return {"ok": True, "key": body.key, "value": body.value}


class ReloadBody(BaseModel):
    key: str  # e.g. classifier_model_yaml


@router.post("/config/reload")
def reload_router_config(
    body: ReloadBody,
    conn: sqlite3.Connection = Depends(get_db),
):
    """重新讀 yaml → 更新 model_registry snapshot（不換 stem）。

    用於「改完 yaml 想立即生效」，等同手動觸發 lifespan sync（冪等）。
    """
    from models_db import sync_model_registry
    from layer_0_router._config import invalidate_cache

    # 驗 key 存在並取 current stem
    cfg_row = conn.execute(
        "SELECT value FROM router_config WHERE key=?", (body.key,)
    ).fetchone()
    if cfg_row is None:
        raise HTTPException(status_code=404, detail=f"router_config key={body.key!r} 不存在")

    stats = sync_model_registry(conn)
    invalidate_cache()

    return {"ok": True, "key": body.key, "stem": cfg_row["value"], "sync_stats": stats}
