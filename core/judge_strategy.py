"""JudgeStrategy 介面（PR-O-5）。

核心對 judge 行為的抽象：給定 sample → 回 vote 結果 dict。
具體實作：
- v1：layer_2_chamber/backend/services/multi_judge.py（三方投票，不寫 log）
- v2：modules/multi_judge_v2/service.py（強制 vendor 多樣 + 寫 multi_judge_v2_agreement_logs）

注入點：core.feature_registry 的 "judge_score" hook。
未註冊時呼叫端 fallback v1 multi_judge_score（最小核心路徑）。

DIP 落地：core 只依賴 JudgeStrategy 介面，不知道 v1/v2 存在。
"""

from __future__ import annotations

import sqlite3
from typing import Protocol


class JudgeStrategy(Protocol):
    """評分策略介面。
    回傳 dict：{'status', 'weight', 'score', 'votes', 'high_value'}
    （與既有 multi_judge_score 回傳格式保持相容）。
    """

    def __call__(
        self,
        conn: sqlite3.Connection,
        sample_id: int,
        instruction: str,
        input_text: str,
        output: str,
        session_id: str | None = None,
    ) -> dict: ...
