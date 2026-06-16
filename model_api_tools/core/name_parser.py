"""name_parser.py — 從 model name 萃取規格欄位（param_size / quantization）。

職責（SRP）：純函數，零 I/O、零 SQL。把「name 字串本身編碼的規格」解析成欄位，
作為 shallow record 的**免費增強**——HF /api/models list endpoint 不回 config 細節，
但 repo name 慣例上常含 size/quant（如 Qwen3.6-35B-A3B-MLX-4bit）。

權威層級：本機 deep enrich（實測）> name 解析 > NULL。
故 backfill_specs 只填仍為 NULL 的欄位，不覆蓋 deep 既有值（DIP：靠 duck typing，
不耦合 ModelRecord 型別）。
"""

from __future__ import annotations

import re
from typing import Iterable, Protocol, TypeVar

# MoE：總參數B + active 參數（"35B-A3B" / "235B-A22B" / "26B-A4B"）。
# A 後必須接數字，避免把 "5B-Adapter" 誤判為 MoE。
_MOE_RE = re.compile(r"(\d+\.?\d*)[Bb]-?[Aa](\d+\.?\d*)[Bb]?")
# effective dense（gemma "E4B" / "e2b"）：E 前綴 + 數字 + B。
_EFF_RE = re.compile(r"\b[Ee](\d+\.?\d*)[Bb]\b")
# dense：第一個帶單位的參數量（B=billion / M=million）。
# 前置 look-behind 排除緊貼字母/數字者，避免吃版本號（Olmo-3.1 的 3.1、InternVL2_5 的 2_5）。
_DENSE_RE = re.compile(r"(?<![A-Za-z\d])(\d+\.?\d*)([BbMm])\b")

# 量化精度標記，優先序：bit > gguf Q* > fp 量化 > 半精度。
# 方法修飾（QAT/AWQ/DWQ/OptiQ）不視為精度，不單獨成值（誠實留 NULL）。
_QUANT_RES = (
    re.compile(r"\b(\d+)bit\b", re.I),                  # mlx：4bit/8bit/6bit...
    re.compile(r"\b(I?Q\d+(?:_[A-Za-z0-9]+)*)\b"),      # gguf：Q4_K_M / IQ4_XS / Q8
    re.compile(r"\b((?:mx|nv)fp\d+)\b", re.I),          # fp 量化：MXFP4 / nvfp4
    re.compile(r"\b(bf16|fp16|fp8)\b", re.I),           # 半精度
)

class _SpecRecord(Protocol):
    """backfill 對象的結構契約（duck typing）：只需這三個欄位。"""

    name: str
    param_size: str | None
    quantization: str | None


_T = TypeVar("_T", bound=_SpecRecord)


def parse_param_size(name: str) -> str | None:
    """name → 參數量字串；MoE 'NB-ANB'、effective 'ENB'、dense 'NB'|'NM'；無則 None。"""
    base = name.split("/")[-1]                  # 去 author 前綴（author 段不含 size token）
    m = _MOE_RE.search(base)
    if m:
        return f"{m.group(1)}B-A{m.group(2)}B"
    e = _EFF_RE.search(base)
    if e:
        return f"E{e.group(1)}B"
    d = _DENSE_RE.search(base)
    if d:
        return f"{d.group(1)}{d.group(2).upper()}"
    return None


def parse_quantization(name: str) -> str | None:
    """name → 量化精度標記（bit/Q*/fp*/half）；多個依優先序取第一；無則 None。"""
    base = name.split("/")[-1]
    for i, rx in enumerate(_QUANT_RES):
        m = rx.search(base)
        if m:
            tok = m.group(1)
            return f"{tok}bit" if i == 0 else tok   # 第一條只捕數字，補回 'bit'
    return None


def backfill_specs(records: Iterable[_T]) -> list[_T]:
    """對每筆 record，用 name 解析補仍為 NULL 的 param_size / quantization。

    只填 None（deep 實測值優先保留）；就地修改並回傳同一批（duck typing：
    record 需具備 .name / .param_size / .quantization 屬性）。
    """
    out = list(records)
    for r in out:
        if getattr(r, "param_size", None) is None:
            r.param_size = parse_param_size(r.name)
        if getattr(r, "quantization", None) is None:
            r.quantization = parse_quantization(r.name)
    return out


__all__ = ["parse_param_size", "parse_quantization", "backfill_specs"]
