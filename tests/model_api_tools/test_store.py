"""tests/model_api_tools/test_store.py — store 持久層 roundtrip + view 最新列（3 個）。

對應 plan Step 2 驗收：roundtrip 短＋長各一；append 後 v_search_model_latest 取最新列正確。
全程 in-memory DB，不碰 shared shiba-brain.db。
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from model_api_tools.core.store import (  # noqa: E402
    ModelRecord,
    get_latest,
    get_local_detail,
    init_search_model_list,
    list_by_run,
    write_batch,
)


def _conn() -> sqlite3.Connection:
    """in-memory DB + 套 schema（冪等）。"""
    c = sqlite3.connect(":memory:")
    init_search_model_list(c)
    return c


def test_roundtrip_short():
    """單筆 shallow record 寫入 → get_latest 讀回，欄位一致。"""
    c = _conn()
    rec = ModelRecord(source="ollama", name="qwen3-coder", detail_level="shallow",
                      model_format="gguf", download_metric="cumulative",
                      download_count=123, usage="tools")
    assert write_batch(c, [rec], "run-1", "2026-06-15 00:00:00") == 1
    rows = get_latest(c, source="ollama")
    assert len(rows) == 1
    r = rows[0]
    assert r["name"] == "qwen3-coder" and r["model_format"] == "gguf"
    assert r["download_metric"] == "cumulative" and r["download_count"] == 123
    assert r["scrape_run_id"] == "run-1" and r["detail_level"] == "shallow"


def test_roundtrip_long_deep_detail():
    """deep record（帶 local_raw_metadata）→ 主表 + model_local_detail 子表，JSON 解析回 dict。"""
    c = _conn()
    recs = [
        ModelRecord(source="ollama", name="a", detail_level="shallow",
                    download_metric="cumulative"),
        ModelRecord(source="huggingface", name="mlx-community/b", detail_level="deep",
                    download_metric="30d", model_format="mlx", context_length=4096,
                    is_local_installed=1,
                    local_raw_metadata='{"ctx": 4096, "q": "Q4_K_M"}'),
    ]
    assert write_batch(c, recs, "run-2", "2026-06-15 00:00:00") == 2
    deep = next(r for r in list_by_run(c, "run-2") if r["detail_level"] == "deep")
    detail = get_local_detail(c, deep["id"])
    assert detail is not None
    assert detail["raw_metadata"] == {"ctx": 4096, "q": "Q4_K_M"}   # 子表 JSON 解析回 dict


def test_append_view_latest():
    """同 (source,name) 跨兩次 run append → view 只取較新 scraped_at 那列。"""
    c = _conn()
    write_batch(c, [ModelRecord(source="ollama", name="x", detail_level="shallow",
                                download_count=10, download_metric="cumulative")],
                "run-old", "2026-06-01 00:00:00")
    write_batch(c, [ModelRecord(source="ollama", name="x", detail_level="shallow",
                                download_count=99, download_metric="cumulative")],
                "run-new", "2026-06-15 00:00:00")
    assert c.execute("SELECT COUNT(*) FROM search_model_list").fetchone()[0] == 2  # append-only
    rows = get_latest(c, source="ollama")
    assert len(rows) == 1 and rows[0]["download_count"] == 99
    assert rows[0]["scrape_run_id"] == "run-new"
