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
    # 不需要真實 DB，FTS5 空結果時回傳空字串
    result = get_rag_context("幫我列出目錄")
    assert isinstance(result, str)  # 不 crash，回傳字串（空或有內容皆可）
