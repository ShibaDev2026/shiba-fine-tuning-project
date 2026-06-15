"""ollama_scraper.py — 解析 ollama.com/library HTML → 淺層 ModelRecord（source=ollama）。

職責（SRP）：只負責「Ollama library 清單頁 → 淺層 record」。三階段拆開：
- fetch_library_html：純 I/O（urllib 抓 HTML）。
- parse_library_html：純解析（HTML → record list，不過濾、不打網路）。
- scrape_ollama_library：協調（抓 → 解析 → 日期過濾 → max_records 上限）。

DIP：本模組只依賴 ModelRecord 契約，不碰 SQL；HTML 可由外部注入（html=...）便於測試。

解析錨點：ollama.com 用 Alpine.js 的 x-test-* 測試屬性（穩定），不靠易變 class：
    <li x-test-model>                        每張卡片
      <a href="/library/{name}">             → name / source_url
      <p class="max-w-lg ...">{desc}</p>     → description
      <span x-test-capability>tools</span>   → usage（能力標籤，可多個）
      <span x-test-size>8b</span>            → param_size（可多個，"/" join）
      <span x-test-pull-count>115.9M</span>  → download_count（cumulative）
      <span class="flex items-center" title="Nov 30, 2024 10:34 PM UTC">
        ... <span x-test-updated>1 year ago</span>
更新時間：優先取外層 span 的 title 精確 UTC 時戳；缺則退回 x-test-updated 相對時間近似
        （Shiba：相對時間貼近即可，不吹毛求疵）。

固定值：model_format='gguf'、download_metric='cumulative'、detail_level='shallow'。
"""

from __future__ import annotations

import json
import re
import urllib.request
from datetime import date, datetime, timedelta, timezone
from html.parser import HTMLParser

from .store import ModelRecord

_LIBRARY_URL = "https://ollama.com/library"
_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"

# Ollama 卡片 title 的精確時戳格式，例："Nov 30, 2024 10:34 PM UTC"
_TITLE_DATE_FMT = "%b %d, %Y %I:%M %p UTC"
# 相對時間近似（貼近即可）：單位 → 約略天數（hour/minute 視為今天）
_REL_UNIT_DAYS = {"year": 365, "month": 30, "week": 7, "day": 1, "hour": 0, "minute": 0}
_REL_RE = re.compile(r"(\d+)\s+(year|month|week|day|hour|minute)s?\s+ago", re.I)


# ----------------------------------------------------------------
# I/O
# ----------------------------------------------------------------


