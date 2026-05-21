"""ragas feature 模組（PR-O-6）。

對應 CONFIG.features.ragas_eval；feature off 時不建 ragas_* 表、不搬舊資料。
schema_files：db/ragas.sql（ragas_evaluation_results / ragas_retrieval_golden_set）
init_fn：一次性搬舊 evaluation_results / retrieval_golden_set
depends_on：multi_judge_v2（Layer 2 report 讀 multi_judge_v2_agreement_logs 計 Fleiss κ）
"""

from __future__ import annotations

import logging
import sqlite3

from core.feature_registry import FeatureSpec, register

from .migrations import migrate_legacy

logger = logging.getLogger(__name__)


def _init(conn: sqlite3.Connection) -> None:
    moved = migrate_legacy(conn)
    for table, n in moved.items():
        if n:
            logger.info("ragas: migrated %d rows into %s", n, table)


register(
    FeatureSpec(
        name="ragas",
        flag="ragas_eval",
        schema_files=("modules/ragas/db/ragas.sql",),
        depends_on=("multi_judge_v2",),
        init_fn=_init,
    )
)
