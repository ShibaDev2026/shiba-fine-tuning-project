# layer_2_chamber/backend/services/multi_judge.py
"""
P1-2 多 Judge 投票（SEAL ReSTEM^EM 精神）。

投票規則：
  3/3 approved → status='approved', weight=1.0
  2/3 approved → status='approved', weight=0.5（soft label）
  ≤1/3 approved → status='rejected'
  Shiba 採納（router_decisions.user_accepted=1）→ 無論 judge 結果，強制 status='approved'
  （weight 由 stop_hook 的 P1-3 sync_sample_weights 另行設定）

Judge approved 判定：score ≥ 8.0
"""

import logging
import sqlite3

from .teacher_service import (
    get_active_teachers,
    _call_teacher,        # noqa: PLC2701
    _log_usage,           # noqa: PLC2701
    _update_sample_score, # noqa: PLC2701
    is_quota_available,
)

logger = logging.getLogger(__name__)

_APPROVED_THRESHOLD = 8.0  # score >= 此值算一票 approved


def multi_judge_score(
    conn: sqlite3.Connection,
    sample_id: int,
    instruction: str,
    input_text: str,
    output: str,
    session_id: str | None = None,
) -> dict:
    """
    三方投票評分，回傳：
    {'status': str, 'weight': float, 'score': float,
     'votes': list, 'high_value': bool}
    """
    teachers = get_active_teachers(conn)
    available = [t for t in teachers if is_quota_available(conn, t)]

    votes = _collect_votes(conn, sample_id, instruction, input_text, output, available)

    if not votes:
        logger.warning("sample %d：所有 Judge 配額耗盡或呼叫失敗，保持 pending", sample_id)
        return {"status": "pending", "weight": 1.0, "score": None, "votes": [], "high_value": False}

    approved_votes = sum(1 for v in votes if v["approved"])
    avg_score = sum(v["score"] for v in votes) / len(votes)

    # 隱性標籤：Shiba 採納 → 強制 approved（高信心信號壓過 judge）
    high_value = _check_shiba_accepted(conn, session_id)

    if high_value:
        status = "approved"
        weight = 1.0  # P1-3 sync_sample_weights 會依採納狀態覆寫
        reason = "Shiba 隱性採納（high_value，覆蓋 judge 結果）"
        logger.info("sample %d high_value：judge_votes=%d/3，隱性採納覆蓋", sample_id, approved_votes)
    elif approved_votes == len(votes) and len(votes) >= 2:
        # 全數同意（至少 2 judge）→ 高信心
        status, weight = "approved", 1.0
        reason = f"全數 {len(votes)} judge approved（avg={avg_score:.1f}）"
    elif approved_votes >= 2:
        # 多數同意（2/3）→ soft label
        status, weight = "approved", 0.5
        reason = f"{approved_votes}/{len(votes)} judge approved（soft label）"
    else:
        # 0 或 1 票 → 拒絕
        status, weight = "rejected", 1.0
        reason = f"不足票數（{approved_votes}/{len(votes)} approved）"
        logger.debug("sample %d rejected：votes=%s", sample_id, votes)

    _update_sample_score(conn, sample_id, avg_score, reason, status)
    if status == "approved":
        # 寫入 weight（soft label 或 1.0）
        conn.execute(
            "UPDATE training_samples SET weight=? WHERE id=?",
            (weight, sample_id),
        )
        conn.commit()

    return {
        "status": status,
        "weight": weight,
        "score": avg_score,
        "votes": votes,
        "high_value": high_value,
    }


def _collect_votes(
    conn: sqlite3.Connection,
    sample_id: int,
    instruction: str,
    input_text: str,
    output: str,
    available_teachers: list,
) -> list[dict]:
    """呼叫最多 3 個可用 Teacher，蒐集投票。"""
    votes = []
    for teacher in available_teachers[:3]:
        result = _call_teacher(teacher, instruction, input_text, output)
        if result is None:
            continue
        _log_usage(conn, teacher["id"], sample_id)
        votes.append({
            "teacher_id": teacher["id"],
            "teacher_name": teacher["name"],
            "score": result["score"],
            "approved": result["score"] >= _APPROVED_THRESHOLD,
            "reason": result["reason"],
        })
    return votes


def _check_shiba_accepted(conn: sqlite3.Connection, session_id: str | None) -> bool:
    """查 router_decisions：若 Shiba 採納（local + accepted=1）→ high_value=True。"""
    if not session_id:
        return False
    row = conn.execute(
        "SELECT id FROM router_decisions "
        "WHERE session_id=? AND classification='local' AND user_accepted=1 "
        "LIMIT 1",
        (session_id,),
    ).fetchone()
    return row is not None
