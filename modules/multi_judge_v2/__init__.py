"""multi_judge_v2 feature 模組（PR-O-5）。

對應 CONFIG.features.multi_judge_v2；feature off 時呼叫端走 v1 multi_judge_score。
schema_files：multi_judge_v2.sql（multi_judge_v2_agreement_logs）
init_fn：搬舊 judge_agreement_logs 資料 + 註冊 "judge_score" hook
"""

from __future__ import annotations

import logging
import sqlite3

from core.feature_registry import FeatureSpec, register, register_hook

from .migrations import migrate_legacy_agreement_logs
from .service import multi_judge_score_v2

logger = logging.getLogger(__name__)


def _init(conn: sqlite3.Connection) -> None:
    moved = migrate_legacy_agreement_logs(conn)
    if moved:
        logger.info("multi_judge_v2: migrated %d rows from legacy judge_agreement_logs", moved)
    register_hook("judge_score", multi_judge_score_v2)


register(
    FeatureSpec(
        name="multi_judge_v2",
        flag="multi_judge_v2",
        schema_files=("modules/multi_judge_v2/db/multi_judge_v2.sql",),
        depends_on=(),
        init_fn=_init,
    )
)
