"""api.py — model_api_tools 的 FastAPI adapter（獨立 app，不掛 Layer 2 backend）。

職責（SRP）：兩類 HTTP 端點，皆委派 core，不含抓取 / 掃描 / SQL 邏輯：
- 觸發爬取：POST /scrape/{source} → 組 ScrapeParams → run_scrape → JSON 摘要。
- 搜尋清單：GET /models → store.search_models/count_models → 分頁結果。
與 cli.py 共用同一份 core（DIP）。

FastAPI 為「此 adapter 專屬」依賴（core 不依賴它）；故 import 僅在本檔，
不會拖累無 fastapi 的測試環境（pytest 對本檔之測試以 importorskip 保護）。

啟動：uvicorn model_api_tools.api:app --port 8900
Vue dashboard 的「更新模型清單」按鈕另接此 app。
"""

from __future__ import annotations

import sqlite3
from typing import Callable, Iterator, Optional

from fastapi import Depends, FastAPI, HTTPException, Query
from pydantic import BaseModel
from shiba_config import CONFIG

from .core import store
from .core.hf_scraper import DEFAULT_HF_FORMATS, DEFAULT_HF_WHITELIST
from .core.runner import ScrapeParams, run_scrape

# 路徑來源 → sources tuple（與 cli._SOURCE_MAP 對映一致，hf = huggingface 簡寫）
_SOURCE_MAP = {
    "ollama": ("ollama",),
    "hf": ("huggingface",),
    "both": ("ollama", "huggingface"),
}


class ScrapeRequest(BaseModel):
    """POST /scrape/{source} 的 body；全部選填，未給則落回 run_scrape 預設。"""

    start: Optional[str] = None              # YYYY-MM-DD；None → 今天-365d
    end: Optional[str] = None                # YYYY-MM-DD；None → 今天
    max_records: Optional[int] = None        # 每來源安全上限
    whitelist: Optional[list[str]] = None    # HF author 白名單；None → 預設
    formats: Optional[list[str]] = None      # HF 格式 lane；None → 預設
    scan_local: bool = True                  # 是否本機掃描 + deep enrich


def get_runner() -> Callable[[ScrapeParams], dict]:
    """DIP seam：回傳協調器；測試以 app.dependency_overrides[get_runner] 注入 fake。"""
    return run_scrape


def get_conn() -> Iterator[sqlite3.Connection]:
    """DIP seam：開統一 DB（CONFIG.paths.db）唯讀查詢用，請求結束關閉。

    測試以 app.dependency_overrides[get_conn] 注入 in-memory conn（覆寫版不關閉）。
    """
    conn = sqlite3.connect(str(CONFIG.paths.db))
    try:
        yield conn
    finally:
        conn.close()


class ModelSearchResponse(BaseModel):
    """GET /models 回應；items 為 v_search_model_latest 列（dict 直出）。"""

    total: int                               # 符合條件總數（分頁前）
    count: int                               # 本頁實際回傳筆數
    limit: int
    offset: int
    items: list[dict]


app = FastAPI(title="model_api_tools scraper", version="0.1.0")


@app.get("/models", response_model=ModelSearchResponse)
def list_models(
    source: Optional[str] = Query(None, description="ollama / huggingface"),
    model_format: Optional[str] = Query(None, alias="format", description="gguf / mlx ..."),
    author: Optional[str] = Query(None, description="HF author / 發布者"),
    q: Optional[str] = Query(None, description="對 name 模糊比對的關鍵字"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    conn: sqlite3.Connection = Depends(get_conn),
) -> ModelSearchResponse:
    """搜尋已爬取的模型清單（走 v_search_model_latest，每 (source,name) 最新一批）。"""
    total = store.count_models(
        conn, source=source, model_format=model_format, author=author, keyword=q
    )
    items = store.search_models(
        conn, source=source, model_format=model_format, author=author,
        keyword=q, limit=limit, offset=offset,
    )
    return ModelSearchResponse(
        total=total, count=len(items), limit=limit, offset=offset, items=items
    )


@app.post("/scrape/{source}")
def scrape(source: str, body: ScrapeRequest, runner=Depends(get_runner)) -> dict:
    """觸發一次爬取；source ∈ {ollama, hf, both}。回傳 run_scrape 摘要 dict。"""
    if source not in _SOURCE_MAP:
        raise HTTPException(status_code=404, detail=f"unknown source: {source}")
    params = ScrapeParams(
        sources=_SOURCE_MAP[source],
        start=body.start,
        end=body.end,
        max_records=body.max_records,
        hf_whitelist=tuple(body.whitelist) if body.whitelist else DEFAULT_HF_WHITELIST,
        formats=tuple(body.formats) if body.formats else DEFAULT_HF_FORMATS,
        scan_local=body.scan_local,
    )
    return runner(params)


@app.get("/health")
def health() -> dict:
    """liveness 探針（dashboard / 監控用）。"""
    return {"status": "ok"}
