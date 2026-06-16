"""tests/model_api_tools/test_hf_scraper.py — HF /api/models 解析 + 日期停損（2 個）。

對應 plan Step 4 驗收：fixture 解析 → model_format=lane、download_metric='30d'；
                       lastModified 降序停損正確。fetch 注入免網路。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from model_api_tools.core.hf_scraper import parse_hf_models, scrape_hf  # noqa: E402

_MODELS = json.loads(
    (Path(__file__).parent / "fixtures" / "hf_models_sample.json").read_text(encoding="utf-8")
)


def test_parse_format_by_lane():
    """format 由 lane 標記（非 tags）：Model-A 帶 safetensors tag 仍標 mlx。"""
    recs = parse_hf_models(_MODELS, "mlx")
    assert len(recs) == 4
    a = recs[0]
    assert a.name == "mlx-community/Model-A-mlx-4bit"
    assert a.author == "mlx-community"          # list 回應 author=null → 由 id 前綴推導
    assert a.usage == "text-generation"         # pipeline_tag
    assert a.download_count == 11967
    assert a.updated_at == "2026-06-15 13:45:27"
    assert a.model_format == "mlx"              # ← lane 權威（tags 含 safetensors 不影響）
    assert a.download_metric == "30d"
    assert a.source == "huggingface" and a.detail_level == "shallow"


def test_date_stoploss_desc_order():
    """降序停損：A(2026-06)+B(2025-08) 入列；C(2025-03)<start 停該 lane，D 不觸及。"""
    page = (_MODELS, None)   # 單頁、無 next_url
    recs = scrape_hf(start="2025-06-01", end="2026-06-15",
                     whitelist=("mlx-community",), formats=("mlx",),
                     fetch=lambda _url: page)
    assert [r.name for r in recs] == [
        "mlx-community/Model-A-mlx-4bit",
        "mlx-community/Model-B-mlx-8bit",
    ]
    assert all(r.model_format == "mlx" for r in recs)
