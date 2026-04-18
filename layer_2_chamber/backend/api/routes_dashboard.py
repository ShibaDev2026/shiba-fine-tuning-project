"""
routes_dashboard.py — 訓練樣本監控 API

GET  /api/v1/stats              — 樣本統計摘要
GET  /api/v1/samples            — 列出樣本（支援 status / adapter_block 過濾）
POST /api/v1/samples/{id}/approve  — 手動 approve
POST /api/v1/samples/{id}/reject   — 手動 reject
"""

from fastapi import APIRouter, Depends, HTTPException
import sqlite3

from ..core.config import get_db
from ..extraction.dataset_formatter import get_export_stats

router = APIRouter(prefix="/api/v1", tags=["dashboard"])


@router.get("/stats")
def get_stats(conn: sqlite3.Connection = Depends(get_db)):
    """回傳 training_samples 統計摘要"""
    return get_export_stats(conn)


@router.get("/samples")
def list_samples(
    status: str | None = None,
    adapter_block: int | None = None,
    limit: int = 50,
    offset: int = 0,
    conn: sqlite3.Connection = Depends(get_db),
):
    """列出訓練樣本，支援 status / adapter_block 過濾與分頁"""
    sql = "SELECT id, source, event_type, instruction, output, score, status, adapter_block, created_at FROM training_samples WHERE 1=1"
    params: list = []

    if status:
        sql += " AND status = ?"
        params.append(status)
    if adapter_block is not None:
        sql += " AND adapter_block = ?"
        params.append(adapter_block)

    sql += " ORDER BY id DESC LIMIT ? OFFSET ?"
    params += [limit, offset]

    rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


@router.post("/samples/{sample_id}/approve")
def approve_sample(sample_id: int, conn: sqlite3.Connection = Depends(get_db)):
    """手動 approve 樣本"""
    return _update_status(conn, sample_id, "approved")


@router.post("/samples/{sample_id}/reject")
def reject_sample(sample_id: int, conn: sqlite3.Connection = Depends(get_db)):
    """手動 reject 樣本"""
    return _update_status(conn, sample_id, "rejected")


def _update_status(conn: sqlite3.Connection, sample_id: int, status: str) -> dict:
    row = conn.execute(
        "SELECT id FROM training_samples WHERE id = ?", (sample_id,)
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="sample not found")

    conn.execute(
        "UPDATE training_samples SET status = ?, reviewed_at = datetime('now') WHERE id = ?",
        (status, sample_id),
    )
    conn.commit()
    return {"id": sample_id, "status": status}
