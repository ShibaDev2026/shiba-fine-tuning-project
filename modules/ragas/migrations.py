"""ragas feature 的 DB migration（PR-O-6）。

從舊 evaluation_results / retrieval_golden_set 一次性搬到加前綴的新表，
idempotent（同 id 不重複插入）。
"""

from __future__ import annotations

import sqlite3


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone() is not None


def _migrate(conn: sqlite3.Connection, old: str, new: str, cols: str) -> int:
    if not _table_exists(conn, old):
        return 0
    if not _table_exists(conn, new):
        raise RuntimeError(f"{new} 表不存在；schema_files 應先於 init_fn 套用")
    cur = conn.execute(
        f"INSERT INTO {new} ({cols}) "
        f"SELECT {cols} FROM {old} WHERE id NOT IN (SELECT id FROM {new})"
    )
    conn.commit()
    return cur.rowcount or 0


def migrate_legacy(conn: sqlite3.Connection) -> dict[str, int]:
    """搬兩張舊表至加前綴版本，回傳每張表搬移筆數。"""
    moved = {
        "ragas_evaluation_results": _migrate(
            conn, "evaluation_results", "ragas_evaluation_results",
            "id, run_id, phase, metric_name, metric_value, sample_id, "
            "evaluator_model, created_at, metadata",
        ),
        "ragas_retrieval_golden_set": _migrate(
            conn, "retrieval_golden_set", "ragas_retrieval_golden_set",
            "id, query, expected_session_uuids, expected_exchange_ids, "
            "expected_answer, annotator, is_active, created_at, notes",
        ),
    }
    return moved
