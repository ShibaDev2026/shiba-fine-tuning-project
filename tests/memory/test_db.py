# tests/memory/test_db.py
"""db.py 單元測試"""

import sqlite3
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# 將 layer_1_memory 加入 import 路徑
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "layer_1_memory"))

from lib.db import (
    compress_text,
    decompress_text,
    fetch_message_raw_content,
    fetch_tool_execution_output,
    get_connection,
    init_db,
    insert_message,
    insert_tool_execution,
    upsert_project,
    upsert_session,
)


def test_init_db_creates_tables(tmp_path):
    """init_db 應建立 sessions、messages、sessions_fts 等核心資料表"""
    db_file = tmp_path / "test.db"
    # 暫時替換 DB 路徑
    with patch("lib.db.get_db_path", return_value=db_file):
        init_db()
        conn = sqlite3.connect(str(db_file))
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table','view')"
            ).fetchall()
        }
        conn.close()

    assert "sessions" in tables
    assert "messages" in tables
    assert "sessions_fts" in tables


def test_get_connection_returns_sqlite_connection(tmp_path):
    """get_connection 應回傳可用的 SQLite 連線"""
    db_file = tmp_path / "test.db"
    with patch("lib.db.get_db_path", return_value=db_file):
        with get_connection() as conn:
            assert isinstance(conn, sqlite3.Connection)
            # WAL 模式已開啟
            mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
            assert mode == "wal"


def test_init_db_idempotent(tmp_path):
    """init_db 重複呼叫不應拋出錯誤（CREATE TABLE IF NOT EXISTS 安全）"""
    db_file = tmp_path / "test.db"
    with patch("lib.db.get_db_path", return_value=db_file):
        init_db()
        init_db()  # 第二次不應失敗


def test_compress_decompress_roundtrip_short_text():
    """< 1024 bytes 不壓縮，decompress 應能還原原字串"""
    text = "短字串測試"  # UTF-8 編碼後遠小於 1024 bytes
    blob, flag = compress_text(text)
    assert flag == 0
    assert blob == text  # 短字串直接以 TEXT 存放
    assert decompress_text(blob, flag) == text


def test_compress_decompress_roundtrip_long_text():
    """> 1024 bytes 應壓為 BLOB，decompress 能完全還原"""
    text = "測試" * 500  # 約 3000 bytes (UTF-8)
    blob, flag = compress_text(text)
    assert flag == 1
    assert isinstance(blob, bytes)
    assert decompress_text(blob, flag) == text


def test_decompress_text_handles_none():
    """None 輸入須回傳 None，不可拋錯"""
    assert decompress_text(None, 0) is None
    assert decompress_text(None, 1) is None


def test_fetch_message_raw_content_roundtrip(tmp_path):
    """insert_message 寫入長 raw_content → fetch 應還原為原始字串"""
    db_file = tmp_path / "test.db"
    with patch("lib.db.get_db_path", return_value=db_file):
        init_db()
        long_text = "raw payload " * 200  # 超過 1024 bytes 必走壓縮路徑
        with get_connection() as conn:
            project_id = upsert_project(conn, "demo", "/tmp/demo", "hash1")
            session_id = upsert_session(conn, project_id, "uuid-session-1")
            message_id = insert_message(
                conn,
                session_id=session_id,
                uuid="msg-uuid-1",
                parent_uuid=None,
                role="user",
                content="short content",
                raw_content=long_text,
                input_tokens=0,
                output_tokens=0,
                cache_creation_input_tokens=0,
                cache_read_input_tokens=0,
                char_count=len(long_text),
                byte_count=len(long_text.encode("utf-8")),
                encoding="utf-8",
                has_tool_use=False,
                tool_names=[],
            )
            assert fetch_message_raw_content(conn, message_id) == long_text


def test_transaction_rollback_on_error(tmp_path):
    """get_connection 異常時應 rollback，不留下部分寫入"""
    db_file = tmp_path / "test.db"
    with patch("lib.db.get_db_path", return_value=db_file):
        init_db()
        try:
            with get_connection() as conn:
                upsert_project(conn, "rollback-test", "/tmp/rb", "hash-rb")
                raise RuntimeError("模擬中途崩潰")
        except RuntimeError:
            pass

        # rollback 後 project 不應存在
        with get_connection() as conn:
            row = conn.execute(
                "SELECT id FROM projects WHERE hash = ?", ("hash-rb",)
            ).fetchone()
            assert row is None, "rollback 失敗：部分寫入殘留"


def test_fetch_tool_execution_output_roundtrip(tmp_path):
    """insert_tool_execution 寫入長 output_log → fetch 應還原為原始字串"""
    db_file = tmp_path / "test.db"
    with patch("lib.db.get_db_path", return_value=db_file):
        init_db()
        long_output = "line\n" * 500  # > 1024 bytes 走壓縮
        with get_connection() as conn:
            project_id = upsert_project(conn, "demo", "/tmp/demo", "hash2")
            session_id = upsert_session(conn, project_id, "uuid-session-2")
            message_id = insert_message(
                conn,
                session_id=session_id,
                uuid="msg-uuid-2",
                parent_uuid=None,
                role="assistant",
                content="tool call",
                raw_content=None,
                input_tokens=0,
                output_tokens=0,
                cache_creation_input_tokens=0,
                cache_read_input_tokens=0,
                char_count=0,
                byte_count=0,
                encoding="utf-8",
                has_tool_use=True,
                tool_names=["Bash"],
            )
            tool_exec_id = insert_tool_execution(
                conn,
                message_id=message_id,
                tool_use_id="toolu_1",
                tool_name="Bash",
                input_cmd="ls -al",
                output_log=long_output,
                is_error=False,
            )
            assert fetch_tool_execution_output(conn, tool_exec_id) == long_output
