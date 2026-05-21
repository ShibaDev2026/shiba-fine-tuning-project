"""ebbinghaus_trigger feature 模組（PR-O-4）。

對應 CONFIG.features.ebbinghaus_trigger；feature off 時 runner 用
layer_3_pipeline/trigger_policy_basic.py 的 should_trigger_basic（固定 approved≥30）。

本模組無 schema 變動（純讀核心 finetune_runs / router_decisions /
exchange_embeddings / training_samples），故 schema_files 為空。

注入點：feature 啟用後 init_fn 註冊 "trigger" hook，runner 透過 get_hook
取得；hook=None 即代表 feature off，走 basic fallback。
"""

from __future__ import annotations

import logging
import sqlite3

from core.feature_registry import FeatureSpec, register, register_hook

from .service import should_trigger

logger = logging.getLogger(__name__)


def _init(conn: sqlite3.Connection) -> None:
    register_hook("trigger", should_trigger)
    logger.info("ebbinghaus_trigger: 註冊 trigger hook（v2 三信號策略）")


register(
    FeatureSpec(
        name="ebbinghaus_trigger",
        flag="ebbinghaus_trigger",
        schema_files=(),
        depends_on=(),
        init_fn=_init,
    )
)
