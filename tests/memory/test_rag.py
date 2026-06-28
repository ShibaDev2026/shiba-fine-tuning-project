# tests/memory/test_rag.py
"""rag.py 單元測試"""

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "layer_1_memory"))

from lib.db import get_connection, init_db
from lib.rag import (
    build_rag_output,
    get_rag_context,
    get_rag_context_with_hits,
    is_low_signal_query,
    is_short_query,
    is_system_meta_query,
    retrieve_relevant_sessions,
)


def _patch_db_path(db_file: Path):
    """把 get_connection 的 DB 指向 tmp。

    get_connection → shiba_db.open_connection 直接讀 module global CONFIG.paths.db；
    CONFIG.paths 為 frozen dataclass（不可 setattr/delattr），故整顆替換 module 的 CONFIG。
    """
    from types import SimpleNamespace
    fake = SimpleNamespace(paths=SimpleNamespace(db=db_file))
    return patch("shiba_db.CONFIG", fake)


def _seed_embeddings(tmp_db: Path, rows: list[tuple[str, str]]) -> None:
    """植入 exchange_embeddings（rows=[(instruction, commands), ...]）。

    embedding 欄 NOT NULL 但 is_low_signal_query 不讀它，塞 '[]' 佔位即可。
    """
    import sqlite3 as _sqlite3
    schema_path = Path(__file__).parent.parent.parent / "layer_1_memory" / "db" / "schema.sql"
    conn = _sqlite3.connect(str(tmp_db))
    conn.row_factory = _sqlite3.Row
    conn.executescript(schema_path.read_text(encoding="utf-8"))
    for i, (instr, cmd) in enumerate(rows):
        conn.execute(
            "INSERT INTO exchange_embeddings (session_uuid, instruction, commands, embedding)"
            " VALUES (?, ?, ?, ?)",
            (f"u{i}", instr, cmd, "[]"),
        )
    conn.commit()
    conn.close()


def test_is_low_signal_query_true_for_high_divergence(tmp_path):
    """同一 instruction 衍生 >= 3 種 commands → 判定同意詞 → True"""
    db_file = tmp_path / "test.db"
    _seed_embeddings(db_file, [("好", "git add"), ("好", "git commit"), ("好", "pytest -q")])
    with _patch_db_path(db_file):
        assert is_low_signal_query("好") is True


def test_is_low_signal_query_false_for_low_divergence_or_novel(tmp_path):
    """發散不足（< 3）或從未出現的新詞 → False（照常召回，累積後再學）"""
    db_file = tmp_path / "test.db"
    _seed_embeddings(db_file, [("跑測試", "pytest"), ("跑測試", "pytest -q")])  # 僅 2 種
    with _patch_db_path(db_file):
        assert is_low_signal_query("跑測試") is False   # 低發散
        assert is_low_signal_query("從沒見過的詞") is False  # 新詞/不存在


def test_is_system_meta_query_true_for_harness_prompts():
    """harness / remember 外掛產生的系統 prompt（非 Shiba 查詢）→ True，呼叫端跳過召回。

    fixture 取自 recall_logs/20260621.txt 實際污染源（前綴穩定、來自不可控外掛/harness）。
    """
    assert is_system_meta_query(
        "You are summarizing a Claude Code session for a daily memory log.\n\nRead the conversation"
    ) is True
    assert is_system_meta_query(
        "Apply maximum non-destructive compression. Rules:\n- Keep ALL facts"
    ) is True
    assert is_system_meta_query(
        "<task-notification>\n<task-id>bivu1ki8f</task-id>"
    ) is True
    assert is_system_meta_query(
        "This session is being continued from a previous conversation that ran out of context."
    ) is True


def test_is_system_meta_query_false_for_real_user_queries():
    """Shiba 的真實查詢（即使短或像 meta）→ False，照常召回。"""
    assert is_system_meta_query("recall_logs 目錄放在哪裡？") is False
    assert is_system_meta_query("Option 1") is False
    assert is_system_meta_query("開PR push and merge main") is False
    assert is_system_meta_query("") is False


def test_is_short_query_gates_short_control_words():
    """過短控制詞/決策碎片（<=15 字）→ True，呼叫端跳過召回+log+通知。

    這些是 is_low_signal_query 的 divergence 啟發式抓不到的一致性控制詞
    （fixture 取自 recall_logs/20260621.txt 實際洩漏）。零 DB、純長度。
    """
    for q in ("merge", "A", "finish", "是", "好", "Option 1", "先2後1+D4", "  收尾  "):
        assert is_short_query(q) is True


def test_is_short_query_false_for_real_instructions():
    """>15 字的真實指令 → False，照常召回。"""
    assert is_short_query("請幫我重構整個資料流節點並更新對應索引路徑") is False
    assert is_short_query("檢查 recall_logs 今日是否有需改善之處") is False


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
    with _patch_db_path(db_file):
        results = retrieve_relevant_sessions("address_parser", top_n=3)

    assert len(results) >= 1
    assert any("address" in str(r) for r in results)


