"""pipeline.py 單元測試（A3 後 v2 only）

涵蓋範圍：
- 路徑 A v2：exchanges 語意層 SEAL 篩選、decay_score 門檻、adapter_block 標記
- 路徑 B：error-repair 抽取、修復回覆配對
- 重複防呆：同一 session 不重複寫入
- 輔助函式：_get_adapter_block、_parse_json_list、_pick_primary_event
"""

import json
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from layer_2_chamber.backend.extraction.pipeline import (
    _get_adapter_block,
    _parse_json_list,
    _pick_primary_event,
    run_extraction_v2,
)

# ── Fixtures ─────────────────────────────────────────────────────────────

LAYER1_SCHEMA = (
    Path(__file__).parent.parent.parent / "layer_1_memory" / "db" / "schema.sql"
)
LAYER2_SCHEMA = (
    Path(__file__).parent.parent.parent
    / "layer_2_chamber" / "backend" / "db" / "schema_layer2.sql"
)


def _make_db(tmp_path: Path) -> sqlite3.Connection:
    """建立含 Layer 1 + Layer 2 schema 的測試 DB"""
    conn = sqlite3.connect(str(tmp_path / "test.db"))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(LAYER1_SCHEMA.read_text())
    conn.executescript(LAYER2_SCHEMA.read_text())
    conn.commit()
    return conn


def _seed_project(conn: sqlite3.Connection) -> int:
    cur = conn.execute(
        "INSERT INTO projects (name, path, hash) VALUES ('test', '/test', 'hash1')"
    )
    conn.commit()
    return cur.lastrowid


def _seed_session(
    conn: sqlite3.Connection,
    project_id: int,
    uuid: str,
    event_types: list[str],
    exchange_count: int = 3,
) -> int:
    cur = conn.execute(
        """INSERT INTO sessions (project_id, uuid, exchange_count, event_types, tool_counts)
           VALUES (?, ?, ?, ?, '{}')""",
        (project_id, uuid, exchange_count, json.dumps(event_types)),
    )
    conn.commit()
    return cur.lastrowid


def _seed_branch(
    conn: sqlite3.Connection, session_id: int, decay_score: float = 0.9
) -> int:
    cur = conn.execute(
        """INSERT INTO branches (session_id, branch_idx, is_active, decay_score)
           VALUES (?, 0, 1, ?)""",
        (session_id, decay_score),
    )
    conn.commit()
    return cur.lastrowid


def _seed_message(
    conn: sqlite3.Connection,
    session_id: int,
    uuid: str,
    role: str,
    content: str,
    has_tool_use: int = 0,
    tool_names: list[str] | None = None,
) -> int:
    cur = conn.execute(
        """INSERT INTO messages
           (session_id, uuid, parent_uuid, role, content, has_tool_use, tool_names)
           VALUES (?, ?, NULL, ?, ?, ?, ?)""",
        (
            session_id, uuid, role, content,
            has_tool_use, json.dumps(tool_names or []),
        ),
    )
    conn.commit()
    return cur.lastrowid


def _seed_tool_execution(
    conn: sqlite3.Connection,
    message_id: int,
    tool_use_id: str,
    tool_name: str,
    is_error: int = 0,
    input_cmd: str | None = None,
) -> int:
    if input_cmd is None:
        input_cmd = json.dumps({"command": "git commit -m 'test'"}) if tool_name == "Bash" else json.dumps({"file_path": "/test/file.py"})
    cur = conn.execute(
        """INSERT INTO tool_executions (message_id, tool_use_id, tool_name, input_cmd, is_error)
           VALUES (?, ?, ?, ?, ?)""",
        (message_id, tool_use_id, tool_name, input_cmd, is_error),
    )
    conn.commit()
    return cur.lastrowid


