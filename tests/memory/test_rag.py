# tests/memory/test_rag.py
"""rag.py 單元測試"""

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "layer_1_memory"))

from lib.db import get_connection, init_db
from lib.rag import build_rag_output, get_rag_context, retrieve_relevant_sessions


def _seed_db(tmp_db: Path) -> None:
    """植入測試資料（直接操作 tmp_db，不使用 patch）"""
    import sqlite3 as _sqlite3
    schema_path = Path(__file__).parent.parent.parent / "layer_1_memory" / "db" / "schema.sql"
    conn = _sqlite3.connect(str(tmp_db))
    conn.row_factory = _sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    conn.executescript(schema_path.read_text(encoding="utf-8"))
    conn.execute("""
        INSERT INTO sessions_fts
            (session_uuid, project_path, event_types, content_summary, files_list, ended_at)
        VALUES
            ('uuid-001', '/project', 'debugging',
             'address_parser 里鄰剝離修正 fix error', '', '2026-04-14T10:30:00Z'),
            ('uuid-002', '/project', 'architecture',
             'geocoder 查詢改用 COALESCE 優化', '', '2026-04-13T09:45:00Z')
    """)
    conn.commit()
    conn.close()


def test_retrieve_relevant_sessions_finds_match(tmp_path):
    """FTS5 查詢應找到相關 session"""
    db_file = tmp_path / "test.db"
    _seed_db(db_file)
    with patch("lib.db.get_db_path", return_value=db_file):
        results = retrieve_relevant_sessions("address_parser", top_n=3)

    assert len(results) >= 1
    assert any("address" in str(r) for r in results)


def test_retrieve_empty_query_returns_empty(tmp_path):
    """空 query 應回傳空 list（不做 FTS 查詢）"""
    db_file = tmp_path / "test.db"
    _seed_db(db_file)
    with patch("lib.db.get_db_path", return_value=db_file):
        results = retrieve_relevant_sessions("", top_n=3)

    assert results == []


def test_build_rag_output_returns_string():
    """build_rag_output 應回傳非空字串"""
    sessions = [
        {
            "session_uuid": "uuid-001",
            "project_path": "/project",
            "event_types": ["debugging"],
            "ended_at": "2026-04-14T10:30:00Z",
            "snippet": "address_parser 里鄰剝離修正",
        }
    ]
    output = build_rag_output(sessions)
    assert isinstance(output, str)
    assert len(output) > 0


def test_build_rag_output_empty_sessions():
    """空 sessions 應回傳空字串"""
    assert build_rag_output([]) == ""


# ── source classification contract（producer↔caller 對齊） ──

def test_get_rag_context_returns_fts5_source_when_vector_unavailable(tmp_path):
    """vector 不可用時 fallback FTS5，source 必須回 'fts5'"""
    db_file = tmp_path / "test.db"
    _seed_db(db_file)
    with patch("lib.db.get_db_path", return_value=db_file), \
         patch("lib.rag.get_embedding", return_value=None):
        context, source = get_rag_context("address_parser", top_n=3)

    assert context  # 有內容
    assert source == "fts5"


def test_get_rag_context_returns_none_source_when_no_hits(tmp_path):
    """空 DB + vector 不可用，回傳 ('', 'none')"""
    db_file = tmp_path / "empty.db"
    # 建空 schema 不灌資料
    import sqlite3 as _sqlite3
    schema_path = Path(__file__).parent.parent.parent / "layer_1_memory" / "db" / "schema.sql"
    conn = _sqlite3.connect(str(db_file))
    conn.executescript(schema_path.read_text(encoding="utf-8"))
    conn.commit()
    conn.close()

    with patch("lib.db.get_db_path", return_value=db_file), \
         patch("lib.rag.get_embedding", return_value=None):
        context, source = get_rag_context("不存在的關鍵字", top_n=3)

    assert context == ""
    assert source == "none"
