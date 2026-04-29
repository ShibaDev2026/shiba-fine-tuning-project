"""
exchanges.py — 四步循環語意層重建邏輯（Layer 1 衍生表）

職責：
    從 messages + branch_messages + tool_executions 重建 exchanges + exchange_messages 兩張衍生表，
    讓「user → assistant(decision+tool_call) → tool_result → assistant(final response)」
    的語意關聯能直接以 SQL JOIN 取得，無需重新 parse raw_content。

邊界定義：
    一個 exchange 從一個「真正的 user 訊息」開始，到下一個「真正的 user 訊息」之前結束。
    包含中間所有 assistant tool_use 與 tool_result_user 訊息（多輪 tool 循環）。

判斷「真正 user」的方式：
    role='user' 且 raw_content 解開後不含 tool_result block。
    role='user' 但含 tool_result block → 視為包裝（不開新 exchange）。

idempotent 重建：
    rebuild_exchanges_for_session 採 DELETE + INSERT，重跑同一 session 結果完全一致。
    exchange_messages 透過 ON DELETE CASCADE 自動清理。
"""

from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass, field
from typing import Any

from layer_1_memory.lib.db import decompress_text, get_connection

logger = logging.getLogger(__name__)


# ============================================================
# 工具函式
# ============================================================

def _fetch_branch_messages(
    conn: sqlite3.Connection, branch_id: int
) -> list[sqlite3.Row]:
    """讀取該 branch 的所有 messages（按 branch_messages.seq 排序）"""
    return conn.execute(
        """SELECT m.id, m.uuid, m.role, m.content, m.raw_content, m.is_compressed,
                  m.has_tool_use, m.tool_names, m.message_time
           FROM branch_messages bm
           JOIN messages m ON m.id = bm.message_id
           WHERE bm.branch_id = ?
           ORDER BY bm.seq, m.id""",
        (branch_id,),
    ).fetchall()


def _is_real_user(row: sqlite3.Row) -> bool:
    """
    判斷一筆 user 訊息是否為「真正使用者輸入」（而非 tool_result 包裝）。

    判斷規則（從強到弱）：
      1. role != 'user'                                    → False
      2. raw_content 解開為 JSON list 且任一 block.type='tool_result' → False
      3. raw_content 解開為純字串                            → True
      4. raw_content 解開為 list 且無 tool_result            → True
      5. raw_content 缺失或解析失敗 → 退回 content 非空判斷    → True/False
    """
    if row["role"] != "user":
        return False

    raw_str = decompress_text(row["raw_content"], row["is_compressed"])
    if not raw_str:
        # 早期資料無 raw_content：依 content 是否有實質文字判斷
        content = row["content"]
        return bool(content and content.strip())

    try:
        data = json.loads(raw_str)
    except (json.JSONDecodeError, TypeError):
        # raw_content 非合法 JSON：退回 content 判斷
        content = row["content"]
        return bool(content and content.strip())

    if isinstance(data, str):
        # 純字串 = 使用者直接輸入
        return True

    if isinstance(data, list):
        # 任一 block 為 tool_result → 認定為包裝訊息
        for block in data:
            if isinstance(block, dict) and block.get("type") == "tool_result":
                return False
        # list 中無 tool_result → 真正 user 輸入
        return True

    # dict 或其他型別：保守視為非真正 user
    return False


def _classify_tentative_role(row: sqlite3.Row) -> str:
    """
    暫定 role_in_exchange（finalize 階段會將被選中的訊息覆寫為 'assistant_final'）。

      role='user'  + tool_result wrapper → 'tool_result_user'
      role='assistant' + has_tool_use=1  → 'assistant_tool'
      role='assistant' + has_tool_use=0  → 'assistant_text'
    """
    if row["role"] == "user":
        return "tool_result_user"
    # role == 'assistant'
    if row["has_tool_use"]:
        return "assistant_tool"
    return "assistant_text"


def _fetch_tool_stats(
    conn: sqlite3.Connection, message_ids: list[int]
) -> tuple[int, bool]:
    """
    從 tool_executions 統計：
      - 總 tool_use 配對數（一個 message 可有多個 tool_use）
      - 是否含 is_error=1（任一即為 True）
    """
    if not message_ids:
        return (0, False)

    placeholders = ",".join("?" * len(message_ids))
    row = conn.execute(
        f"""SELECT COUNT(*) AS use_count,
                   COALESCE(SUM(CASE WHEN is_error=1 THEN 1 ELSE 0 END), 0) AS error_count
            FROM tool_executions
            WHERE message_id IN ({placeholders})""",
        message_ids,
    ).fetchone()
    return (int(row["use_count"] or 0), bool(row["error_count"]))


# ============================================================
# 核心：state machine 建 exchange
# ============================================================