def _seed_exchange(
    conn: sqlite3.Connection,
    session_id: int,
    branch_id: int,
    exchange_idx: int,
    user_message_id: int,
    final_assistant_message_id: int | None,
    has_tool_use: int = 1,
    has_error: int = 0,
    has_final_text: int = 1,
    status: str = "completed",
    tool_names: list[str] | None = None,
    assistant_tool_msg_ids: list[int] | None = None,
) -> int:
    """建立一筆 exchange + exchange_messages 紀錄（v2 SQL 必需）"""
    cur = conn.execute(
        """INSERT INTO exchanges
           (session_id, branch_id, exchange_idx, user_message_id, final_assistant_message_id,
            has_tool_use, has_error, has_final_text, status, tool_names, started_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))""",
        (
            session_id, branch_id, exchange_idx,
            user_message_id, final_assistant_message_id,
            has_tool_use, has_error, has_final_text, status,
            json.dumps(tool_names or []),
        ),
    )
    exchange_id = cur.lastrowid

    seq = 0
    conn.execute(
        "INSERT INTO exchange_messages (exchange_id, message_id, seq, role_in_exchange) "
        "VALUES (?, ?, ?, 'user_open')",
        (exchange_id, user_message_id, seq),
    )
    seq += 1
    for asst_msg_id in (assistant_tool_msg_ids or []):
        conn.execute(
            "INSERT INTO exchange_messages (exchange_id, message_id, seq, role_in_exchange) "
            "VALUES (?, ?, ?, 'assistant_tool')",
            (exchange_id, asst_msg_id, seq),
        )
        seq += 1
    if final_assistant_message_id is not None:
        conn.execute(
            "INSERT INTO exchange_messages (exchange_id, message_id, seq, role_in_exchange) "
            "VALUES (?, ?, ?, 'assistant_final')",
            (exchange_id, final_assistant_message_id, seq),
        )
    conn.commit()
    return exchange_id


def _seed_block1_session(conn, project_id: int, uuid: str, event_types: list[str], decay_score: float = 0.9):
    """便利 helper：建一個 block1 session（user→assistant_tool→assistant_final）含 2 個 exchange"""
    sid = _seed_session(conn, project_id, uuid, event_types)
    bid = _seed_branch(conn, sid, decay_score=decay_score)
    for idx in range(2):
        u = _seed_message(conn, sid, f"{uuid}-u{idx}", "user", f"user 訊息 {idx}")
        a_tool = _seed_message(conn, sid, f"{uuid}-at{idx}", "assistant", "執行中", has_tool_use=1, tool_names=["Bash"])
        a_final = _seed_message(conn, sid, f"{uuid}-af{idx}", "assistant", f"完成回覆 {idx}")
        _seed_tool_execution(conn, a_tool, f"{uuid}-tool{idx}", "Bash")
        _seed_exchange(
            conn, sid, bid, exchange_idx=idx,
            user_message_id=u,
            final_assistant_message_id=a_final,
            has_tool_use=1, has_error=0, has_final_text=1,
            tool_names=["Bash"],
            assistant_tool_msg_ids=[a_tool],
        )
    return sid, bid


# ── 輔助函式測試 ─────────────────────────────────────────────────────────

class TestGetAdapterBlock:
    def test_block1_event_types(self):
        assert _get_adapter_block("git_ops") == 1
        assert _get_adapter_block("terminal_ops") == 1
        assert _get_adapter_block("code_gen") == 1

    def test_block2_event_types(self):
        assert _get_adapter_block("debugging") == 2
        assert _get_adapter_block("architecture") == 2
        assert _get_adapter_block("knowledge_qa") == 2
        assert _get_adapter_block("fine_tuning_ops") == 2

    def test_unknown_defaults_to_block1(self):
        assert _get_adapter_block("unknown_event") == 1


class TestParseJsonList:
    def test_valid_json_array(self):
        assert _parse_json_list('["git_ops", "code_gen"]') == ["git_ops", "code_gen"]

    def test_none_returns_empty(self):
        assert _parse_json_list(None) == []

    def test_empty_string_returns_empty(self):
        assert _parse_json_list("") == []

    def test_invalid_json_falls_back_to_split(self):
        assert _parse_json_list("git_ops code_gen") == ["git_ops", "code_gen"]


class TestPickPrimaryEvent:
    def test_picks_matched_first(self):
        result = _pick_primary_event(["knowledge_qa", "git_ops"], {"git_ops"})
        assert result == "git_ops"

    def test_falls_back_to_first_event(self):
        result = _pick_primary_event(["terminal_ops", "code_gen"], set())
        assert result == "terminal_ops"

    def test_empty_list_returns_code_gen(self):
        result = _pick_primary_event([], set())
        assert result == "code_gen"


# ── 路徑 A v2 測試 ───────────────────────────────────────────────────────

