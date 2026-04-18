"""
main.py — Layer 2 精神時光屋 FastAPI 入口

啟動：
    cd layer_2_chamber/backend
    uvicorn main:app --reload --port 8000

端點總覽：
    GET  /health
    GET  /api/v1/stats
    GET  /api/v1/samples
    POST /api/v1/samples/{id}/approve
    POST /api/v1/samples/{id}/reject
    POST /api/v1/dataset/extract
    POST /api/v1/dataset/export
    GET  /api/v1/dataset/export/download
    POST /mcp/tools/query_memory
    POST /mcp/tools/get_stats
"""

from contextlib import asynccontextmanager
import logging
import sqlite3

from fastapi import FastAPI

from .api.routes_dashboard import router as dashboard_router
from .api.routes_dataset import router as dataset_router
from .api.routes_mcp import router as mcp_router
from .core.background import setup_scheduler
from .core.config import DB_PATH, init_layer2_db

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


def _conn_factory() -> sqlite3.Connection:
    """給背景排程使用的 connection factory"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 啟動：確保 DB schema、啟動排程
    init_layer2_db()
    scheduler = setup_scheduler(app, _conn_factory)
    if scheduler:
        scheduler.start()
        logger.info("APScheduler 已啟動（extraction/scoring/compress）")
    else:
        logger.warning("APScheduler 未啟動，背景任務停用")

    yield

    # 關閉
    if scheduler and scheduler.running:
        scheduler.shutdown(wait=False)


app = FastAPI(
    title="Shiba Layer 2 Chamber",
    description="訓練樣本冶煉 + MCP 記憶查詢",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(dashboard_router)
app.include_router(dataset_router)
app.include_router(mcp_router)


@app.get("/health")
def health():
    return {"status": "ok", "db": str(DB_PATH)}