@dataclass
class _ExchangeWIP:
    """state machine 掃描中暫存的 exchange（尚未 finalize）"""
    user_message_id: int
    started_at: str | None
    members: list[dict[str, Any]] = field(default_factory=list)
    # member dict: {'row': sqlite3.Row, 'role_in_exchange': str}


def _build_exchanges_for_branch(
    conn: sqlite3.Connection, branch_id: int, is_active_branch: bool
) -> list[dict[str, Any]]:
    """
    對該 branch 線性掃描所有 messages，依「真正 user」邊界切出 exchange 序列。
    回傳 finalize 後的 exchange dict 列表（caller 負責填入 session_id/branch_id/exchange_idx）。
    """
    rows = _fetch_branch_messages(conn, branch_id)

    exchanges: list[dict[str, Any]] = []
    current: _ExchangeWIP | None = None

    for row in rows:
        if _is_real_user(row):
            # 收尾上一個（已 completed：因有下一個 user 來閉合）
            if current is not None:
                exchanges.append(_finalize_exchange(conn, current, status="completed"))
            # 開新 exchange
            current = _ExchangeWIP(
                user_message_id=row["id"],
                started_at=row["message_time"],
            )
            current.members.append({"row": row, "role_in_exchange": "user_open"})
        else:
            # 加入當前 exchange 中段
            if current is None:
                # 邊緣情況：branch 開頭就是 tool_result（理論不應發生，保險跳過）
                logger.debug(
                    "branch %d 開頭遇到非 user 訊息（uuid=%s），跳過",
                    branch_id, row["uuid"],
                )
                continue
            current.members.append({
                "row": row,
                "role_in_exchange": _classify_tentative_role(row),
            })

    # 收尾最後一個 exchange
    if current is not None:
        final_status = "in_progress" if is_active_branch else "abandoned"
        exchanges.append(_finalize_exchange(conn, current, status=final_status))

    return exchanges


def _finalize_exchange(
    conn: sqlite3.Connection, wip: _ExchangeWIP, status: str
) -> dict[str, Any]:
    """
    對暫存 exchange 完成統計、找 final_assistant、取得 tool_executions 統計，
    回傳 INSERT 用的 dict（含 members 列表給 exchange_messages 寫入）。

    final_assistant 選定規則（反向掃描）：
      1. 優先：最後一個 has_tool_use=0 且 content 非空白 的 assistant（乾淨的最終回應）
      2. 備選：最後一個 assistant 訊息（即使無文字，至少標出端點）
      3. 都無 assistant：final_assistant_message_id = NULL（極罕見，例如只有 user 沒回應）
    """
    members = wip.members
    message_count = len(members)
    assistant_count = sum(1 for m in members if m["row"]["role"] == "assistant")
    tool_round_count = sum(
        1 for m in members
        if m["row"]["role"] == "assistant" and m["row"]["has_tool_use"]
    )

    # 反向掃描找 final_assistant
    clean_final_idx: int | None = None
    fallback_assistant_idx: int | None = None
    for i in range(len(members) - 1, -1, -1):
        m = members[i]
        if m["row"]["role"] != "assistant":
            continue
        if fallback_assistant_idx is None:
            fallback_assistant_idx = i
        if not m["row"]["has_tool_use"]:
            content = m["row"]["content"]
            if content and content.strip():
                clean_final_idx = i
                break  # 找到乾淨 final 即停止

    final_assistant_message_id: int | None = None
    has_final_text = False
    final_text_preview: str | None = None
    ended_at: str | None = None

    chosen_idx = clean_final_idx if clean_final_idx is not None else fallback_assistant_idx
    if chosen_idx is not None:
        members[chosen_idx]["role_in_exchange"] = "assistant_final"
        chosen_row = members[chosen_idx]["row"]
        final_assistant_message_id = chosen_row["id"]
        ended_at = chosen_row["message_time"]
        content = chosen_row["content"]
        if content and content.strip():
            has_final_text = True
            final_text_preview = content[:500]

    # 聚合 tool_names（聯集，排序輸出穩定 JSON）
    tool_names_set: set[str] = set()
    for m in members:
        try:
            names = json.loads(m["row"]["tool_names"] or "[]")
            if isinstance(names, list):
                tool_names_set.update(str(n) for n in names if n)
        except (json.JSONDecodeError, TypeError):
            pass
    tool_names_list = sorted(tool_names_set)
    has_tool_use = bool(tool_names_set)

    # tool_executions 統計
    member_ids = [m["row"]["id"] for m in members]
    tool_use_count, has_error = _fetch_tool_stats(conn, member_ids)

    # user_text_preview
    user_row = members[0]["row"]
    user_content = user_row["content"]
    user_text_preview = user_content[:300] if user_content else ""

    return {
        "user_message_id": wip.user_message_id,
        "final_assistant_message_id": final_assistant_message_id,
        "message_count": message_count,
        "assistant_message_count": assistant_count,
        "tool_round_count": tool_round_count,
        "tool_use_count": tool_use_count,
        "has_tool_use": 1 if has_tool_use else 0,
        "has_error": 1 if has_error else 0,
        "has_final_text": 1 if has_final_text else 0,
        "tool_names": json.dumps(tool_names_list, ensure_ascii=False),
        "user_text_preview": user_text_preview,
        "final_text_preview": final_text_preview,
        "status": status,
        "started_at": wip.started_at,  # 可能為 None；INSERT 時 COALESCE
        "ended_at": ended_at,
        "members": members,
    }


