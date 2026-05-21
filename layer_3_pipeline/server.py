# layer_3_pipeline/server.py
# FastAPI :8001 輕量 wrapper，由 launchd 常駐於 host（需要 MPS / MLX）
# POST /trigger/{block} → 執行 fine-tune（直接呼叫 runner，不走 docker）
# GET  /runs            → 最近 10 筆訓練 run
# GET  /health          → Layer 2 心跳檢查

import logging
import sqlite3
from contextlib import contextmanager
from fastapi import FastAPI, HTTPException

from shiba_config import CONFIG
from .runner import run_finetune_if_ready


def _conn_factory():
    """開啟 DB 連線（row_factory 已設定）"""
    from shiba_db import open_connection
    return open_connection("writer")


app = FastAPI(title="Shiba Layer 3 Pipeline", version="0.9.0")
logger = logging.getLogger("layer3.server")


@app.on_event("startup")
def _startup():
    """啟動 sanity check — finetune_runs 必須由 Layer 2 backend init / 或手動套用
    layer_1_memory/db/schema.sql（最終 PR-O-9 後改 config/db/schema_core.sql）。

    PR-O-2 解 V6：移除本檔內聯的 CREATE TABLE / INDEX（spec §3.2），
    DDL 來源統一在 layer_1_memory/db/schema.sql 單一處，避免雙重 DDL 漂移。
    """
    conn = _conn_factory()
    try:
        conn.execute("SELECT 1 FROM finetune_runs LIMIT 1").fetchone()
        logger.info("finetune_runs 表 sanity check 通過")
    except sqlite3.OperationalError as e:
        # 表不存在 = Layer 2 backend 未啟動過 / DB 未初始化；明確錯誤勝於靜默建空表
        raise RuntimeError(
            "finetune_runs 表不存在；請先啟動 Layer 2 backend 完成 schema 初始化，"
            "或手動套用 layer_1_memory/db/schema.sql"
        ) from e
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
