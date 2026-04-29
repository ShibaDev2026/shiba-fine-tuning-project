"""
pipeline.py — Layer 2 訓練樣本抽取管線

路徑 A（layer1_bridge）：
  Layer 1 高品質 session → exchange 級篩選 → training_samples
  條件：event_type ∈ {git_ops, terminal_ops, code_gen}
        + has_tool_use=true + exchange_count >= 2

路徑 B（error_repair）：
  tool_executions.is_error=1 → 找後續修復回合 → training_samples

SEAL 概念：以 exchange 為單位篩選，只取「成功完成」的回合對，跳過中間失敗重試
FOREVER 概念：decay_score 加權，新鮮高分 session 優先，避免反覆抽舊資料
MoE-CL 概念：每筆樣本標記 adapter_block（1 或 2）
"""

import json
import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone

# 共用 Layer 1 的 raw_content 解壓函式（zlib），避免重複實作
from layer_1_memory.lib.db import decompress_text

logger = logging.getLogger(__name__)

# ── adapter_block 分類規則（對應 CLAUDE.md 兩個 LoRA block）────────────
_BLOCK1_EVENT_TYPES = {"git_ops", "terminal_ops", "code_gen"}
_BLOCK2_EVENT_TYPES = {"debugging", "architecture", "knowledge_qa", "fine_tuning_ops"}

# 路徑 A 的 Layer 1 橋接條件（block1 + block2 全收）
_BRIDGE_EVENT_TYPES = _BLOCK1_EVENT_TYPES | _BLOCK2_EVENT_TYPES

# decay_score 門檻：低於此值的 branch 跳過（舊/低品質）
_MIN_DECAY_SCORE = 0.3


@dataclass
class ExtractedSample:
    """單筆待寫入 training_samples 的資料"""
    source: str          # 'layer1_bridge' | 'error_repair'
    session_id: str      # Layer 1 session uuid
    event_type: str
    instruction: str
    input: str
    output: str
    adapter_block: int   # 1 或 2


# ── 公開入口 ─────────────────────────────────────────────────────────────

def run_extraction_v2(conn: sqlite3.Connection) -> dict:
    """
    執行完整抽取流程（路徑 A v2 + 路徑 B），將新樣本寫入 training_samples。
    路徑 A 使用 exchanges 語意層（layer1_bridge_v2），取代舊版 state machine。
    回傳統計：{'path_a': int, 'path_b': int, 'skipped': int}
    """
    stats = {"path_a": 0, "path_b": 0, "skipped": 0}

    path_a_samples = _extract_path_a_v2(conn)
    path_b_samples = _extract_path_b(conn)

    for sample in path_a_samples:
        if _is_duplicate(conn, sample):
            stats["skipped"] += 1
            continue
        _insert_sample(conn, sample)
        stats["path_a"] += 1

    for sample in path_b_samples:
        if _is_duplicate(conn, sample):
            stats["skipped"] += 1
            continue
        _insert_sample(conn, sample)
        stats["path_b"] += 1

    conn.commit()
    logger.info(
        "抽取完成（v2）path_a=%d path_b=%d skipped=%d",
        stats["path_a"], stats["path_b"], stats["skipped"],
    )
    return stats


def run_extraction(conn: sqlite3.Connection) -> dict:
    """
    執行完整抽取流程（路徑 A + B），將新樣本寫入 training_samples。
    回傳統計：{'path_a': int, 'path_b': int, 'skipped': int}
    """
    stats = {"path_a": 0, "path_b": 0, "skipped": 0}

    path_a_samples = _extract_path_a(conn)
    path_b_samples = _extract_path_b(conn)

    for sample in path_a_samples:
        if _is_duplicate(conn, sample):
            stats["skipped"] += 1
            continue
        _insert_sample(conn, sample)
        stats["path_a"] += 1

    for sample in path_b_samples:
        if _is_duplicate(conn, sample):
            stats["skipped"] += 1
            continue
        _insert_sample(conn, sample)
        stats["path_b"] += 1

    conn.commit()
    logger.info(
        "抽取完成 path_a=%d path_b=%d skipped=%d",
        stats["path_a"], stats["path_b"], stats["skipped"],
    )
    return stats


