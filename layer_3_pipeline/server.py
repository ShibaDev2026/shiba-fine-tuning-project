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


@app.on_event("startup")
def _startup():
    """啟動時兜底建立 finetune_runs（DDL 主源在 layer_1_memory/db/schema.sql；
    此處作為舊 DB 升級時的幂等防呆，定義須與 schema.sql 完全對齊）"""
    conn = _conn_factory()
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS finetune_runs (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                adapter_block INTEGER NOT NULL,
                status        TEXT NOT NULL DEFAULT 'pending'
                                CHECK(status IN ('pending', 'running', 'done', 'failed')),
                dataset_path  TEXT,
                adapter_path  TEXT,
                gguf_path     TEXT,
                ollama_model  TEXT,
                sample_count  INTEGER,
                error_msg     TEXT,
                started_at    TEXT,
                finished_at   TEXT,
                created_at    TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_finetune_runs_block_status "
            "ON finetune_runs(adapter_block, status, id)"
        )
        conn.commit()
        logger.info("finetune_runs 表確認完成")
    finally:
        conn.close()


@app.get("/health")
def health():
    return {"status": "ok", "layer": 3}


@app.post("/trigger/{adapter_block}")
def trigger(adapter_block: int):
    """Layer 2 透過 HTTP 觸發指定 block fine-tune；門檻由 trigger_policy 決定。"""
    if adapter_block not in (1, 2):
        raise HTTPException(status_code=400, detail="adapter_block must be 1 or 2")
    conn = _conn_factory()
    try:
        result = run_finetune_if_ready(conn, adapter_block=adapter_block)
        return result or {"status": "skipped", "reason": "trigger policy 未觸發"}
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
