"""multi_judge_v2 feature 的 DB migration（PR-O-5）。

舊資料來源 evaluation/migration_evaluation.sql 的 judge_agreement_logs
（ragas_eval feature 領域）。若舊表存在 → 一次性 INSERT...SELECT
到 multi_judge_v2_agreement_logs，idempotent。
"""

from __future__ import annotations

import sqlite3


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone()
    return row is not None


def migrate_legacy_agreement_logs(conn: sqlite3.Connection) -> int:
    """搬舊 judge_agreement_logs → multi_judge_v2_agreement_logs（idempotent）。"""
    if not _table_exists(conn, "judge_agreement_logs"):
        return 0
    if not _table_exists(conn, "multi_judge_v2_agreement_logs"):
        raise RuntimeError(
            "multi_judge_v2_agreement_logs 表不存在；schema_files 應先於 init_fn 套用"
        )
    # 舊表沒有 vendor_diversity 欄位，補 0（未知）；id 用舊值避免衝突
    cur = conn.execute(
        """
        INSERT INTO multi_judge_v2_agreement_logs
            (id, sample_id, votes_json, vendor_diversity,
             fleiss_kappa, pairwise_disagreement, ragas_faithfulness, evaluated_at)
        SELECT id, sample_id, votes_json, 0,
               fleiss_kappa, pairwise_disagreement, ragas_faithfulness, evaluated_at
        FROM judge_agreement_logs
        WHERE id NOT IN (SELECT id FROM multi_judge_v2_agreement_logs)
        """
    )
    conn.commit()
    return cur.rowcount or 0
