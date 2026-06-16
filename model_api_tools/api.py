"""api.py — model_api_tools 的 FastAPI 觸發 adapter（獨立 app，不掛 Layer 2 backend）。

職責（SRP）：HTTP 觸發 → 組 ScrapeParams → 呼叫 run_scrape → 回 JSON 摘要，
不含抓取 / 掃描 / SQL 邏輯（全委派 core.runner）。與 cli.py 共用同一份 core（DIP）。

FastAPI 為「此 adapter 專屬」依賴（core 不依賴它）；故 import 僅在本檔，
不會拖累無 fastapi 的測試環境（pytest 對本檔之測試以 importorskip 保護）。

啟動：uvicorn model_api_tools.api:app --port 8900
Vue dashboard 的「更新模型清單」按鈕另接此 app。
"""

from __future__ import annotations

from typing import Callable, Optional

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel

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


app = FastAPI(title="model_api_tools scraper", version="0.1.0")


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
