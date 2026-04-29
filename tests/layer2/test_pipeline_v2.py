"""
test_pipeline_v2.py — _extract_path_a_v2 單元測試

涵蓋範圍：
- block1（git_ops）：從 exchange_messages assistant_tool 取工具指令
- block2（debugging）：從 final_assistant_message_id 取純文字
- 過濾：has_error=1 / has_final_text=0 / decay_score<0.3 / exchange_count<2
- _resolve_user_text：content 存在 vs raw_content fallback（zlib）
- NOT IN 去重：已有 layer1_bridge_v2 記錄的 session 跳過
"""

import json
import sqlite3
import sys
import zlib
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from layer_2_chamber.backend.extraction.pipeline import (
    _extract_path_a_v2,
    _resolve_user_text,
)

LAYER1_SCHEMA = Path(__file__).parent.parent.parent / "layer_1_memory" / "db" / "schema.sql"
LAYER2_SCHEMA = (
    Path(__file__).parent.parent.parent
    / "layer_2_chamber" / "backend" / "db" / "schema_layer2.sql"
)


# ── 共用 DB 建立 ──────────────────────────────────────────────────────────

def _make_db(tmp_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(tmp_path / "test.db"))
    conn.row_factory = sqlite3.Row
    conn.executescript(LAYER1_SCHEMA.read_text())
    conn.executescript(LAYER2_SCHEMA.read_text())
    conn.commit()
    return conn


def _seed_session(conn, uuid: str, event_types: list[str]) -> tuple[int, int]:
    """建立 project + session + is_active branch（decay_score=0.9），回傳 (session_id, branch_id)"""
    pid = conn.execute(
        "INSERT INTO projects (name, path, hash) VALUES ('t', '/t', 'h')"
    ).lastrowid
    sid = conn.execute(
        "INSERT INTO sessions (project_id, uuid, exchange_count, event_types, tool_counts) "
        "VALUES (?, ?, 3, ?, '{}')",
        (pid, uuid, json.dumps(event_types)),
    ).lastrowid
    bid = conn.execute(
        "INSERT INTO branches (session_id, branch_idx, is_active, decay_score) VALUES (?, 0, 1, 0.9)",
        (sid,),
    ).lastrowid
    conn.commit()
    return sid, bid


def _seed_msg(conn, sid: int, role: str, content: str, has_tool_use: int = 0,
              tool_names: list | None = None, raw_content: bytes | None = None,
              is_compressed: int = 0) -> int:
    uid = f"msg-{conn.execute('SELECT COUNT(*) FROM messages').fetchone()[0]+1}"
    mid = conn.execute(
        "INSERT INTO messages (session_id, uuid, parent_uuid, role, content, has_tool_use, tool_names, raw_content, is_compressed) "
        "VALUES (?, ?, NULL, ?, ?, ?, ?, ?, ?)",
        (sid, uid, role, content, has_tool_use, json.dumps(tool_names or []), raw_content, is_compressed),
    ).lastrowid
    conn.commit()
    return mid


def _seed_exchange(
    conn, sid: int, bid: int, user_mid: int, final_mid: int | None = None,
    has_tool_use: int = 0, has_error: int = 0, has_final_text: int = 1,
    tool_names: list | None = None, idx: int = 0,
) -> int:
    eid = conn.execute(
        "INSERT INTO exchanges "
        "(session_id, branch_id, exchange_idx, user_message_id, final_assistant_message_id, "
        "has_tool_use, has_error, has_final_text, tool_names, status, started_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'completed', '2026-01-01T00:00:00')",
        (sid, bid, idx, user_mid, final_mid, has_tool_use, has_error, has_final_text,
         json.dumps(tool_names or [])),
    ).lastrowid
    conn.commit()
    return eid


def _seed_ex_msg(conn, eid: int, mid: int, seq: int, role_in_exchange: str) -> None:
    conn.execute(
        "INSERT INTO exchange_messages (exchange_id, message_id, seq, role_in_exchange) "
        "VALUES (?, ?, ?, ?)",
        (eid, mid, seq, role_in_exchange),
    )
    conn.commit()


def _seed_tool_exec(conn, mid: int, tool_name: str, cmd_json: str) -> None:
    uid = f"tu-{conn.execute('SELECT COUNT(*) FROM tool_executions').fetchone()[0]+1}"
    conn.execute(
        "INSERT INTO tool_executions (message_id, tool_use_id, tool_name, input_cmd, is_error) "
        "VALUES (?, ?, ?, ?, 0)",
        (mid, uid, tool_name, cmd_json),
    )
    conn.commit()


