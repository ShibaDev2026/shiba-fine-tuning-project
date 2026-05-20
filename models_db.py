"""Model registry DB 同步器 — 將 config/models/ 的 yaml 變動寫入 model_registry。

設計與 models_loader.py 對稱：
- 由 models_loader.MODELS 取得當前 yaml 全集（loader 已負責解析 + 驗證）
- 本模組負責：算 sha256、與 DB 比對、寫入新版本

使用範例：

    import sqlite3
    from models_db import init_model_registry, sync_model_registry, get_current

    conn = sqlite3.connect("./data/shiba-brain.db")
    init_model_registry(conn)
    stats = sync_model_registry(conn)   # {"created": 5, "modified": 0, ...}
    cur = get_current(conn, "classifier-gemma3-4b")  # dict 含 snapshot

設計原則：
- sync 為冪等：同 hash 多次呼叫只更新 0 次新版
- 變動偵測一律走 sha256，不依賴 mtime / yaml_version
- 寫入路徑單一（本模組），讀取路徑可任意；保 snapshot single source
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import asdict
from pathlib import Path
from typing import Any

from models_loader import MODELS, ModelConfig

# ----------------------------------------------------------------
# 常量
# ----------------------------------------------------------------

# schema 檔位置：與 models_loader._models_dir 同一個 root
_SCHEMA_PATH: Path = (
    Path(__file__).resolve().parent / "config" / "db" / "schema_model_registry.sql"
)

# config/models/ 目錄；用於由 stem 推導檔案實體路徑（schema 不存 file_path）
_MODELS_DIR: Path = Path(__file__).resolve().parent / "config" / "models"


# ----------------------------------------------------------------
# 初始化
# ----------------------------------------------------------------


def init_model_registry(conn: sqlite3.Connection) -> None:
    """執行 schema_model_registry.sql；CREATE TABLE IF NOT EXISTS 故冪等。"""
    sql = _SCHEMA_PATH.read_text(encoding="utf-8")
    conn.executescript(sql)
    conn.commit()


# ----------------------------------------------------------------
# helpers
# ----------------------------------------------------------------


def _yaml_path(stem: str) -> Path:
    """由 stem 推導 yaml 實體路徑（schema 不存 file_path，每次推導）。"""
    return _MODELS_DIR / f"{stem}.yaml"


def _file_sha256(path: Path) -> str:
    """檔案 sha256，逐 chunk 讀取避免大檔吃記憶體（雖然 yaml 都 < 4KB）。"""
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _build_snapshot(cfg: ModelConfig) -> dict[str, Any]:
    """組 snapshot JSON 內容（不含 column 已有的 role/display_name/model_name）。

    inference / prompt / training 用 dataclasses.asdict()；None 保持 None。
    """
    return {
        "description": cfg.description,
        "ollama_tag": cfg.ollama_tag,
        "hf_repo": cfg.hf_repo,
        "inference": asdict(cfg.inference) if cfg.inference else None,
        "prompt": asdict(cfg.prompt) if cfg.prompt else None,
        "training": asdict(cfg.training) if cfg.training else None,
        "meta": asdict(cfg.meta),
        "maintenance": asdict(cfg.maintenance),
    }


def _next_version_seq(conn: sqlite3.Connection, model_name: str) -> int:
    """取下一個 version_seq；無歷史則回 1。"""
    row = conn.execute(
        "SELECT MAX(version_seq) AS m FROM model_registry WHERE model_name=?",
        (model_name,),
    ).fetchone()
    return (row["m"] if row and row["m"] is not None else 0) + 1


def _get_current_row(conn: sqlite3.Connection, model_name: str) -> sqlite3.Row | None:
    """取該 model_name 的 is_current=1 row；無則 None。"""
    return conn.execute(
        "SELECT * FROM model_registry WHERE model_name=? AND is_current=1",
        (model_name,),
    ).fetchone()


def _find_history_by_hash(
    conn: sqlite3.Connection, model_name: str, content_hash: str
) -> sqlite3.Row | None:
    """檢查同 (model_name, content_hash) 是否已有歷史 row（UNIQUE 約束）。"""
    return conn.execute(
        "SELECT * FROM model_registry WHERE model_name=? AND content_hash=?",
        (model_name, content_hash),
    ).fetchone()


def _switch_current(conn: sqlite3.Connection, target_id: int, model_name: str) -> None:
    """把 model_name 的 is_current 切到 target_id；其餘設 0。"""
    conn.execute(
        "UPDATE model_registry SET is_current=0 WHERE model_name=? AND is_current=1",
        (model_name,),
    )
    conn.execute(
        "UPDATE model_registry SET is_current=1 WHERE id=?",
        (target_id,),
    )


def _insert_version(
    conn: sqlite3.Connection,
    cfg: ModelConfig,
    content_hash: str,
    change_kind: str,
) -> None:
    """寫一筆新版（自動把舊 current 清為 0）。"""
    conn.execute(
        "UPDATE model_registry SET is_current=0 WHERE model_name=? AND is_current=1",
        (cfg.stem,),
    )
    conn.execute(
        """
        INSERT INTO model_registry
          (model_name, version_seq, is_current, content_hash, role,
           display_name, snapshot, change_kind)
        VALUES (?, ?, 1, ?, ?, ?, ?, ?)
        """,
        (
            cfg.stem,
            _next_version_seq(conn, cfg.stem),
            content_hash,
            cfg.role,
            cfg.display_name,
            json.dumps(_build_snapshot(cfg), ensure_ascii=False),
            change_kind,
        ),
    )


def _insert_removed(conn: sqlite3.Connection, prev: sqlite3.Row) -> None:
    """檔案不見時寫一筆 removed 版本；snapshot/role/display_name 沿用 prev row。"""
    conn.execute(
        "UPDATE model_registry SET is_current=0 WHERE id=?",
        (prev["id"],),
    )
    # 為了不撞 UNIQUE(model_name, content_hash)，removed 版的 content_hash 加 ":removed:<seq>" 後綴
    next_seq = _next_version_seq(conn, prev["model_name"])
    removed_hash = f"{prev['content_hash']}:removed:{next_seq}"
    conn.execute(
        """
        INSERT INTO model_registry
          (model_name, version_seq, is_current, content_hash, role,
           display_name, snapshot, change_kind)
        VALUES (?, ?, 1, ?, ?, ?, ?, 'removed')
        """,
        (
            prev["model_name"],
            next_seq,
            removed_hash,
            prev["role"],
            prev["display_name"],
            prev["snapshot"],
        ),
    )


# ----------------------------------------------------------------
# sync 主流程
# ----------------------------------------------------------------


def sync_model_registry(conn: sqlite3.Connection) -> dict[str, int]:
    """掃 MODELS（loader singleton）+ DB 現況，寫入差異。

    回傳統計：{"created": n, "modified": n, "restored": n, "removed": n, "unchanged": n}
    全程在單一事務，任一步驟失敗整體 rollback。
    """
    stats = {"created": 0, "modified": 0, "restored": 0, "removed": 0, "unchanged": 0}

    try:
        conn.execute("BEGIN")

        seen_stems: set[str] = set()

        for cfg in MODELS.list_all():
            seen_stems.add(cfg.stem)
            file_hash = _file_sha256(_yaml_path(cfg.stem))
            current = _get_current_row(conn, cfg.stem)

            if current is None:
                # 情境 ①：初次發現
                _insert_version(conn, cfg, file_hash, change_kind="created")
                stats["created"] += 1
                continue

            if current["content_hash"] == file_hash:
                # 情境 ③：hash 同 current，無動作
                stats["unchanged"] += 1
                continue

            # hash 不同：先看是否為 hash 撞到舊歷史版本（含 removed-suffix 排除）
            history = _find_history_by_hash(conn, cfg.stem, file_hash)
            if history is not None:
                # 情境 ⑤：跳回某舊版本（hash 完全相同）
                _switch_current(conn, history["id"], cfg.stem)
                stats["restored"] += 1
                continue

            # 情境 ② / ⑥：新 hash → 寫新版
            # 若上一版是 removed，本次算 restored；否則 modified
            kind = "restored" if current["change_kind"] == "removed" else "modified"
            _insert_version(conn, cfg, file_hash, change_kind=kind)
            stats[kind] += 1

        # 情境 ④：DB 有 current row 但磁碟無此 yaml → 寫 removed 版
        rows = conn.execute(
            "SELECT * FROM model_registry WHERE is_current=1 AND change_kind != 'removed'"
        ).fetchall()
        for prev in rows:
            if prev["model_name"] not in seen_stems:
                _insert_removed(conn, prev)
                stats["removed"] += 1

        conn.commit()
    except Exception:
        conn.rollback()
        raise

    return stats


# ----------------------------------------------------------------
# 讀取 API
# ----------------------------------------------------------------


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    """sqlite3.Row → dict，並把 snapshot JSON 解析成物件。"""
    d = dict(row)
    d["snapshot"] = json.loads(d["snapshot"])
    return d


def get_current(conn: sqlite3.Connection, model_name: str) -> dict[str, Any] | None:
    """取某 yaml 當前版（含 snapshot 解析後 dict）；無或已 removed 回 None。"""
    row = conn.execute(
        """
        SELECT * FROM model_registry
        WHERE model_name=? AND is_current=1 AND change_kind != 'removed'
        """,
        (model_name,),
    ).fetchone()
    return _row_to_dict(row) if row else None


def list_current_by_role(conn: sqlite3.Connection, role: str) -> list[dict[str, Any]]:
    """列指定 role 的所有當前 yaml（給前端 dropdown）；排除 removed。"""
    rows = conn.execute(
        """
        SELECT * FROM model_registry
        WHERE role=? AND is_current=1 AND change_kind != 'removed'
        ORDER BY display_name
        """,
        (role,),
    ).fetchall()
    return [_row_to_dict(r) for r in rows]


def list_history(conn: sqlite3.Connection, model_name: str) -> list[dict[str, Any]]:
    """某 yaml 的完整版本歷史（最新在前）。"""
    rows = conn.execute(
        """
        SELECT * FROM model_registry
        WHERE model_name=?
        ORDER BY version_seq DESC
        """,
        (model_name,),
    ).fetchall()
    return [_row_to_dict(r) for r in rows]


__all__ = [
    "init_model_registry",
    "sync_model_registry",
    "get_current",
    "list_current_by_role",
    "list_history",
]