# ── 路徑 A：Layer 1 橋接 ─────────────────────────────────────────────────

def _extract_path_a(conn: sqlite3.Connection) -> list[ExtractedSample]:
    """
    從 Layer 1 抽取高品質 session。
    - 已抽過的 session（training_samples 已有記錄）跳過
    - decay_score < _MIN_DECAY_SCORE 的 branch 跳過（FOREVER 加權）
    - 以 exchange 為單位：只取 assistant 有工具呼叫且後續無 is_error 的回合（SEAL 篩選）
    """
    # 找符合橋接條件的 session，尚未被抽取過
    sql = """
        SELECT s.id, s.uuid, s.exchange_count, s.event_types, s.tool_counts
        FROM sessions s
        WHERE s.exchange_count >= 2
          AND s.uuid NOT IN (
              SELECT session_id FROM training_samples
              WHERE source = 'layer1_bridge' AND session_id IS NOT NULL
          )
    """
    sessions = conn.execute(sql).fetchall()

    samples: list[ExtractedSample] = []
    for sess in sessions:
        event_types = _parse_json_list(sess["event_types"])

        # 只處理橋接目標 event_type
        matched = _BRIDGE_EVENT_TYPES & set(event_types)
        if not matched:
            continue

        # 確認最高品質 branch 的 decay_score（FOREVER）
        branch = _get_best_branch(conn, sess["id"])
        if branch is None or branch["decay_score"] < _MIN_DECAY_SCORE:
            continue

        primary_event = _pick_primary_event(event_types, matched)
        adapter_block = _get_adapter_block(primary_event)

        # block1（git/bash）：output 用實際執行指令；block2：用文字回覆
        use_tool_output = adapter_block == 1
        exchanges = _extract_valid_exchanges(
            conn, sess["id"], branch["id"], use_tool_output=use_tool_output
        )
        if not exchanges:
            continue

        # 整合成單筆 Alpaca 樣本
        sample = _build_alpaca_sample(
            source="layer1_bridge",
            session_uuid=sess["uuid"],
            event_type=primary_event,
            exchanges=exchanges,
            adapter_block=adapter_block,
        )
        if sample:
            samples.append(sample)

    return samples


# ── 路徑 A v2：直接以 Layer 1 exchanges 語意層為單位 ───────────────────────
#
# 與 v1 對照：
#   v1：從 branch_messages JOIN messages 重跑 state machine 切 exchange
#       三個結構性問題（邊界判定脆弱、錯誤標記過粗、語意層重複實作）
#   v2：直接讀 exchanges 表（Layer 1 已預先標記 has_error / has_final_text /
#       status='completed'），不再自行切回合
#
# 樣本形狀維持 session→1 sample 不變，僅改抽法。

# 主 SQL：一次撈所有候選 exchange，後續 group by session
_PATH_A_V2_SQL = """
    SELECT s.id AS session_id, s.uuid AS session_uuid, s.event_types,
           e.id AS exchange_id, e.exchange_idx,
           e.user_message_id, e.final_assistant_message_id,
           e.has_tool_use, e.tool_names AS exchange_tool_names,
           b.id AS branch_id, b.decay_score
    FROM exchanges e
    JOIN branches b ON b.id = e.branch_id AND b.is_active = 1
    JOIN sessions s ON s.id = e.session_id
    WHERE b.decay_score >= ?
      AND e.status = 'completed'
      AND e.has_error = 0
      AND e.has_final_text = 1
      AND s.uuid NOT IN (
          SELECT session_id FROM training_samples
          WHERE source = 'layer1_bridge_v2' AND session_id IS NOT NULL
      )
    ORDER BY s.id, b.decay_score DESC, e.exchange_idx
"""