def test_retrieve_empty_query_returns_empty(tmp_path):
    """空 query 應回傳空 list（不做 FTS 查詢）"""
    db_file = tmp_path / "test.db"
    _seed_db(db_file)
    with _patch_db_path(db_file):
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
    with _patch_db_path(db_file), \
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

    with _patch_db_path(db_file), \
         patch("lib.rag.get_embedding", return_value=None):
        context, source = get_rag_context("不存在的關鍵字", top_n=3)

    assert context == ""
    assert source == "none"


def test_get_rag_context_with_hits_returns_triple(tmp_path):
    """擴充版多回 hits：fts5 命中時回 (ctx, 'fts5', 非空 hits)，含結構化欄位"""
    db_file = tmp_path / "test.db"
    _seed_db(db_file)
    with _patch_db_path(db_file), \
         patch("lib.rag.get_embedding", return_value=None):
        context, source, hits = get_rag_context_with_hits("address_parser", top_n=3)

    assert context and source == "fts5"
    assert isinstance(hits, list) and len(hits) > 0


def test_get_rag_context_with_hits_empty_when_no_hits(tmp_path):
    """無命中：hits 為空 list，與 ('', 'none') 一致"""
    db_file = tmp_path / "empty.db"
    import sqlite3 as _sqlite3
    schema_path = Path(__file__).parent.parent.parent / "layer_1_memory" / "db" / "schema.sql"
    conn = _sqlite3.connect(str(db_file))
    conn.executescript(schema_path.read_text(encoding="utf-8"))
    conn.commit()
    conn.close()

    with _patch_db_path(db_file), \
         patch("lib.rag.get_embedding", return_value=None):
        context, source, hits = get_rag_context_with_hits("不存在的關鍵字", top_n=3)

    assert context == "" and source == "none" and hits == []


def test_build_context_block_includes_answer():
    """hit 帶 answer 時，單 exchange 區塊輸出「答案：」行。"""
    from lib.rag import _build_context_block
    hit = {
        "instruction": "D4 灌水是什麼",
        "commands": "",
        "answer": "branch membership 錯亂導致重複切片",
        "exchange_id": None,
    }
    block, expanded = _build_context_block(hit, window_k=0, preview_chars=200)
    assert expanded is False
    assert "答案：branch membership 錯亂導致重複切片" in block
    assert "指令：" not in block  # 純問答無指令


# ── _build_exchange_context answer 渲染（Fix A TDD）──

def test_build_exchange_context_renders_answer():
    """純問答 exchange（空 commands + 有 answer）→ 含「答案：」行、不含空「指令：」行。"""
    from lib.rag import _build_exchange_context
    exchanges = [
        {
            "instruction": "D4 灌水是什麼",
            "commands": "",
            "answer": "branch membership 錯亂導致重複切片",
        }
    ]
    result = _build_exchange_context(exchanges)
    assert "答案：branch membership 錯亂導致重複切片" in result
    # 純問答不得輸出空指令行
    assert "指令：\n" not in result
    assert "指令：" not in result


def test_build_exchange_context_truncates_long_answer():
    """answer 超過 200 字 → 顯示截斷至約 200 字（_ANSWER_PREVIEW_CHARS）。"""
    from lib.rag import _build_exchange_context, _ANSWER_PREVIEW_CHARS
    long_answer = "A" * 500  # 遠超 200 字
    exchanges = [
        {
            "instruction": "說明一下",
            "commands": "",
            "answer": long_answer,
        }
    ]
    result = _build_exchange_context(exchanges)
    # 截斷後長度應 <= 200 + 一點 ellipsis overhead（允許 ≤ 210 以防 format 前後加字）
    answer_start = result.find("答案：")
    assert answer_start != -1
    answer_portion = result[answer_start + len("答案："):]
    # 截到下一行或結尾
    answer_line = answer_portion.split("\n")[0]
    assert len(answer_line) <= _ANSWER_PREVIEW_CHARS + 3  # +3 for potential "..."


# ── retrieve_for_eval answer 渲染（Fix B TDD）──

def test_retrieve_for_eval_includes_answer(monkeypatch):
    """vector_search 回帶 answer 的 hit → retrieved_contexts[0] 含「答案：」行。"""
    from lib import rag

    fake_hit = {
        "session_uuid": "uuid-test",
        "instruction": "什麼是 HyDE",
        "commands": "",
        "answer": "Hypothetical Document Embeddings 透過假設文件增強召回",
        "score": 0.85,
        "exchange_id": None,
    }
    monkeypatch.setattr(rag, "_vector_search", lambda *a, **kw: [fake_hit])

    result = rag.retrieve_for_eval("什麼是 HyDE")
    assert result["source"] == "vector"
    ctx = result["retrieved_contexts"][0]
    assert "答案：Hypothetical Document Embeddings" in ctx
    # 純問答不得有空指令行
    assert "指令：\n" not in ctx
    assert "指令：" not in ctx