# ── 測試 ─────────────────────────────────────────────────────────────────

class TestExtractPathAV2:
    def test_block1_git_ops_extracts_tool_commands(self, tmp_path):
        """git_ops exchange → block1 樣本，output 含 Bash 指令"""
        conn = _make_db(tmp_path)
        sid, bid = _seed_session(conn, "s-block1", ["git_ops"])

        user_mid = _seed_msg(conn, sid, "user", "幫我 commit 這次修改")
        asst_mid = _seed_msg(conn, sid, "assistant", "", has_tool_use=1, tool_names=["Bash"])
        final_mid = _seed_msg(conn, sid, "assistant", "已完成 commit")

        eid = _seed_exchange(conn, sid, bid, user_mid, final_mid,
                             has_tool_use=1, has_final_text=1, tool_names=["Bash"], idx=0)
        _seed_ex_msg(conn, eid, user_mid, 0, "user_open")
        _seed_ex_msg(conn, eid, asst_mid, 1, "assistant_tool")
        _seed_ex_msg(conn, eid, final_mid, 2, "assistant_final")
        _seed_tool_exec(conn, asst_mid, "Bash", json.dumps({"command": "git commit -m 'fix'"}))

        # 第二個 exchange（滿足 count >= 2）
        user_mid2 = _seed_msg(conn, sid, "user", "確認一下 status")
        final_mid2 = _seed_msg(conn, sid, "assistant", "已確認，乾淨")
        eid2 = _seed_exchange(conn, sid, bid, user_mid2, final_mid2,
                              has_final_text=1, idx=1)
        _seed_ex_msg(conn, eid2, user_mid2, 0, "user_open")
        _seed_ex_msg(conn, eid2, final_mid2, 1, "assistant_final")

        samples = _extract_path_a_v2(conn)
        assert len(samples) == 1
        s = samples[0]
        assert s.source == "layer1_bridge_v2"
        assert s.event_type == "git_ops"
        assert s.adapter_block == 1
        assert "git commit" in s.instruction or "git commit" in s.output

    def test_block2_debugging_extracts_final_text(self, tmp_path):
        """debugging exchange → block2 樣本，output 為文字回覆"""
        conn = _make_db(tmp_path)
        sid, bid = _seed_session(conn, "s-block2", ["debugging"])

        user_mid = _seed_msg(conn, sid, "user", "為什麼會有 KeyError？")
        final_mid = _seed_msg(conn, sid, "assistant", "因為 dict 在 None 時不存在這個 key")

        for i in range(2):
            um = _seed_msg(conn, sid, "user", f"問題 {i}")
            fm = _seed_msg(conn, sid, "assistant", f"回覆 {i}")
            eid = _seed_exchange(conn, sid, bid, um, fm, has_final_text=1, idx=i+1)
            _seed_ex_msg(conn, eid, um, 0, "user_open")
            _seed_ex_msg(conn, eid, fm, 1, "assistant_final")

        eid0 = _seed_exchange(conn, sid, bid, user_mid, final_mid, has_final_text=1, idx=0)
        _seed_ex_msg(conn, eid0, user_mid, 0, "user_open")
        _seed_ex_msg(conn, eid0, final_mid, 1, "assistant_final")

        samples = _extract_path_a_v2(conn)
        assert len(samples) == 1
        s = samples[0]
        assert s.adapter_block == 2
        assert s.event_type == "debugging"

    def test_has_error_exchange_filtered(self, tmp_path):
        """has_error=1 的 exchange 被 SQL 過濾，不產生樣本"""
        conn = _make_db(tmp_path)
        sid, bid = _seed_session(conn, "s-err", ["git_ops"])

        for i in range(2):
            um = _seed_msg(conn, sid, "user", f"指令 {i}")
            fm = _seed_msg(conn, sid, "assistant", f"回覆 {i}")
            eid = _seed_exchange(conn, sid, bid, um, fm,
                                 has_error=1, has_final_text=1, idx=i)
            _seed_ex_msg(conn, eid, um, 0, "user_open")
            _seed_ex_msg(conn, eid, fm, 1, "assistant_final")

        samples = _extract_path_a_v2(conn)
        assert samples == []

    def test_low_decay_score_filtered(self, tmp_path):
        """decay_score < 0.3 的 branch session 不抽取"""
        conn = _make_db(tmp_path)
        pid = conn.execute(
            "INSERT INTO projects (name, path, hash) VALUES ('t', '/t', 'h')"
        ).lastrowid
        sid = conn.execute(
            "INSERT INTO sessions (project_id, uuid, exchange_count, event_types, tool_counts) "
            "VALUES (?, 's-low', 3, ?, '{}')",
            (pid, json.dumps(["git_ops"])),
        ).lastrowid
        bid = conn.execute(
            "INSERT INTO branches (session_id, branch_idx, is_active, decay_score) VALUES (?, 0, 1, 0.1)",
            (sid,),
        ).lastrowid
        conn.commit()

        for i in range(2):
            um = _seed_msg(conn, sid, "user", f"請求 {i}")
            fm = _seed_msg(conn, sid, "assistant", f"回覆 {i}")
            eid = _seed_exchange(conn, sid, bid, um, fm, has_final_text=1, idx=i)
            _seed_ex_msg(conn, eid, um, 0, "user_open")
            _seed_ex_msg(conn, eid, fm, 1, "assistant_final")

        samples = _extract_path_a_v2(conn)
        assert samples == []

    def test_exchange_count_less_than_2_skipped(self, tmp_path):
        """只有 1 個 exchange 的 session 跳過（等價 v1 exchange_count >= 2）"""
        conn = _make_db(tmp_path)
        sid, bid = _seed_session(conn, "s-one", ["git_ops"])

        um = _seed_msg(conn, sid, "user", "單一指令")
        fm = _seed_msg(conn, sid, "assistant", "回覆")
        eid = _seed_exchange(conn, sid, bid, um, fm, has_final_text=1, idx=0)
        _seed_ex_msg(conn, eid, um, 0, "user_open")
        _seed_ex_msg(conn, eid, fm, 1, "assistant_final")

        samples = _extract_path_a_v2(conn)
        assert samples == []

    def test_not_in_deduplication(self, tmp_path):
        """session 已有 layer1_bridge_v2 記錄時，SQL NOT IN 過濾，不重複抽取"""
        conn = _make_db(tmp_path)
        sid, bid = _seed_session(conn, "s-dup", ["git_ops"])

        for i in range(2):
            um = _seed_msg(conn, sid, "user", f"請求 {i}")
            fm = _seed_msg(conn, sid, "assistant", f"回覆 {i}")
            eid = _seed_exchange(conn, sid, bid, um, fm, has_final_text=1, idx=i)
            _seed_ex_msg(conn, eid, um, 0, "user_open")
            _seed_ex_msg(conn, eid, fm, 1, "assistant_final")

        # 先植入一筆 v2 記錄（模擬已抽過）
        conn.execute(
            "INSERT INTO training_samples "
            "(source, session_id, event_type, instruction, input, output, adapter_block, status, created_at) "
            "VALUES ('layer1_bridge_v2', 's-dup', 'git_ops', 'x', '', 'y', 1, 'raw', '2026-01-01T00:00:00')"
        )
        conn.commit()

        samples = _extract_path_a_v2(conn)
        assert samples == []


class TestResolveUserText:
    def test_content_present_returns_it(self, tmp_path):
        """content 有值時直接回傳"""
        conn = sqlite3.connect(str(tmp_path / "t.db"))
        conn.row_factory = sqlite3.Row
        # 用 mock row
        row = conn.execute("SELECT 'hello' AS content, NULL AS raw_content, 0 AS is_compressed").fetchone()
        assert _resolve_user_text(row) == "hello"
        conn.close()

    def test_content_empty_fallback_raw_content(self, tmp_path):
        """content 空時 fallback 解 raw_content（zlib 壓縮）"""
        conn = sqlite3.connect(str(tmp_path / "t.db"))
        conn.row_factory = sqlite3.Row
        compressed = zlib.compress("zlib 解壓的文字".encode("utf-8"))
        row = conn.execute(
            "SELECT '' AS content, ? AS raw_content, 1 AS is_compressed",
            (compressed,),
        ).fetchone()
        assert _resolve_user_text(row) == "zlib 解壓的文字"
        conn.close()

    def test_none_row_returns_none(self):
        assert _resolve_user_text(None) is None