def _extract_path_a_v2(conn: sqlite3.Connection) -> list[ExtractedSample]:
    """
    路徑 A v2：以 exchanges 表為基礎抽取 layer1_bridge_v2 樣本。

    流程：
    1. SQL 一次撈完所有乾淨 exchange（has_error=0 / has_final_text=1 / status=completed）
    2. group by session_uuid，同 session 取最高 decay_score 的 branch
    3. 套用 event_type 篩選（沿用 v1 的 _BRIDGE_EVENT_TYPES）
    4. block1 取 tool_executions 指令、block2 取 final_assistant 文字
    5. 合併為單筆 Alpaca 樣本，source='layer1_bridge_v2'
    """
    rows = conn.execute(_PATH_A_V2_SQL, (_MIN_DECAY_SCORE,)).fetchall()

    # group by session_uuid，同一 session 只保留最高 decay_score 的 branch
    # （SQL 已 ORDER BY decay_score DESC，第一個遇到的 branch_id 即為最佳）
    by_session: dict[str, dict] = {}
    for r in rows:
        uuid = r["session_uuid"]
        if uuid not in by_session:
            by_session[uuid] = {"branch_id": r["branch_id"], "exchanges": []}
        if r["branch_id"] == by_session[uuid]["branch_id"]:
            by_session[uuid]["exchanges"].append(r)

    samples: list[ExtractedSample] = []
    for session_uuid, data in by_session.items():
        # 跳過 exchange 數 < 2 的 session（保留 v1 的 exchange_count >= 2 等價條件）
        if len(data["exchanges"]) < 2:
            continue

        # event_type 篩選（同 v1）：取第一個 exchange 的 session.event_types 即可
        event_types = _parse_json_list(data["exchanges"][0]["event_types"])
        matched = _BRIDGE_EVENT_TYPES & set(event_types)
        if not matched:
            continue

        primary_event = _pick_primary_event(event_types, matched)
        adapter_block = _get_adapter_block(primary_event)
        use_tool_output = (adapter_block == 1)

        # 將每個 exchange 物質化為 dict（含 user / assistant 文字）
        exchange_dicts: list[dict] = []
        for ex_row in data["exchanges"]:
            ex_dict = _materialize_exchange_v2(conn, ex_row, use_tool_output)
            if ex_dict:
                exchange_dicts.append(ex_dict)

        if not exchange_dicts:
            continue

        sample = _build_alpaca_sample(
            source="layer1_bridge_v2",
            session_uuid=session_uuid,
            event_type=primary_event,
            exchanges=exchange_dicts,
            adapter_block=adapter_block,
        )
        if sample:
            samples.append(sample)

    return samples


def _materialize_exchange_v2(
    conn: sqlite3.Connection,
    ex_row: sqlite3.Row,
    use_tool_output: bool,
) -> dict | None:
    """
    從一個 exchange row 取出 user content 與 output。
    block1（use_tool_output=True）：output 為 exchange 內 assistant_tool 訊息的指令序列
    block2（use_tool_output=False）：output 為 final_assistant_message_id 的純文字
    """
    # user content：由 messages 表讀（exchanges.user_text_preview 會截斷，不可用於訓練）
    user_msg = conn.execute(
        "SELECT content, raw_content, is_compressed FROM messages WHERE id = ?",
        (ex_row["user_message_id"],),
    ).fetchone()
    user_content = _resolve_user_text(user_msg)
    if not user_content:
        return None

    if use_tool_output:
        # block1：取此 exchange 內所有 assistant_tool 訊息 ID，餵 _collect_tool_commands
        msg_ids = [
            r["message_id"]
            for r in conn.execute(
                "SELECT message_id FROM exchange_messages "
                "WHERE exchange_id = ? AND role_in_exchange = 'assistant_tool' "
                "ORDER BY seq",
                (ex_row["exchange_id"],),
            ).fetchall()
        ]
        cmds = _collect_tool_commands(conn, msg_ids)
        if not cmds:
            return None
        return {
            "user": user_content,
            "assistant": cmds,
            "has_tool_use": True,
            "tool_names": _parse_json_list(ex_row["exchange_tool_names"]),
        }

    # block2：直接取 final_assistant_message_id 的 content
    if ex_row["final_assistant_message_id"] is None:
        return None
    final_msg = conn.execute(
        "SELECT content, has_tool_use, tool_names FROM messages WHERE id = ?",
        (ex_row["final_assistant_message_id"],),
    ).fetchone()
    if not final_msg or not (final_msg["content"] or "").strip():
        return None
    return {
        "user": user_content,
        "assistant": final_msg["content"].strip(),
        "has_tool_use": bool(final_msg["has_tool_use"]),
        "tool_names": _parse_json_list(final_msg["tool_names"]),
    }


