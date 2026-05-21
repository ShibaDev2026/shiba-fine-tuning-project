"""gatekeeper feature 的 DB migration 邏輯。

PR-O-3：原 layer_2_chamber/backend/core/config.py 內
`_run_golden_samples_migration` 搬到此處並改名為 gatekeeper_golden_samples。

由 modules/gatekeeper/__init__.py 的 init_fn 在 feature 啟用時呼叫；
若舊 DB 已存在 golden_samples（PR-O-3 前的歷史資料），則一次性將
資料搬到 gatekeeper_golden_samples（idempotent，重跑無副作用）。
"""

from __future__ import annotations

import sqlite3


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone()
    return row is not None


def migrate_legacy_golden_samples(conn: sqlite3.Connection) -> int:
    """將舊 golden_samples 資料搬到 gatekeeper_golden_samples（idempotent）。

    回傳實際搬移筆數；舊表不存在或新表已有同 id 則略過該筆。
    """
    if not _table_exists(conn, "golden_samples"):
        return 0
    if not _table_exists(conn, "gatekeeper_golden_samples"):
        # 新表理應由 schema_files 先套用；若不存在代表呼叫順序錯誤
        raise RuntimeError(
            "gatekeeper_golden_samples 表不存在；schema_files 應先於 init_fn 套用"
        )

    cur = conn.execute(
        """
        INSERT INTO gatekeeper_golden_samples
            (id, source_sample_id, instruction, input, expected_output,
             event_type, score, frozen_at, is_active)
        SELECT id, source_sample_id, instruction, input, expected_output,
               event_type, score, frozen_at, is_active
        FROM golden_samples
        WHERE id NOT IN (SELECT id FROM gatekeeper_golden_samples)
        """
    )
    conn.commit()
    return cur.rowcount or 0
