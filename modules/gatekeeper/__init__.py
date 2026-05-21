"""gatekeeper feature 模組（PR-O-3）。

對應 CONFIG.features.shadow_gatekeeper（強制與 golden_retention 同開）。
透過 core.feature_registry 自我登記：

- schema_files：modules/gatekeeper/db/gatekeeper.sql
- init_fn：從舊 golden_samples 搬移歷史資料 + 註冊 "gate" hook
- depends_on：golden_retention（雙 flag 必須同開）

核心 layer 透過 core.feature_registry.get_hook("gate") 取得 run_gate；
未啟用時 get_hook 回 None，呼叫端略過閘門邏輯（最小核心路徑）。
"""

from __future__ import annotations

import logging
import sqlite3

from core.feature_registry import FeatureSpec, register, register_hook

from .migrations import migrate_legacy_golden_samples
from .service import run_gate

logger = logging.getLogger(__name__)


def _init(conn: sqlite3.Connection) -> None:
    """schema 套完後執行：搬移舊資料 + 註冊 gate hook。"""
    moved = migrate_legacy_golden_samples(conn)
    if moved:
        logger.info("gatekeeper: migrated %d rows from legacy golden_samples", moved)
    register_hook("gate", run_gate)


register(
    FeatureSpec(
        name="gatekeeper",
        flag="shadow_gatekeeper",
        schema_files=("modules/gatekeeper/db/gatekeeper.sql",),
        depends_on=("golden_retention",),
        init_fn=_init,
    )
)
