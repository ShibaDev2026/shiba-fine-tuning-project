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
import sys
from pathlib import Path

# 將專案根加入 sys.path，讓 models_loader / models_db 可被匯入（與 paraphrase_service 同 pattern）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from models_db import init_model_registry, sync_model_registry
from .api.routes_dashboard import router as dashboard_router
from .api.routes_dataset import router as dataset_router
from .api.routes_mcp import router as mcp_router
from .api.routes_finetune import router as finetune_router
from .api.routes_teachers import router as teachers_router, html_router as teacher_html_router
from .api.routes_models import router as models_router
from .api.routes_router_config import router as router_config_router
from .api.routes_router import router as router_router
from .api.routes_memory import router as memory_router
from .core.background import setup_scheduler
from .core.config import DB_PATH, init_layer2_db

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


def _conn_factory():
    """給背景排程使用的 connection factory"""
    from shiba_db import open_connection
    return open_connection("writer")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 啟動：確保 DB schema、啟動排程
    init_layer2_db()

    # model_registry：建表 + sync config/models/*.yaml 變動
    # 失敗不阻擋 API 啟動（registry 為新模組，初期允許 degrade）
    try:
        with _conn_factory() as registry_conn:
            init_model_registry(registry_conn)
            stats = sync_model_registry(registry_conn)
        logger.info("model_registry sync 完成：%s", stats)
    except Exception as e:
        logger.exception("model_registry sync 失敗，跳過：%s", e)

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

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 開發用途
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(models_router)
app.include_router(router_config_router)
app.include_router(router_router)
app.include_router(memory_router)
app.include_router(dashboard_router)
app.include_router(dataset_router)
app.include_router(mcp_router)
app.include_router(finetune_router)
app.include_router(teachers_router)
app.include_router(teacher_html_router)


@app.get("/health")
def health():
    return {"status": "ok", "db": str(DB_PATH)}
