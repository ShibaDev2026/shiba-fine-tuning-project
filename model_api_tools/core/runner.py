"""runner.py — 觸發式爬取協調器（CLI 與 FastAPI 共用，DIP）。

run_scrape 串起整條流程，產生單一 scrape_run_id：
    遠端淺層 scrape（ollama + hf）→ 本機掃描 deep enrich → store.write_batch（append-only）。

職責（SRP）：只負責「協調 + 彙整摘要」，不含解析/掃描/SQL 細節（委派給 core 各模組）。
DIP：三個遠端/本機 collaborator（ollama_fn / hf_fn / scan_fn）可注入，預設綁真實模組函式；
     測試注入 fake 即可免網路驗證協調邏輯。
"""

from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from shiba_config import CONFIG

from . import hf_scraper, local_scanner, ollama_scraper, store
from .hf_scraper import DEFAULT_HF_FORMATS, DEFAULT_HF_WHITELIST


@dataclass
class ScrapeParams:
    """一次觸發的參數（CLI / API body 對映）。日期 None → 動態解析為「近一年」。"""

    sources: tuple = ("ollama", "huggingface")          # 要爬的遠端來源
    start: str | None = None                            # None → 今天 - 365d
    end: str | None = None                              # None → 今天
    max_records: int | None = None                      # 每來源安全上限
    hf_whitelist: tuple = DEFAULT_HF_WHITELIST
    formats: tuple = DEFAULT_HF_FORMATS
    scan_local: bool = True                             # 是否本機掃描 + deep enrich


def run_scrape(
    params: ScrapeParams | None = None,
    *,
    conn: sqlite3.Connection | None = None,
    ollama_fn=None,
    hf_fn=None,
    scan_fn=None,
) -> dict:
    """執行一次爬取並寫入 search_model_list；回傳摘要 dict。

    conn=None → 自開統一 DB（CONFIG.paths.db）並負責關閉；傳入則沿用不關（測試用 :memory:）。
    ollama_fn / hf_fn / scan_fn 可注入（DIP / 測試）；預設為真實模組函式。
    """
    params = params or ScrapeParams()
    ollama_fn = ollama_fn or ollama_scraper.scrape_ollama_library
    hf_fn = hf_fn or hf_scraper.scrape_hf
    scan_fn = scan_fn or local_scanner.scan_all_installed

    start, end = _resolve_range(params.start, params.end)
    run_id = uuid.uuid4().hex
    scraped_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    # 1) 遠端淺層
    catalog: list = []
    if "ollama" in params.sources:
        catalog += ollama_fn(start=start, end=end, max_records=params.max_records)
    if "huggingface" in params.sources:
        catalog += hf_fn(
            start=start, end=end, max_records=params.max_records,
            whitelist=params.hf_whitelist, formats=params.formats,
        )

    # 2) 本機掃描 + deep enrich
    records = local_scanner.enrich_catalog(catalog, scan_fn()) if params.scan_local else catalog

    # 3) 寫入（單一 run_id / scraped_at）
    own_conn = conn is None
    if own_conn:
        conn = sqlite3.connect(str(CONFIG.paths.db))
    try:
        store.init_search_model_list(conn)
        n = store.write_batch(conn, records, run_id, scraped_at)
    finally:
        if own_conn:
            conn.close()

    return {
        "scrape_run_id": run_id,
        "scraped_at": scraped_at,
        "range": {"start": start, "end": end},
        "total": n,
        "by_source": _count_by(records, "source"),
        "by_detail": _count_by(records, "detail_level"),
        "local_installed": sum(1 for r in records if r.is_local_installed),
    }


# ----------------------------------------------------------------
# helpers
# ----------------------------------------------------------------


def _resolve_range(start: str | None, end: str | None) -> tuple[str, str]:
    """None → 動態「近一年」：start=今天-365d、end=今天（避免寫死日期過期）。"""
    today = date.today()
    s = start or (today - timedelta(days=365)).isoformat()
    e = end or today.isoformat()
    return s, e


def _count_by(records: list, attr: str) -> dict:
    """依某欄位計數（摘要用）。"""
    out: dict = {}
    for r in records:
        k = getattr(r, attr)
        out[k] = out.get(k, 0) + 1
    return out


__all__ = ["ScrapeParams", "run_scrape"]
