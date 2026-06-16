"""tests/model_api_tools/test_ollama_scraper.py — ollama.com/library HTML 解析（1 個）。

對應 plan Step 3 驗收：fixture 解析 → 欄位對映 + model_format='gguf' / download_metric='cumulative'。
（日期過濾於 Step 3 已 inline 驗證、非該步驗收欄項目，依「不自行擴充」原則不另立測試。）
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from model_api_tools.core.ollama_scraper import parse_library_html  # noqa: E402

_HTML = (Path(__file__).parent / "fixtures" / "ollama_library_sample.html").read_text(
    encoding="utf-8"
)


def test_parse_fields_and_stamps():
    """3 張 card 解析；首列欄位對映 + 固定 stamp（gguf / cumulative / shallow）。"""
    recs = parse_library_html(_HTML)
    assert len(recs) == 3
    by_name = {r.name: r for r in recs}

    llama = by_name["llama3.1"]
    assert llama.description.startswith("Llama 3.1 is a new state-of-the-art")
    assert llama.usage == "tools"
    assert llama.param_size == "8b/70b/405b"
    assert llama.download_count == 115_900_000          # "115.9M" → int
    assert llama.updated_at == "2024-11-30 22:34:00"    # title 精確時戳（10:34 PM → 22:34）
    # 固定 stamp（Ollama 全列一致）
    assert llama.model_format == "gguf"
    assert llama.download_metric == "cumulative"
    assert llama.detail_level == "shallow"

    # 多能力以 ", " join
    assert by_name["deepseek-r1"].usage == "tools, thinking"
