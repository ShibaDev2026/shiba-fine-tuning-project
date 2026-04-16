# tests/memory/test_db.py
"""db.py 單元測試"""

import sqlite3
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# 將 layer_1_memory 加入 import 路徑
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "layer_1_memory"))

from lib.db import get_connection, init_db


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