def _resolve_user_text(user_msg: sqlite3.Row | None) -> str | None:
    """
    取 user 訊息的純文字。content 為空時 fallback 解 raw_content（zlib）。
    回傳 trimmed 字串；無內容時回 None。
    """
    if user_msg is None:
        return None
    content = (user_msg["content"] or "").strip()
    if content:
        return content
    # content 空 → 嘗試 raw_content 解壓
    text = decompress_text(user_msg["raw_content"], user_msg["is_compressed"])
    if not text:
        return None
    text = text.strip()
    return text or None


def _get_best_branch(conn: sqlite3.Connection, session_id: int) -> sqlite3.Row | None:
    """取 session 的最高 decay_score 且 is_active=1 的 branch"""
    return conn.execute(
        """SELECT id, decay_score FROM branches
           WHERE session_id = ? AND is_active = 1
           ORDER BY decay_score DESC LIMIT 1""",
        (session_id,),
    ).fetchone()


def _extract_valid_exchanges(
    conn: sqlite3.Connection, session_id: int, branch_id: int,
    use_tool_output: bool = False,
) -> list[dict]:
    """
    從 branch_messages 取出此 branch 的訊息序列，篩選有效的 user → assistant 配對。

    use_tool_output=True（block1 event type）：
      output 改為 user 訊息之後 Claude 實際執行的 Bash/Edit/Write 指令序列，
      而非 assistant 的文字回覆。這樣訓練對的「因果」更直接：
      因 = 使用者意圖，果 = 實際操作指令。
    """
    rows = conn.execute(
        """SELECT m.id AS msg_id, m.role, m.content, m.has_tool_use, m.tool_names, bm.seq
           FROM branch_messages bm
           JOIN messages m ON m.id = bm.message_id
           WHERE bm.branch_id = ?
           ORDER BY bm.seq""",
        (branch_id,),
    ).fetchall()

    error_tool_ids = _get_error_tool_ids(conn, session_id)

    exchanges = []
    i = 0
    while i < len(rows):
        row = rows[i]

        # 找有內容的 user 訊息
        if row["role"] != "user" or not (row["content"] or "").strip():
            i += 1
            continue

        user_content = row["content"].strip()

        # 收集此 user 之後、下一個 user 之前的所有 assistant 訊息
        j = i + 1
        asst_rows = []
        has_error = False
        while j < len(rows):
            r = rows[j]
            if r["role"] == "user":
                break
            if r["role"] == "assistant":
                if r["has_tool_use"] and _has_error_tool(r, error_tool_ids):
                    has_error = True
                    break
                asst_rows.append(r)
            j += 1

        if has_error or not asst_rows:
            i = j + 1 if asst_rows else i + 1
            continue

        if use_tool_output:
            # block1：output = 實際執行的 Bash/Edit/Write 指令序列
            cmds = _collect_tool_commands(conn, [r["msg_id"] for r in asst_rows])
            if cmds:
                exchanges.append({
                    "user": user_content,
                    "assistant": cmds,
                    "has_tool_use": True,
                    "tool_names": [],
                })
        else:
            # block2：output = 最後一個有文字內容的 assistant 回覆
            final = next(
                (r for r in reversed(asst_rows) if (r["content"] or "").strip()), None
            )
            if final:
                exchanges.append({
                    "user": user_content,
                    "assistant": final["content"].strip(),
                    "has_tool_use": bool(final["has_tool_use"]),
                    "tool_names": _parse_json_list(final["tool_names"]),
                })

        i = j

    return exchanges


