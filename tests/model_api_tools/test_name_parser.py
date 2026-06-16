"""test_name_parser.py — name 規格解析 + backfill 權威層級驗證。"""

from dataclasses import dataclass

import pytest

from model_api_tools.core.name_parser import (
    backfill_specs,
    parse_param_size,
    parse_quantization,
)


# (name, 期望 param_size, 期望 quantization)：涵蓋 MoE / effective / dense /
# million / 版本號干擾 / 多量化標記 / 無 size 等代表分支。
_CASES = [
    ("lmstudio-community/Qwen3.6-35B-A3B-MLX-4bit", "35B-A3B", "4bit"),   # MoE + bit
    ("lmstudio-community/gemma-4-E4B-it-GGUF", "E4B", None),              # effective，GGUF 無顯式量化
    ("mlx-community/gemma-4-12B-it-8bit", "12B", "8bit"),                 # dense + bit
    ("mlx-community/Qwen3-30B-A3B-Instruct-2507-6bit-DWQ-lr8e-8", "30B-A3B", "6bit"),  # 後綴干擾
    ("lmstudio-community/Olmo-3.1-32B-Instruct-GGUF", "32B", None),       # 版本號 3.1 不誤抓
    ("mlx-community/Falcon-H1-Tiny-90M-Base-4bit", "90M", "4bit"),        # million
    ("mlx-community/gpt-oss-120b-MXFP4-Q8", "120B", "Q8"),                # Q 優先於 fp
    ("mlx-community/parler-tts-mini", None, None),                        # 無 size 無量化
    ("lmstudio-community/Qwen3-VL-235B-A22B-Instruct-GGUF", "235B-A22B", None),  # MoE 大 active
    ("mlx-community/Mistral-Small-3.2-24B-Instruct-2506-bf16", "24B", "bf16"),   # 半精度
]


@pytest.mark.parametrize("name,exp_param,exp_quant", _CASES)
def test_parse_name_specs(name, exp_param, exp_quant):
    """各家族 name 樣式 → 正確 param_size / quantization。"""
    assert parse_param_size(name) == exp_param
    assert parse_quantization(name) == exp_quant


@dataclass
class _Rec:
    """測試替身：模擬 ModelRecord 的相關欄位（duck typing）。"""

    name: str
    param_size: str | None = None
    quantization: str | None = None


def test_backfill_only_fills_null():
    """backfill 只補 NULL 欄位，deep 既有實測值不被 name 解析覆蓋。"""
    deep = _Rec(name="x/Qwen3.6-35B-A3B-MLX-8bit", param_size="35.2B", quantization="Q8_0")
    shallow = _Rec(name="x/gemma-4-12B-it-4bit")  # 兩欄皆 NULL → 由 name 補

    backfill_specs([deep, shallow])

    assert deep.param_size == "35.2B"        # deep 實測保留
    assert deep.quantization == "Q8_0"       # deep 實測保留
    assert shallow.param_size == "12B"       # name 補
    assert shallow.quantization == "4bit"    # name 補
