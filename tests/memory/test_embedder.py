"""tests/memory/test_embedder.py — Embedding 單元測試（3 個）"""

import json
import sqlite3
import pytest

from layer_1_memory.lib.embedder import cosine_similarity, get_embedding


# ── Test 1：cosine_similarity 正確性 ─────────────────────────────────

def test_cosine_similarity_identical():
    """相同向量 → similarity = 1.0"""
    vec = [1.0, 0.0, 0.5]
    assert abs(cosine_similarity(vec, vec) - 1.0) < 1e-6


def test_cosine_similarity_orthogonal():
    """正交向量 → similarity ≈ 0.0"""
    a = [1.0, 0.0]
    b = [0.0, 1.0]
    assert abs(cosine_similarity(a, b)) < 1e-6


# ── Test 2：Ollama 離線時 get_embedding 回傳 None ──────────────────

def test_get_embedding_fallback_when_ollama_down():
    """Ollama 不可用時回傳 None，不 raise exception"""
    result = get_embedding("測試文字", base_url="http://localhost:19999")  # 不存在的 port
    assert result is None


# ── Test 3：向量召回 fallback 到 FTS5 ────────────────────────────────

def test_vector_search_fallback_to_fts5(monkeypatch):
    """Ollama 不可用時，get_rag_context 自動 fallback FTS5，不 crash"""
    monkeypatch.setattr(
        "layer_1_memory.lib.rag.get_embedding",
        lambda *a, **kw: None,
    )

    from layer_1_memory.lib.rag import get_rag_context
    # 不需要真實 DB，FTS5 空結果時回傳 ("", "none")
    context, source = get_rag_context("幫我列出目錄")
    assert isinstance(context, str)  # 不 crash，回傳字串（空或有內容皆可）
    assert source in {"vector", "fts5", "none"}


def test_vector_search_leave_one_out(monkeypatch):
    """LOO 排除 source session：在 top_n 截斷前過濾、支援多 uuid、空池不 fallback。

    用 mock embedding + mock DB rows，使 cosine 排序固定 A>B>C，純驗 exclude 邏輯。
    """
    import json
    import layer_1_memory.lib.rag as rag

    # query 向量 [1,0,0]；三筆 row 設計成 cosine A(1.0) > B(0.8) > C(0.6)，皆 > 0.35 門檻
    monkeypatch.setattr(rag, "get_embedding", lambda *a, **kw: [1.0, 0.0, 0.0])
    rows = [
        {"session_uuid": "A", "instruction": "a", "commands": "x",
         "embedding": json.dumps([1.0, 0.0, 0.0]), "exchange_id": 1},
        {"session_uuid": "B", "instruction": "b", "commands": "y",
         "embedding": json.dumps([0.8, 0.6, 0.0]), "exchange_id": 2},
        {"session_uuid": "C", "instruction": "c", "commands": "z",
         "embedding": json.dumps([0.6, 0.8, 0.0]), "exchange_id": 3},
    ]

    class _FakeCur:
        def fetchall(self):
            return rows

    class _FakeConn:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def execute(self, *a, **kw):
            return _FakeCur()

    monkeypatch.setattr(rag, "get_connection", lambda *a, **kw: _FakeConn())

    def uuids(**kw):
        return [r["session_uuid"] for r in rag._vector_search("q", **kw)]

    # 無排除：top_n=2 取最相關兩筆
    assert uuids(top_n=2) == ["A", "B"]
    # 盲點1：排除最相關的 A 後，top_n=2 仍補到 B、C（exclude 在截斷前，不會少召回）
    assert uuids(top_n=2, exclude_session_uuids={"A"}) == ["B", "C"]
    # 盲點2：多 uuid 全部排除
    assert uuids(top_n=2, exclude_session_uuids={"A", "B"}) == ["C"]
    # 盲點3：全排除→空池，不得 fallback 含回 source
    assert uuids(top_n=2, exclude_session_uuids={"A", "B", "C"}) == []
