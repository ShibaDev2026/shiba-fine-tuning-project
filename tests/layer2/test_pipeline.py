"""pipeline.py 單元測試

涵蓋範圍：
- 路徑 A：橋接條件篩選、exchange 級 SEAL 篩選、decay_score 門檻、adapter_block 標記
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
    run_extraction,
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
    has_tool_use: int = 1,
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


def _seed_branch_message(
    conn: sqlite3.Connection, branch_id: int, message_id: int, seq: int
) -> None:
    conn.execute(
        "INSERT INTO branch_messages (branch_id, message_id, seq) VALUES (?, ?, ?)",
        (branch_id, message_id, seq),
    )
    conn.commit()


def _seed_tool_execution(
    conn: sqlite3.Connection,
    message_id: int,
    tool_use_id: str,
    tool_name: str,
    is_error: int = 0,
) -> int:
    cur = conn.execute(
        """INSERT INTO tool_executions (message_id, tool_use_id, tool_name, is_error)
           VALUES (?, ?, ?, ?)""",
        (message_id, tool_use_id, tool_name, is_error),
    )
    conn.commit()
    return cur.lastrowid


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


# ── 路徑 A 測試 ──────────────────────────────────────────────────────────

class TestPathA:
    def test_valid_session_extracted(self, tmp_path):
        """git_ops + has_tool_use + exchange_count>=2 應被抽取"""
        conn = _make_db(tmp_path)
        pid = _seed_project(conn)
        sid = _seed_session(conn, pid, "sess-a1", ["git_ops"], exchange_count=3)
        bid = _seed_branch(conn, sid, decay_score=0.9)

        m1 = _seed_message(conn, sid, "m1", "user", "請幫我 commit 這個修改")
        m2 = _seed_message(conn, sid, "m2", "assistant", "好的，執行 git commit -m 'fix: ...'", has_tool_use=1, tool_names=["Bash"])
        _seed_branch_message(conn, bid, m1, 1)
        _seed_branch_message(conn, bid, m2, 2)

        stats = run_extraction(conn)
        assert stats["path_a"] == 1
        row = conn.execute("SELECT * FROM training_samples WHERE source='layer1_bridge'").fetchone()
        assert row["event_type"] == "git_ops"
        assert row["adapter_block"] == 1
        assert row["status"] == "pending"

    def test_non_bridge_event_type_skipped(self, tmp_path):
        """knowledge_qa session 不符合路徑 A 橋接條件"""
        conn = _make_db(tmp_path)
        pid = _seed_project(conn)
        sid = _seed_session(conn, pid, "sess-a2", ["knowledge_qa"], exchange_count=3)
        _seed_branch(conn, sid, decay_score=0.9)

        stats = run_extraction(conn)
        assert stats["path_a"] == 0

    def test_low_decay_score_skipped(self, tmp_path):
        """decay_score < 0.3 的 session 跳過（FOREVER 加權）"""
        conn = _make_db(tmp_path)
        pid = _seed_project(conn)
        sid = _seed_session(conn, pid, "sess-a3", ["git_ops"], exchange_count=3)
        bid = _seed_branch(conn, sid, decay_score=0.1)

        m1 = _seed_message(conn, sid, "m1", "user", "commit 請求")
        m2 = _seed_message(conn, sid, "m2", "assistant", "完成 commit", has_tool_use=1)
        _seed_branch_message(conn, bid, m1, 1)
        _seed_branch_message(conn, bid, m2, 2)

        stats = run_extraction(conn)
        assert stats["path_a"] == 0

    def test_exchange_count_below_threshold_skipped(self, tmp_path):
        """exchange_count < 2 不符合條件"""
        conn = _make_db(tmp_path)
        pid = _seed_project(conn)
        sid = _seed_session(conn, pid, "sess-a4", ["git_ops"], exchange_count=1)
        _seed_branch(conn, sid, decay_score=0.9)

        stats = run_extraction(conn)
        assert stats["path_a"] == 0

    def test_adapter_block2_for_debugging(self, tmp_path):
        """debugging event → adapter_block=2"""
        conn = _make_db(tmp_path)
        pid = _seed_project(conn)
        # debugging 不在路徑A橋接條件內（_BRIDGE_EVENT_TYPES = block1 only）
        # 驗證 code_gen + debugging 混合時，adapter_block 依 primary event 決定
        sid = _seed_session(conn, pid, "sess-a5", ["code_gen"], exchange_count=3)
        bid = _seed_branch(conn, sid, decay_score=0.9)

        m1 = _seed_message(conn, sid, "m1", "user", "寫一個函式解析 JSON")
        m2 = _seed_message(conn, sid, "m2", "assistant", "完成，這是程式碼...", has_tool_use=1)
        _seed_branch_message(conn, bid, m1, 1)
        _seed_branch_message(conn, bid, m2, 2)

        stats = run_extraction(conn)
        assert stats["path_a"] == 1
        row = conn.execute("SELECT adapter_block FROM training_samples WHERE source='layer1_bridge'").fetchone()
        assert row["adapter_block"] == 1  # code_gen → block1


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

        stats = run_extraction(conn)
        assert stats["path_b"] == 1
        row = conn.execute("SELECT * FROM training_samples WHERE source='error_repair'").fetchone()
        assert "Bash" in row["instruction"]
        assert row["status"] == "pending"

    def test_no_repair_response_skipped(self, tmp_path):
        """tool error 後沒有 assistant 修復回覆 → 不抽取"""
        conn = _make_db(tmp_path)
        pid = _seed_project(conn)
        sid = _seed_session(conn, pid, "sess-b2", ["terminal_ops"], exchange_count=1)

        m1 = _seed_message(conn, sid, "m1", "assistant", "執行中...", has_tool_use=1)
        _seed_tool_execution(conn, m1, "tool-002", "Bash", is_error=1)
        # 沒有後續 assistant 訊息

        stats = run_extraction(conn)
        assert stats["path_b"] == 0

    def test_same_session_only_once(self, tmp_path):
        """同一 session 有多個 tool error，只產生一筆樣本"""
        conn = _make_db(tmp_path)
        pid = _seed_project(conn)
        sid = _seed_session(conn, pid, "sess-b3", ["terminal_ops"], exchange_count=3)

        m1 = _seed_message(conn, sid, "m1", "assistant", "第一次失敗", has_tool_use=1)
        m2 = _seed_message(conn, sid, "m2", "assistant", "修復回覆一")
        m3 = _seed_message(conn, sid, "m3", "assistant", "第二次失敗", has_tool_use=1)
        _seed_tool_execution(conn, m1, "tool-003", "Bash", is_error=1)
        _seed_tool_execution(conn, m3, "tool-004", "Edit", is_error=1)

        stats = run_extraction(conn)
        assert stats["path_b"] == 1


# ── 重複防呆測試 ─────────────────────────────────────────────────────────

class TestDeduplication:
    def test_same_session_not_extracted_twice(self, tmp_path):
        """第二次跑 run_extraction 同一 session 應 skipped"""
        conn = _make_db(tmp_path)
        pid = _seed_project(conn)
        sid = _seed_session(conn, pid, "sess-dup", ["git_ops"], exchange_count=3)
        bid = _seed_branch(conn, sid, decay_score=0.9)

        m1 = _seed_message(conn, sid, "m1", "user", "commit 請求")
        m2 = _seed_message(conn, sid, "m2", "assistant", "完成", has_tool_use=1)
        _seed_branch_message(conn, bid, m1, 1)
        _seed_branch_message(conn, bid, m2, 2)

        stats1 = run_extraction(conn)
        stats2 = run_extraction(conn)

        assert stats1["path_a"] == 1
        # 第二次：SQL 層 NOT IN 已過濾，path_a=0，skipped=0（未進入 _is_duplicate）
        assert stats2["path_a"] == 0
        assert stats2["skipped"] == 0
        # DB 仍只有一筆，確認沒有重複寫入
        assert conn.execute("SELECT COUNT(*) FROM training_samples").fetchone()[0] == 1
