"""multi_judge v2 strategy（PR-O-5）。

包覆 v1 multi_judge_score：
- 強制 vendor 多樣：vote 集合中不同 vendor 數 < 2 → 視為共識不足，status 降為 pending
- 寫入 multi_judge_v2_agreement_logs（含 vendor_diversity、votes_json，Fleiss κ 由批次另算）

不重新實作投票邏輯，避免 v1/v2 行為漂移；v2 是「v1 + 額外約束 + log」。
"""

from __future__ import annotations

import json
import logging
import sqlite3

from layer_2_chamber.backend.services.multi_judge import multi_judge_score

logger = logging.getLogger(__name__)

_MIN_VENDOR_DIVERSITY = 2  # v2 至少 2 個不同 vendor 才採信投票結果


def multi_judge_score_v2(
    conn: sqlite3.Connection,
    sample_id: int,
    instruction: str,
    input_text: str,
    output: str,
    session_id: str | None = None,
) -> dict:
    """v2 strategy：呼叫 v1 後做 vendor 多樣強制 + agreement log 寫入。"""
    result = multi_judge_score(conn, sample_id, instruction, input_text, output, session_id)

    votes = result.get("votes") or []
    vendors = {v.get("vendor", "unknown") for v in votes}
    diversity = len(vendors - {"unknown"}) or len(vendors)

    # vendor 多樣強制：未達門檻且非 Shiba 採納覆寫 → 降為 pending（待補不同 vendor 重投）
    if (
        result["status"] == "approved"
        and not result.get("high_value")
        and diversity < _MIN_VENDOR_DIVERSITY
    ):
        logger.warning(
            "sample %d v2：vendor 多樣不足（%d < %d），status 降為 pending",
            sample_id, diversity, _MIN_VENDOR_DIVERSITY,
        )
        with conn:
            conn.execute(
                "UPDATE training_samples SET status='pending' WHERE id=?",
                (sample_id,),
            )
        result["status"] = "pending"
        result["weight"] = 1.0

    _log_agreement(conn, sample_id, votes, diversity)
    return result


def _log_agreement(
    conn: sqlite3.Connection,
    sample_id: int,
    votes: list[dict],
    diversity: int,
) -> None:
    """寫入 multi_judge_v2_agreement_logs（失敗靜默，不炸主流程）。"""
    if not votes:
        return
    try:
        conn.execute(
            """INSERT INTO multi_judge_v2_agreement_logs
               (sample_id, votes_json, vendor_diversity)
               VALUES (?, ?, ?)""",
            (sample_id, json.dumps(votes, ensure_ascii=False), diversity),
        )
        conn.commit()
    except Exception as e:
        logger.debug("multi_judge_v2_agreement_logs 寫入失敗（無害）：%s", e)
