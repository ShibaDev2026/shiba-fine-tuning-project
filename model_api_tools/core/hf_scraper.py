"""hf_scraper.py — HuggingFace /api/models（白名單 × format lane）→ 淺層 ModelRecord。

職責（SRP）：只負責「HF 官方 org 清單 → 淺層 record」。三階段拆開：
- fetch_models_page：純 I/O（urllib 抓一頁 + 解析 Link 取 next cursor）。
- parse_hf_models：純解析（model dict list → record list，stamp 格式/metric）。
- scrape_hf：協調（每 author × format lane 分頁，依 lastModified 停損 + max_records 上限）。

DIP：只依賴 ModelRecord 契約；fetch 可注入（fetch=...）便於測試免打網路。

API 觀察（2026-06-15 grounding）：
- 端點 /api/models?author=&filter={gguf|mlx}&sort=lastModified&direction=-1
- 分頁：cursor-based，next URL 在 HTTP `Link` header 的 rel="next"。
- 欄位：id=repo（name）；author 在 list 回應為 null → 由 id 前綴推導；
        downloads=近 30 天（→ download_metric='30d'）；pipeline_tag→usage；
        lastModified=ISO（→ updated_at）；tags=原始標籤陣列。
- format **由 lane 決定**（不靠 tags——mlx 模型同時帶 'mlx'+'safetensors' tag）。

固定值：source='huggingface'、detail_level='shallow'、download_metric='30d'。
description / param_size / context_length / file_size_bytes / quantization 淺層皆 NULL
（規格類欄位留給本機 deep 補）。
"""

from __future__ import annotations

import json
import urllib.request
from datetime import date, datetime
from typing import Callable

from .store import ModelRecord

_API_BASE = "https://huggingface.co/api/models"
_UA = "Mozilla/5.0"

# 預設官方策展白名單與格式（皆為可異動參數，runner 可覆寫）
DEFAULT_HF_WHITELIST = ("lmstudio-community", "mlx-community", "ggml-org")
DEFAULT_HF_FORMATS = ("gguf", "mlx")


# ----------------------------------------------------------------
# I/O
# ----------------------------------------------------------------


def build_lane_url(author: str, fmt: str, limit: int = 100) -> str:
    """單一 (author, format) lane 的首頁 URL（lastModified 降序）。"""
    return (
        f"{_API_BASE}?author={author}&filter={fmt}"
        f"&sort=lastModified&direction=-1&limit={limit}"
    )


def fetch_models_page(url: str, timeout: int = 30) -> tuple[list[dict], str | None]:
    """抓一頁 → (models, next_url)；next_url 來自 Link header rel="next"，無則 None。"""
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310（固定官方 API）
        link = resp.headers.get("Link")
        models = json.loads(resp.read().decode("utf-8", "replace"))
    return models, _parse_next_link(link)


def _parse_next_link(link: str | None) -> str | None:
    """解析 Link header：'<url>; rel="next"' → url；無 next 回 None。"""
    if not link:
        return None
    for part in link.split(","):
        seg = part.split(";", 1)
        if len(seg) == 2 and 'rel="next"' in seg[1]:
            return seg[0].strip().strip("<>")
    return None


# ----------------------------------------------------------------
# 純解析
# ----------------------------------------------------------------


def parse_hf_models(models: list[dict], fmt: str) -> list[ModelRecord]:
    """model dict list → ModelRecord list；format 由傳入 lane 決定（非 tags）。"""
    records: list[ModelRecord] = []
    for m in models:
        mid = m.get("id") or m.get("modelId")
        if not mid:
            continue
        author = mid.split("/", 1)[0] if "/" in mid else None
        tags = m.get("tags") or []
        records.append(
            ModelRecord(
                source="huggingface",
                name=mid,
                detail_level="shallow",
                author=author,                                   # list 回應 author=null → 由 id 推導
                source_url="https://huggingface.co/" + mid,
                description=None,                                # HF 淺層無描述
                usage=m.get("pipeline_tag"),                     # pipeline_tag 當用途
                tags=(json.dumps(tags, ensure_ascii=False) if tags else None),
                updated_at=_normalize_hf_date(m.get("lastModified")),
                download_count=m.get("downloads"),               # 近 30 天
                download_metric="30d",
                model_format=fmt,                                # ← lane 權威
            )
        )
    return records


# ----------------------------------------------------------------
# 協調 + 分頁停損
# ----------------------------------------------------------------


def scrape_hf(
    *,
    start,
    end,
    whitelist=DEFAULT_HF_WHITELIST,
    formats=DEFAULT_HF_FORMATS,
    max_records: int | None = None,
    fetch: Callable[[str], tuple[list[dict], str | None]] | None = None,
) -> list[ModelRecord]:
    """每 author × format lane 分頁抓取，依 lastModified 過濾 [start, end]。

    停損：lane 內 lastModified 降序，遇 < start 即停該 lane（其後只會更舊）。
    max_records：跨所有 lane 的總筆數安全上限。fetch 可注入（測試免網路）。
    """
    if fetch is None:
        fetch = fetch_models_page
    start_d, end_d = _as_date(start), _as_date(end)

    out: list[ModelRecord] = []
    for author in whitelist:
        for fmt in formats:
            url: str | None = build_lane_url(author, fmt)
            stop = False
            while url and not stop:
                if max_records is not None and len(out) >= max_records:
                    return out[:max_records]
                models, next_url = fetch(url)
                for rec in parse_hf_models(models, fmt):
                    d = _date_of(rec.updated_at)
                    if d is None:
                        continue                      # 無日期 → 保守跳過
                    if d < start_d:
                        stop = True                   # 降序：其後只會更舊 → 停該 lane
                        break
                    if d > end_d:
                        continue                      # 太新，尚未進範圍
                    out.append(rec)
                    if max_records is not None and len(out) >= max_records:
                        return out[:max_records]
                url = next_url
    return out


# ----------------------------------------------------------------
# helpers
# ----------------------------------------------------------------


def _normalize_hf_date(s: str | None) -> str | None:
    """'2026-06-15T13:45:27.000Z' → '2026-06-15 13:45:27'；無法解析回原值前 19 字。"""
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return s[:19].replace("T", " ")  # best-effort fallback


def _as_date(x) -> date:
    """date / datetime / 'YYYY-MM-DD' 字串 → date。"""
    if isinstance(x, datetime):
        return x.date()
    if isinstance(x, date):
        return x
    return datetime.strptime(str(x)[:10], "%Y-%m-%d").date()


def _date_of(s: str | None) -> date | None:
    """取 'YYYY-MM-DD ...' 的日期部分；無法解析回 None。"""
    if not s:
        return None
    try:
        return datetime.strptime(s[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


__all__ = [
    "DEFAULT_HF_WHITELIST",
    "DEFAULT_HF_FORMATS",
    "build_lane_url",
    "fetch_models_page",
    "parse_hf_models",
    "scrape_hf",
]