class TestPathAV2:
    def test_valid_block1_session_extracted(self, tmp_path):
        """git_ops session（2 個乾淨 exchange）→ 抽出 source='layer1_bridge_v2'"""
        conn = _make_db(tmp_path)
        pid = _seed_project(conn)
        _seed_block1_session(conn, pid, "sess-a1", ["git_ops"])

        stats = run_extraction_v2(conn)
        assert stats["path_a"] == 1
        row = conn.execute(
            "SELECT * FROM training_samples WHERE source='layer1_bridge_v2'"
        ).fetchone()
        assert row["event_type"] == "git_ops"
        assert row["adapter_block"] == 1
        assert row["status"] == "raw"

    def test_block2_event_type_extracted(self, tmp_path):
        """A3 spec 對齊：debugging 等 block2 event 也應橋接（v2 全橋）"""
        conn = _make_db(tmp_path)
        pid = _seed_project(conn)
        _seed_block1_session(conn, pid, "sess-a-block2", ["debugging"])

        stats = run_extraction_v2(conn)
        assert stats["path_a"] == 1
        row = conn.execute(
            "SELECT adapter_block, event_type FROM training_samples WHERE source='layer1_bridge_v2'"
        ).fetchone()
        assert row["adapter_block"] == 2
        assert row["event_type"] == "debugging"

    def test_low_decay_score_skipped(self, tmp_path):
        """decay_score < 0.3 的 branch 跳過（FOREVER 加權）"""
        conn = _make_db(tmp_path)
        pid = _seed_project(conn)
        _seed_block1_session(conn, pid, "sess-a3", ["git_ops"], decay_score=0.1)

        stats = run_extraction_v2(conn)
        assert stats["path_a"] == 0

    def test_has_error_exchange_skipped(self, tmp_path):
        """exchanges.has_error=1 應排除（SEAL 篩選）"""
        conn = _make_db(tmp_path)
        pid = _seed_project(conn)
        sid = _seed_session(conn, pid, "sess-a4", ["git_ops"])
        bid = _seed_branch(conn, sid, decay_score=0.9)
        for idx in range(2):
            u = _seed_message(conn, sid, f"u{idx}", "user", f"q{idx}")
            af = _seed_message(conn, sid, f"af{idx}", "assistant", f"a{idx}")
            _seed_exchange(
                conn, sid, bid, exchange_idx=idx,
                user_message_id=u, final_assistant_message_id=af,
                has_error=1,  # 錯誤回合
            )

        stats = run_extraction_v2(conn)
        assert stats["path_a"] == 0


# ── 路徑 B 測試 ──────────────────────────────────────────────────────────

class TestPathB:
    def test_error_repair_pair_extracted(self, tmp_path):
        """tool is_error=1 後有 assistant 修復回覆 → 抽取為 error_repair 樣本"""
        conn = _make_db(tmp_path)
        pid = _seed_project(conn)
        sid = _seed_session(conn, pid, "sess-b1", ["terminal_ops"], exchange_count=2)

        m1 = _seed_message(conn, sid, "m1", "user", "執行 pytest")
        m2 = _seed_message(conn, sid, "m2", "assistant", "執行中...", has_tool_use=1)
        m3 = _seed_message(conn, sid, "m3", "assistant", "發現錯誤，修正方法是...")
        _seed_tool_execution(conn, m2, "tool-001", "Bash", is_error=1)

        stats = run_extraction_v2(conn)
        assert stats["path_b"] == 1
        row = conn.execute("SELECT * FROM training_samples WHERE source='error_repair'").fetchone()
        assert "Bash" in row["instruction"]
        assert row["status"] == "raw"

    def test_no_repair_response_skipped(self, tmp_path):
        """tool error 後沒有 assistant 修復回覆 → 不抽取"""
        conn = _make_db(tmp_path)
        pid = _seed_project(conn)
        sid = _seed_session(conn, pid, "sess-b2", ["terminal_ops"], exchange_count=1)

        m1 = _seed_message(conn, sid, "m1", "assistant", "執行中...", has_tool_use=1)
        _seed_tool_execution(conn, m1, "tool-002", "Bash", is_error=1)

        stats = run_extraction_v2(conn)
        assert stats["path_b"] == 0


# ── 重複防呆測試 ─────────────────────────────────────────────────────────

class TestDeduplication:
    def test_same_session_not_extracted_twice(self, tmp_path):
        """第二次跑 run_extraction_v2 同一 session 應 skipped"""
        conn = _make_db(tmp_path)
        pid = _seed_project(conn)
        _seed_block1_session(conn, pid, "sess-dup", ["git_ops"])

        stats1 = run_extraction_v2(conn)
        stats2 = run_extraction_v2(conn)

        assert stats1["path_a"] == 1
        assert stats2["path_a"] == 0
        assert stats2["skipped"] == 0
        assert conn.execute("SELECT COUNT(*) FROM training_samples").fetchone()[0] == 1
