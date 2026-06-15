"""tests/model_api_tools/test_local_scanner.py — 本機掃描 + catalog 回填（2 個）。

對應 plan Step 5 驗收：mock ollama tags/show → is_local_installed/deep 欄位；本機獨有列補建。
fetch 注入免網路。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from model_api_tools.core.local_scanner import (  # noqa: E402
    LocalModel,
    enrich_catalog,
    scan_ollama_installed,
)
from model_api_tools.core.store import ModelRecord  # noqa: E402

_FIX = Path(__file__).parent / "fixtures"
_TAGS = json.loads((_FIX / "ollama_tags_sample.json").read_text(encoding="utf-8"))
_SHOW = json.loads((_FIX / "ollama_show_sample.json").read_text(encoding="utf-8"))


def test_scan_ollama_deep_fields():
    """注入 tags/show → match_name 去 :tag、context_length 取自 show、usage 取自 capabilities。"""
    locals_ = scan_ollama_installed(
        host="http://x", fetch_tags=lambda: _TAGS, fetch_show=lambda _name: _SHOW
    )
    assert len(locals_) == 2
    coder = next(m for m in locals_ if m.display_name == "qwen3-coder:30b")
    assert coder.match_name == "qwen3-coder"            # 去 :30b → library slug
    assert coder.context_length == 262144               # show.model_info qwen3moe.context_length
    assert coder.usage == "completion, tools"           # show.capabilities join
    assert coder.model_format == "gguf" and coder.param_size == "30.5B"
    assert coder.file_size_bytes == 18556700761


def test_enrich_catalog_match_and_new():
    """命中者升 deep+installed 並補缺欄；本機獨有者補新 deep 列。"""
    catalog = [ModelRecord(source="ollama", name="qwen3-coder", detail_level="shallow")]
    locals_ = [
        LocalModel(source="ollama", match_name="qwen3-coder",
                   display_name="qwen3-coder:30b", context_length=262144,
                   file_size_bytes=999, quantization="Q4_K_M"),
        LocalModel(source="ollama", match_name="qwen3.6",
                   display_name="qwen3.6:35b-a3b-nvfp4-custom", model_format="safetensors"),
    ]
    out = enrich_catalog(catalog, locals_)
    assert len(out) == 2

    hit = next(r for r in out if r.name == "qwen3-coder")
    assert hit.is_local_installed == 1 and hit.detail_level == "deep"
    assert hit.context_length == 262144 and hit.quantization == "Q4_K_M"   # 補缺欄

    new = next(r for r in out if r.name == "qwen3.6:35b-a3b-nvfp4-custom")  # 本機獨有 → 用完整名
    assert new.is_local_installed == 1 and new.detail_level == "deep"
    assert new.source == "ollama" and new.model_format == "safetensors"
