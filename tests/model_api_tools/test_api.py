"""tests/model_api_tools/test_api.py — FastAPI adapter（搜尋 + 觸發）。

fastapi 為 adapter 專屬依賴，無 fastapi 環境以 importorskip 跳過（不拖累 core 測試）。
全程 in-memory DB 注入 get_conn override，不碰 shared shiba-brain.db。
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from model_api_tools.api import app, get_conn  # noqa: E402
from model_api_tools.core.store import (  # noqa: E402
    ModelRecord,
    init_search_model_list,
    write_batch,
)


def _seed_conn() -> sqlite3.Connection:
    """in-memory DB 套 schema + 種三筆（含 mlx），供搜尋過濾驗證。"""
    # TestClient 在 threadpool 跑同步端點，in-memory conn 需放寬 thread 檢查
    c = sqlite3.connect(":memory:", check_same_thread=False)
    init_search_model_list(c)
    recs = [
        ModelRecord(source="huggingface", name="mlx-community/qwen3-30b", author="mlx-community",
                    detail_level="shallow", model_format="mlx", download_metric="30d",
                    download_count=500),
        ModelRecord(source="huggingface", name="lmstudio-community/glm-4-gguf", author="lmstudio-community",
                    detail_level="shallow", model_format="gguf", download_metric="30d",
                    download_count=300),
        ModelRecord(source="ollama", name="qwen3-coder", author=None,
                    detail_level="shallow", model_format="gguf", download_metric="cumulative",
                    download_count=999),
    ]
    write_batch(c, recs, "run-1", "2026-06-16 00:00:00")
    return c


def _client(conn: sqlite3.Connection) -> TestClient:
    """注入共用 in-memory conn（override 版不關閉，避免多次請求後 conn 被關）。"""
    app.dependency_overrides[get_conn] = lambda: conn
    return TestClient(app)


def test_models_no_filter_returns_all():
    c = _seed_conn()
    client = _client(c)
    try:
        r = client.get("/models")
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 3 and body["count"] == 3
        assert len(body["items"]) == 3
    finally:
        app.dependency_overrides.clear()


def test_models_filter_by_format_mlx():
    c = _seed_conn()
    client = _client(c)
    try:
        r = client.get("/models", params={"format": "mlx"})
        body = r.json()
        assert body["total"] == 1
        assert body["items"][0]["model_format"] == "mlx"
        assert body["items"][0]["author"] == "mlx-community"
    finally:
        app.dependency_overrides.clear()


def test_models_keyword_and_pagination():
    c = _seed_conn()
    client = _client(c)
    try:
        # keyword 對 name 模糊比對
        r = client.get("/models", params={"q": "qwen3"})
        body = r.json()
        assert body["total"] == 2  # mlx-community/qwen3-30b + ollama/qwen3-coder
        # 分頁：limit=1 → 本頁 1 筆、total 仍 2
        r2 = client.get("/models", params={"q": "qwen3", "limit": 1, "offset": 1})
        body2 = r2.json()
        assert body2["total"] == 2 and body2["count"] == 1 and body2["offset"] == 1
    finally:
        app.dependency_overrides.clear()