def _collect_tool_commands(conn: sqlite3.Connection, message_ids: list[int]) -> str:
    """
    從指定 message_ids 的 tool_executions 收集成功執行的指令，
    組成多行字串（每行一個指令，含工具名稱前綴）。
    """
    if not message_ids:
        return ""
    placeholders = ",".join("?" * len(message_ids))
    rows = conn.execute(
        f"""SELECT te.tool_name, te.input_cmd
            FROM tool_executions te
            WHERE te.message_id IN ({placeholders})
              AND te.is_error = 0
              AND te.tool_name IN ('Bash', 'Edit', 'Write')
            ORDER BY te.id""",
        message_ids,
    ).fetchall()

    lines = []
    for r in rows:
        try:
            import json as _json
            cmd_data = _json.loads(r["input_cmd"] or "{}")
        except Exception:
            cmd_data = {}

        if r["tool_name"] == "Bash":
            cmd = cmd_data.get("command", "").strip()
            if cmd:
                lines.append(f"$ {cmd}")
        elif r["tool_name"] in ("Edit", "Write"):
            path = cmd_data.get("file_path", cmd_data.get("path", ""))
            if path:
                lines.append(f"# {r['tool_name']}: {path}")

    return "\n".join(lines)


def _get_error_tool_ids(conn: sqlite3.Connection, session_id: int) -> set[str]:
    """取出此 session 所有失敗 tool_use_id（後續無修復者）"""
    rows = conn.execute(
        """SELECT te.tool_use_id
           FROM tool_executions te
           JOIN messages m ON m.id = te.message_id
           WHERE m.session_id = ? AND te.is_error = 1""",
        (session_id,),
    ).fetchall()
    return {r["tool_use_id"] for r in rows}


def _has_error_tool(msg: sqlite3.Row, error_ids: set[str]) -> bool:
    """判斷此訊息是否使用了出錯的工具"""
    if not error_ids:
        return False
    tool_names = _parse_json_list(msg["tool_names"])
    # tool_names 是工具名，error_ids 是 tool_use_id；保守策略：有任何 error 就標記
    return bool(error_ids)


def _build_alpaca_sample(
    source: str,
    session_uuid: str,
    event_type: str,
    exchanges: list[dict],
    adapter_block: int,
) -> ExtractedSample | None:
    """將 exchange 列表組合為單筆 Alpaca 格式樣本"""
    if not exchanges:
        return None

    # instruction：第一個 user 訊息
    instruction = exchanges[0]["user"]

    # input：中間回合的對話（若超過一回合）
    input_parts = []
    for ex in exchanges[1:-1]:
        input_parts.append(f"User: {ex['user']}\nAssistant: {ex['assistant']}")
    input_text = "\n\n".join(input_parts)

    # output：最後一個 assistant 回覆
    output = exchanges[-1]["assistant"]

    if not instruction or not output:
        return None

    return ExtractedSample(
        source=source,
        session_id=session_uuid,
        event_type=event_type,
        instruction=instruction,
        input=input_text,
        output=output,
        adapter_block=adapter_block,
    )


# ── 路徑 B：error-repair ─────────────────────────────────────────────────

