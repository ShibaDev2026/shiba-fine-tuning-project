# layer_2_chamber/backend/api/routes_finetune.py
"""手動觸發 fine-tune pipeline"""

from fastapi import APIRouter
from ..core.config import get_db

router = APIRouter(prefix="/api/v1/finetune", tags=["finetune"])


@router.post("/trigger/{adapter_block}")
def trigger_finetune(adapter_block: int):
    """手動觸發指定 block 的 fine-tune（threshold=0，不受樣本數限制）"""
    from layer_3_pipeline.runner import run_finetune_if_ready
    conn = get_db()
    try:
        result = run_finetune_if_ready(conn, adapter_block=adapter_block, threshold=0)
        return result or {"status": "skipped", "reason": "no approved samples"}
    finally:
        conn.close()


@router.get("/runs")
def list_runs():
    """列出最近 10 次 fine-tune run"""
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT * FROM finetune_runs ORDER BY id DESC LIMIT 10"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()