# ============================================================
# DB 寫入
# ============================================================

def _insert_exchange(
    conn: sqlite3.Connection,
    session_id: int,
    branch_id: int,
    exchange_idx: int,
    ex: dict[str, Any],
) -> int:
    """寫入單一 exchange，回傳 id"""
    cur = conn.execute(
        """INSERT INTO exchanges
           (session_id, branch_id, exchange_idx,
            user_message_id, final_assistant_message_id,
            message_count, assistant_message_count, tool_round_count, tool_use_count,
            has_tool_use, has_error, has_final_text, tool_names,
            user_text_preview, final_text_preview,
            status, started_at, ended_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                   COALESCE(?, datetime('now')), ?)""",
        (
            session_id, branch_id, exchange_idx,
            ex["user_message_id"], ex["final_assistant_message_id"],
            ex["message_count"], ex["assistant_message_count"],
            ex["tool_round_count"], ex["tool_use_count"],
            ex["has_tool_use"], ex["has_error"], ex["has_final_text"],
            ex["tool_names"],
            ex["user_text_preview"], ex["final_text_preview"],
            ex["status"], ex["started_at"], ex["ended_at"],
        ),
    )
    return cur.lastrowid


def _insert_exchange_members(
    conn: sqlite3.Connection, exchange_id: int, members: list[dict[str, Any]]
) -> None:
    """寫入 exchange_messages 橋接列（含 role_in_exchange 語意角色）"""
    rows = [
        (exchange_id, m["row"]["id"], seq, m["role_in_exchange"])
        for seq, m in enumerate(members)
    ]
    conn.executemany(
        """INSERT INTO exchange_messages
           (exchange_id, message_id, seq, role_in_exchange)
           VALUES (?, ?, ?, ?)""",
        rows,
    )


# ============================================================
# Public API
# ============================================================

def rebuild_exchanges_for_session(
    conn: sqlite3.Connection, session_id: int
) -> dict[str, int]:
    """
    對該 session 全部 branch 重建 exchanges（in-transaction，由 caller commit）。

    流程：
      1. 取得該 session 所有 branches
      2. 逐 branch DELETE 舊 exchanges（CASCADE 連帶清 exchange_messages）
      3. 逐 branch 重建新 exchanges + exchange_messages

    回傳統計：{'branches': N, 'exchanges': M, 'members': K}
    """
    branches = conn.execute(
        "SELECT id, is_active FROM branches WHERE session_id = ? ORDER BY branch_idx",
        (session_id,),
    ).fetchall()

    stats = {"branches": 0, "exchanges": 0, "members": 0}

    for b in branches:
        branch_id = b["id"]
        is_active = bool(b["is_active"])

        # 清舊（CASCADE）
        conn.execute("DELETE FROM exchanges WHERE branch_id = ?", (branch_id,))

        # 建新
        ex_list = _build_exchanges_for_branch(conn, branch_id, is_active)

        for idx, ex in enumerate(ex_list):
            ex_id = _insert_exchange(conn, session_id, branch_id, idx, ex)
            _insert_exchange_members(conn, ex_id, ex["members"])
            stats["members"] += len(ex["members"])
            stats["exchanges"] += 1
        stats["branches"] += 1

    return stats


def rebuild_exchanges_for_session_standalone(
    session_uuid: str,
) -> dict[str, int]:
    """
    自開連線版本（給 stop_hook / backfill 用）。
    自管 transaction：成功 commit、失敗 rollback。
    若 session 不存在（uuid 找不到）回傳空統計。
    """
    with get_connection() as conn:
        row = conn.execute(
            "SELECT id FROM sessions WHERE uuid = ?", (session_uuid,)
        ).fetchone()
        if row is None:
            logger.warning("rebuild_exchanges：找不到 session uuid=%s", session_uuid)
            return {"branches": 0, "exchanges": 0, "members": 0}

        session_id = row["id"]
        stats = rebuild_exchanges_for_session(conn, session_id)
        conn.commit()
        return stats
