"""核心 fallback 觸發策略（PR-O-4）。

ebbinghaus_trigger feature off 時 runner 使用本檔；
固定 approved≥30 + 首次訓練人工把關，不含 Ebbinghaus / 採納退化 / 分布偏移信號。

完整三信號版搬至 modules/ebbinghaus_trigger/service.py，由 feature_registry
透過 "trigger" hook 注入。`TriggerDecision` 由本檔定義為共用型別，
v2 import 自此處以保持單一資料來源。
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# 最小訓練樣本門檻；basic 與 v2 共用此常數
MIN_SAMPLES = 30


@dataclass
class TriggerDecision:
    """訓練觸發決策。basic 與 v2 共用，v2 額外填三個 signal_* 欄位。"""

    should_train: bool
    reason: str
    approved_count: int
    signal_a: bool = False
    signal_b: bool = False
    signal_c: bool = False
    # D：首次訓練人工把關；True 時 runner 建立 pending_manual run
    requires_manual: bool = False


def should_trigger_basic(conn: sqlite3.Connection, adapter_block: int) -> TriggerDecision:
    """核心 fallback 策略：approved≥30 即觸發；首次訓練標記 requires_manual。"""
    approved = _count_approved(conn, adapter_block)
    if approved < MIN_SAMPLES:
        return TriggerDecision(
            should_train=False,
            reason=f"approved={approved} < MIN_SAMPLES={MIN_SAMPLES}",
            approved_count=approved,
        )

    is_first_run = _last_finetune_done(conn, adapter_block) is None
    reason = f"basic: approved={approved} 達門檻"
    if is_first_run:
        logger.info("block%d 首次訓練偵測到，標記 requires_manual（%s）", adapter_block, reason)

    return TriggerDecision(
        should_train=True,
        reason=reason,
        approved_count=approved,
        requires_manual=is_first_run,
    )


def _count_approved(conn: sqlite3.Connection, adapter_block: int) -> int:
    row = conn.execute(
        "SELECT COUNT(*) FROM training_samples WHERE status='approved' AND adapter_block=?",
        (adapter_block,),
    ).fetchone()
    return row[0]


def _last_finetune_done(conn: sqlite3.Connection, adapter_block: int) -> str | None:
    row = conn.execute(
        "SELECT started_at FROM finetune_runs "
        "WHERE adapter_block=? AND status='done' "
        "ORDER BY id DESC LIMIT 1",
        (adapter_block,),
    ).fetchone()
    return row[0] if row else None