def fetch_library_html(timeout: int = 30) -> str:
    """抓 ollama.com/library 整頁 HTML（單頁即回傳全部 model，無分頁處理）。"""
    req = urllib.request.Request(_LIBRARY_URL, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310（固定官方 URL）
        return resp.read().decode("utf-8", "replace")


# ----------------------------------------------------------------
# 純解析（HTMLParser 狀態機）
# ----------------------------------------------------------------


class _CardParser(HTMLParser):
    """逐張 <li x-test-model> 卡片累積欄位；遇 </li> 收成一筆 dict 進 self.cards。"""

    def __init__(self) -> None:
        super().__init__()
        self.cards: list[dict] = []
        self._cur: dict | None = None       # 當前累積中的卡片
        self._capture: str | None = None     # 當前擷取中的 x-test 欄位 key
        self._buf: str = ""                   # 文字緩衝（description / x-test span 共用）
        self._in_desc = False                 # 是否在 description <p> 內

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "li" and "x-test-model" in a:
            self._cur = {"capabilities": [], "sizes": []}
            return
        if self._cur is None:
            return
        # 無值屬性（如 x-test-model）值為 None → 一律 coerce 成 ""
        href = a.get("href") or ""
        cls = a.get("class") or ""
        if tag == "a" and href.startswith("/library/"):
            self._cur["name"] = href.split("/library/", 1)[1].strip("/")
            self._cur["source_url"] = "https://ollama.com" + href
        elif tag == "p" and "max-w-lg" in cls:
            # description 段（與下方統計 <p class="my-4 flex ...">　區隔）
            self._in_desc = True
            self._buf = ""
        elif tag == "span":
            if "x-test-capability" in a:
                self._capture, self._buf = "capability", ""
            elif "x-test-size" in a:
                self._capture, self._buf = "size", ""
            elif "x-test-pull-count" in a:
                self._capture, self._buf = "pulls", ""
            elif "x-test-updated" in a:
                self._capture, self._buf = "updated_rel", ""
            # 更新時間外層 span 的精確時戳；僅在能解析為日期時採用，
            # 避免誤抓 model-title 的 title（那是 model 名，非日期）
            title = a.get("title")
            if title and _parse_title_date(title):
                self._cur["updated_title"] = title

    def handle_data(self, data):
        if self._cur is None:
            return
        if self._in_desc or self._capture is not None:
            self._buf += data

    def handle_endtag(self, tag):
        if self._cur is None:
            return
        if tag == "p" and self._in_desc:
            self._cur["description"] = self._buf.strip()
            self._in_desc = False
            self._buf = ""
        elif tag == "span" and self._capture is not None:
            val = self._buf.strip()
            if self._capture == "capability" and val:
                self._cur["capabilities"].append(val)
            elif self._capture == "size" and val:
                self._cur["sizes"].append(val)
            elif self._capture == "pulls":
                self._cur["pulls"] = val
            elif self._capture == "updated_rel":
                self._cur["updated_rel"] = val
            self._capture = None
            self._buf = ""
        elif tag == "li":
            self.cards.append(self._cur)
            self._cur = None


def parse_library_html(html: str, ref: datetime | None = None) -> list[ModelRecord]:
    """HTML → list[ModelRecord]（不過濾日期、不打網路）。

    ref：相對時間近似的基準時間（預設 now UTC）；title 精確時戳優先時用不到。
    """
    if ref is None:
        ref = datetime.now(timezone.utc)
    parser = _CardParser()
    parser.feed(html)

    records: list[ModelRecord] = []
    for c in parser.cards:
        name = c.get("name")
        if not name:
            continue  # 無 name 不是有效卡片
        caps = c.get("capabilities", [])
        sizes = c.get("sizes", [])
        records.append(
            ModelRecord(
                source="ollama",
                name=name,
                detail_level="shallow",
                source_url=c.get("source_url"),
                description=c.get("description") or None,
                usage=", ".join(caps) or None,                 # 能力標籤合一
                # tags 留原始 provenance：能力 + 規格全標籤 JSON（供日後重抽欄位）
                tags=(json.dumps(caps + sizes, ensure_ascii=False) if (caps or sizes) else None),
                param_size="/".join(sizes) or None,
                download_count=_parse_pull_count(c.get("pulls")),
                download_metric="cumulative",
                model_format="gguf",
                updated_at=_resolve_updated(c.get("updated_title"), c.get("updated_rel"), ref),
            )
        )
    return records


# ----------------------------------------------------------------
# 協調 + 日期過濾
# ----------------------------------------------------------------


def scrape_ollama_library(
    *,
    start,
    end,
    max_records: int | None = None,
    html: str | None = None,
    ref: datetime | None = None,
) -> list[ModelRecord]:
    """抓 → 解析 → 依 updated_at 過濾 [start, end] → 取前 max_records 筆。

    html 可注入（測試免打網路）；None 則即時抓。start/end 接受 date 或 'YYYY-MM-DD'。
    清單頁已按熱門度排序，故 max_records 截斷保留最熱門的範圍內 model。
    """
    start_d, end_d = _as_date(start), _as_date(end)
    if html is None:
        html = fetch_library_html()
    records = parse_library_html(html, ref=ref)
    records = [r for r in records if _in_range(r.updated_at, start_d, end_d)]
    if max_records is not None:
        records = records[:max_records]
    return records


# ----------------------------------------------------------------
# helpers
# ----------------------------------------------------------------


def _parse_title_date(title: str) -> str | None:
    """'Nov 30, 2024 10:34 PM UTC' → 'YYYY-MM-DD HH:MM:SS'；非此格式回 None。"""
    try:
        return datetime.strptime(title.strip(), _TITLE_DATE_FMT).strftime("%Y-%m-%d %H:%M:%S")
    except (ValueError, AttributeError):
        return None


def _parse_relative_date(rel: str | None, ref: datetime) -> str | None:
    """'1 year ago' / '11 months ago' → 近似 'YYYY-MM-DD HH:MM:SS'；無法解析回 None。"""
    if not rel:
        return None
    m = _REL_RE.search(rel)
    if not m:
        return None  # "yesterday" 等不規則字樣 → 近似不處理
    n, unit = int(m.group(1)), m.group(2).lower()
    approx = ref - timedelta(days=_REL_UNIT_DAYS[unit] * n)
    return approx.strftime("%Y-%m-%d %H:%M:%S")


def _resolve_updated(title: str | None, rel: str | None, ref: datetime) -> str | None:
    """更新時間：精確 title 優先，缺則退回相對時間近似。"""
    return (_parse_title_date(title) if title else None) or _parse_relative_date(rel, ref)


def _parse_pull_count(s: str | None) -> int | None:
    """'115.9M' → 115900000；'12.3K' → 12300；純數字直接轉；無法解析回 None。"""
    if not s:
        return None
    s = s.strip().replace(",", "")
    mult = 1
    if s and s[-1] in "KkMmBb":
        mult = {"k": 1_000, "m": 1_000_000, "b": 1_000_000_000}[s[-1].lower()]
        s = s[:-1]
    try:
        return int(float(s) * mult)
    except ValueError:
        return None


def _as_date(x) -> date:
    """date / datetime / 'YYYY-MM-DD' 字串 → date。"""
    if isinstance(x, datetime):
        return x.date()
    if isinstance(x, date):
        return x
    return datetime.strptime(str(x)[:10], "%Y-%m-%d").date()


def _in_range(updated_at: str | None, start: date, end: date) -> bool:
    """updated_at 是否落在 [start, end]。

    無可解析日期 → 保守排除：日期過濾目的是限定近期，未知日期無法確認在範圍內。
    （Ollama 卡片實務上皆帶 title 精確時戳，此分支幾乎不觸發。）
    """
    if not updated_at:
        return False
    try:
        d = datetime.strptime(updated_at[:10], "%Y-%m-%d").date()
    except ValueError:
        return False
    return start <= d <= end


__all__ = [
    "fetch_library_html",
    "parse_library_html",
    "scrape_ollama_library",
]
