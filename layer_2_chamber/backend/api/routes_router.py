# layer_2_chamber/backend/api/routes_router.py
"""Phase 0 路由層 API — router_decisions 查詢、統計、狀態與採納更新"""

import sqlite3
import urllib.request
import urllib.error
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from ..core.config import get_db
from shiba_config import CONFIG

router = APIRouter(prefix="/api/v1/router", tags=["router"])


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
def router_status():
    """檢查 Ollama 是否在線，回傳路由器設定"""
    try:
        urllib.request.urlopen(CONFIG.services.ollama_base_url, timeout=2)
        ollama_online = True
    except Exception:
        ollama_online = False

    return {
        "ollama_online": ollama_online,
        "classifier_model": "gemma3:2b",
        "local_model": "qwen3:30b-a3b",
        "router_enabled": True,
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
