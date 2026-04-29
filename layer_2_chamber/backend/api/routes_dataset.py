"""
routes_dataset.py — 資料集生成 API

POST /api/v1/dataset/extract    — 執行 pipeline 抽取（路徑 A + B）
POST /api/v1/dataset/export     — 匯出 Alpaca JSONL
GET  /api/v1/dataset/export     — 查詢最新 export 狀態
"""

import tempfile
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse
import sqlite3

from ..core.config import get_db, init_layer2_db
from ..extraction.pipeline import run_extraction_v2
from ..extraction.dataset_formatter import export_dataset
from ..services.refiner_service import refine_pending_raw_samples

router = APIRouter(prefix="/api/v1/dataset", tags=["dataset"])

# 最近一次 export 的檔案路徑（process 內快取）
_last_export: dict | None = None


@router.post("/extract")
def trigger_extraction(conn: sqlite3.Connection = Depends(get_db)):
    """
    執行 pipeline 抽取（路徑 A + B）。
    回傳本次新增的樣本統計。
    """
    stats = run_extraction_v2(conn)
    return {"extracted_at": datetime.now(timezone.utc).isoformat(), **stats}


@router.post("/refine")
def trigger_refine():
    """手動觸發精煉器，處理所有 status='raw' 的樣本"""
    stats = refine_pending_raw_samples(init_layer2_db)
    return {"refined_at": datetime.now(timezone.utc).isoformat(), **stats}


@router.post("/export")
def trigger_export(
    adapter_block: int | None = None,
    since_id: int = 0,
    conn: sqlite3.Connection = Depends(get_db),
):
    """
    將 approved 樣本匯出為 Alpaca JSONL。
    回傳統計與下載用 export_id。
    """
    global _last_export

    output_path = Path(tempfile.mkdtemp()) / "dataset.jsonl"
    stats = export_dataset(conn, output_path, adapter_block=adapter_block, since_id=since_id)

    _last_export = {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "path": str(output_path),
        **stats,
    }
    return _last_export


@router.get("/export/download")
def download_export():
    """下載最新匯出的 JSONL 檔案"""
    if not _last_export or not Path(_last_export["path"]).exists():
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="尚無可下載的 export，請先執行 POST /export")

    return FileResponse(
        path=_last_export["path"],
        filename="shiba_dataset.jsonl",
        media_type="application/jsonl",
    )
