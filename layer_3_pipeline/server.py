# layer_3_pipeline/server.py
# FastAPI :8001 輕量 wrapper，由 launchd 常駐於 host（需要 MPS / MLX）
# POST /trigger/{block} → 執行 fine-tune（直接呼叫 runner，不走 docker）
# GET  /runs            → 最近 10 筆訓練 run
# GET  /health          → Layer 2 心跳檢查

import logging
from contextlib import contextmanager
from fastapi import FastAPI, HTTPException

from shiba_config import CONFIG
from .runner import run_finetune_if_ready


def _conn_factory():
    """開啟 DB 連線（row_factory 已設定）"""
    import sqlite3
    conn = sqlite3.connect(str(CONFIG.paths.db))
    conn.row_factory = sqlite3.Row
    return conn


app = FastAPI(title="Shiba Layer 3 Pipeline", version="0.9.0")
logger = logging.getLogger("layer3.server")


@app.get("/health")
def health():
    return {"status": "ok", "layer": 3}


@app.post("/trigger/{adapter_block}")
def trigger(adapter_block: int):
    """Layer 2 透過 HTTP 觸發指定 block fine-tune（threshold=0）"""
    if adapter_block not in (1, 2):
        raise HTTPException(status_code=400, detail="adapter_block must be 1 or 2")
    conn = _conn_factory()
    try:
        result = run_finetune_if_ready(conn, adapter_block=adapter_block, threshold=0)
        return result or {"status": "skipped", "reason": "no approved samples"}
    except Exception as e:
        logger.error("trigger block%d 失敗：%s", adapter_block, e)
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


@app.get("/runs")
def list_runs():
    """最近 10 筆訓練 run 紀錄"""
    conn = _conn_factory()
    try:
        rows = conn.execute(
            "SELECT * FROM finetune_runs ORDER BY id DESC LIMIT 10"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "layer_3_pipeline.server:app",
        host="127.0.0.1",  # 只監聽 localhost，不對外
        port=CONFIG.services.layer3_port,
        reload=False,
    )