def _extract_path_b(conn: sqlite3.Connection) -> list[ExtractedSample]:
    """
    從 tool_executions 找 is_error=1 的失敗工具，
    並配對後續 assistant 修復回覆，組成 error-repair 訓練對。
    """
    # 找尚未被抽取的失敗工具執行
    sql = """
        SELECT te.id, te.tool_name, te.input_cmd, te.tool_use_id,
               m.session_id, m.id AS message_id, s.uuid AS session_uuid,
               s.event_types
        FROM tool_executions te
        JOIN messages m ON m.id = te.message_id
        JOIN sessions s ON s.id = m.session_id
        WHERE te.is_error = 1
          AND s.uuid NOT IN (
              SELECT session_id FROM training_samples WHERE source = 'error_repair'
          )
        LIMIT 200
    """
    error_rows = conn.execute(sql).fetchall()

    samples: list[ExtractedSample] = []
    seen_sessions: set[str] = set()

    for row in error_rows:
        session_uuid = row["session_uuid"]
        if session_uuid in seen_sessions:
            continue

        repair_exchange = _find_repair_exchange(conn, row["message_id"], row["session_id"])
        if not repair_exchange:
            continue

        event_types = _parse_json_list(row["event_types"])
        event_type = _pick_primary_event(event_types, set(event_types)) or "debugging"
        adapter_block = _get_adapter_block(event_type)

        instruction = (
            f"修復以下工具執行錯誤：\n"
            f"工具：{row['tool_name']}\n"
            f"指令：{row['input_cmd'] or '(無)'}\n"
            f"錯誤：{repair_exchange['error_context']}"
        )

        samples.append(ExtractedSample(
            source="error_repair",
            session_id=session_uuid,
            event_type=event_type,
            instruction=instruction,
            input="",
            output=repair_exchange["repair_response"],
            adapter_block=adapter_block,
        ))
        seen_sessions.add(session_uuid)

    return samples


def _find_repair_exchange(
    conn: sqlite3.Connection, error_message_id: int, session_id: int
) -> dict | None:
    """
    在失敗訊息之後找 assistant 的修復回覆。
    取緊接在 error message 後的第一個 assistant 訊息。
    """
    # 取出 session 所有訊息，依 created_at 排序
    rows = conn.execute(
        """SELECT id, role, content, created_at
           FROM messages
           WHERE session_id = ?
           ORDER BY created_at""",
        (session_id,),
    ).fetchall()

    # 找 error_message_id 的位置
    error_idx = next((i for i, r in enumerate(rows) if r["id"] == error_message_id), None)
    if error_idx is None:
        return None

    # 取 error 訊息的 content 作為 error_context
    error_content = (rows[error_idx]["content"] or "").strip()[:500]

    # 找後續第一個非空的 assistant 訊息
    for row in rows[error_idx + 1:]:
        if row["role"] == "assistant" and (row["content"] or "").strip():
            return {
                "error_context": error_content,
                "repair_response": row["content"].strip(),
            }

    return None


# ── 寫入 ─────────────────────────────────────────────────────────────────

def _insert_sample(conn: sqlite3.Connection, sample: ExtractedSample) -> None:
    """寫入 training_samples（status='raw'，等 refiner 處理後升 pending）"""
    conn.execute(
        """INSERT INTO training_samples
           (source, session_id, event_type, instruction, input, output,
            adapter_block, status, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, 'raw', ?)""",
        (
            sample.source,
            sample.session_id,
            sample.event_type,
            sample.instruction,
            sample.input,
            sample.output,
            sample.adapter_block,
            datetime.now(timezone.utc).isoformat(),
        ),
    )


def _is_duplicate(conn: sqlite3.Connection, sample: ExtractedSample) -> bool:
    """同一 session_id + source 已存在則跳過"""
    row = conn.execute(
        "SELECT id FROM training_samples WHERE session_id = ? AND source = ?",
        (sample.session_id, sample.source),
    ).fetchone()
    return row is not None


# ── 輔助函式 ─────────────────────────────────────────────────────────────

def _parse_json_list(value: str | None) -> list[str]:
    """安全解析 JSON array 字串"""
    if not value:
        return []
    try:
        result = json.loads(value)
        return result if isinstance(result, list) else []
    except (json.JSONDecodeError, TypeError):
        return value.split() if value else []


def _get_adapter_block(event_type: str) -> int:
    """依 event_type 決定 adapter block（MoE-CL 分類規則）"""
    if event_type in _BLOCK1_EVENT_TYPES:
        return 1
    if event_type in _BLOCK2_EVENT_TYPES:
        return 2
    return 1  # 預設 block1


def _pick_primary_event(event_types: list[str], matched: set[str]) -> str:
    """從 session 的 event_types 中選出主要 event（matched 優先，取第一個）"""
    for et in event_types:
        if et in matched:
            return et
    return event_types[0] if event_types else "code_gen"
