# layer_0_router/telemetry.py
"""Router 決策遙測：寫入 router_decisions，支援混合採納判定。"""

import hashlib
import logging
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from shiba_config import CONFIG

logger = logging.getLogger(__name__)

DB_PATH = CONFIG.paths.db

# C4：採納啟發式由「無否定即採納」改為多維結構。
# 否定關鍵字 → accepted=False / rewrote=False（明確拒絕）
# 改寫關鍵字 → accepted=False / rewrote=True（軟拒絕，user 自行修正）
# 確認關鍵字 → accepted=True  / rewrote=False（明確採納）
# 三者皆無  → accepted=None              （模糊；保留 NULL，等待下次或 manual）
_REJECTION_KEYWORDS = [
    "不對", "不行", "重做", "不符合", "不好", "錯了", "不是這樣",
    "換回", "用 claude", "用claude", "let claude", "redo", "try again",
    "that's wrong", "not right", "doesn't work",
]

# 軟拒絕：user 提供修正版（接受結構但要求改內容）
_REWRITE_KEYWORDS = [
    "改成", "應該是", "改為", "正確是", "正確的是",
    "should be", "actually", "fix to", "change to",
]

# 明確採納：user 主動確認正向訊號
_CONFIRM_KEYWORDS = [
    "好的", "好", "對", "正確", "謝謝", "感謝", "完美", "棒", "讚",
    "thanks", "thank you", "thx", "perfect", "great", "looks good", "lgtm",
]


@dataclass
class AcceptanceSignal:
    """單次 user follow-up 的多維採納判定結果。"""
    accepted: bool | None     # True=採納 / False=拒絕 / None=模糊（不寫入）
    rewrote: bool             # True=user 提供修正版（軟拒絕 + 高訓練價值）
    matched_keyword: str | None  # 命中的關鍵字（debug / audit）


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def prompt_hash(prompt: str) -> str:
    """SHA256 前 12 碼，不儲存明文。"""
    return hashlib.sha256(prompt.encode()).hexdigest()[:12]


def record_decision(
    *,
    session_id: str | None,
    prompt: str,
    classification: str,
    reason: str | None = None,
    local_output: str | None = None,
    latency_ms: int | None = None,
    tokens_prompt: int | None = None,
    tokens_response: int | None = None,
) -> int:
    """寫入一筆路由決策，回傳 decision_id（供後續採納更新使用）。"""
    phash = prompt_hash(prompt)
    output_preview = local_output[:500] if local_output else None

    with _conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO router_decisions
                (session_id, prompt_hash, classification, reason, local_output,
                 latency_ms, tokens_prompt, tokens_response)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (session_id, phash, classification, reason, output_preview,
             latency_ms, tokens_prompt, tokens_response),
        )
        return cur.lastrowid


def update_acceptance(
    decision_id: int,
    accepted: bool,
    rewrote: bool = False,
    source: str = "manual",
) -> None:
    """手動或自動更新採納狀態。source = 'manual' | 'auto'"""
    with _conn() as conn:
        conn.execute(
            """
            UPDATE router_decisions
               SET user_accepted = ?, user_rewrote = ?, acceptance_source = ?
             WHERE id = ?
            """,
            (1 if accepted else 0, 1 if rewrote else 0, source, decision_id),
        )
    logger.debug("採納更新 decision_id=%s accepted=%s source=%s", decision_id, accepted, source)


def infer_acceptance_from_text(next_user_message: str) -> AcceptanceSignal:
    """
    多維啟發式採納判定。

    優先序：拒絕 > 改寫 > 確認 > 模糊（None）。
    僅用於 auto 模式，manual 覆寫優先。模糊情境保留 NULL，
    避免「無否定即推定採納」的 false positive 拉高 acceptance_rate。
    """
    msg = next_user_message.lower()

    for kw in _REJECTION_KEYWORDS:
        if kw.lower() in msg:
            return AcceptanceSignal(accepted=False, rewrote=False, matched_keyword=kw)

    for kw in _REWRITE_KEYWORDS:
        if kw.lower() in msg:
            return AcceptanceSignal(accepted=False, rewrote=True, matched_keyword=kw)

    for kw in _CONFIRM_KEYWORDS:
        if kw.lower() in msg:
            return AcceptanceSignal(accepted=True, rewrote=False, matched_keyword=kw)

    return AcceptanceSignal(accepted=None, rewrote=False, matched_keyword=None)


def update_pending_decisions(session_id: str, next_user_message: str) -> int:
    """
    在 stop_hook 或下次 session_start_hook 呼叫：
    對同一 session 內 user_accepted=NULL 的 local 決策，
    以多維啟發式自動更新。回傳實際更新筆數（模糊訊號不寫入時為 0）。
    """
    signal = infer_acceptance_from_text(next_user_message)
    if signal.accepted is None:
        return 0  # 模糊訊號保留 NULL，等下次或 manual 覆寫

    with _conn() as conn:
        rows = conn.execute(
            """
            SELECT id FROM router_decisions
             WHERE session_id = ?
               AND classification = 'local'
               AND user_accepted IS NULL
               AND acceptance_source IS NULL
            """,
            (session_id,),
        ).fetchall()

        for row in rows:
            conn.execute(
                """
                UPDATE router_decisions
                   SET user_accepted = ?, user_rewrote = ?, acceptance_source = 'auto'
                 WHERE id = ?
                """,
                (1 if signal.accepted else 0, 1 if signal.rewrote else 0, row["id"]),
            )
        return len(rows)


def sync_sample_weights(session_id: str) -> int:
    """
    P1-3：根據 router_decisions 採納結果，更新同 session 的 training_samples weight。
      local + accepted → 1.0（正常）
      local + rejected → 1.5（重點學習）
      無 local decision（claude 接手）→ 2.0（最失敗）
    回傳更新筆數。
    """
    with _conn() as conn:
        row = conn.execute(
            "SELECT user_accepted FROM router_decisions "
            "WHERE session_id = ? AND classification = 'local' "
            "  AND user_accepted IS NOT NULL "
            "ORDER BY id DESC LIMIT 1",
            (session_id,),
        ).fetchone()

        if row is None:
            weight = 2.0  # claude 完全接手
        elif row["user_accepted"] == 1:
            weight = 1.0
        else:
            weight = 1.5

        result = conn.execute(
            "UPDATE training_samples SET weight = ? WHERE session_id = ?",
            (weight, session_id),
        )
        updated = result.rowcount
    if updated:
        logger.debug("P1-3 weight 同步：session=%s weight=%.1f 更新 %d 筆", session_id, weight, updated)
    return updated


def get_acceptance_rate(days: int = 7) -> float | None:
    """計算近 N 天 local 決策的採納率（已判定者）。"""
    with _conn() as conn:
        row = conn.execute(
            """
            SELECT COUNT(*) as total,
                   SUM(CASE WHEN user_accepted = 1 THEN 1 ELSE 0 END) as accepted
              FROM router_decisions
             WHERE classification = 'local'
               AND user_accepted IS NOT NULL
               AND created_at >= datetime('now', ?)
            """,
            (f"-{days} days",),
        ).fetchone()

    if not row or row["total"] == 0:
        return None
    return row["accepted"] / row["total"]
