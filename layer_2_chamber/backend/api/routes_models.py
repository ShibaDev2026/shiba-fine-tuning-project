# layer_2_chamber/backend/api/routes_models.py
"""Model Registry API — 讀取 model_registry 表（唯讀）"""

import sqlite3
from fastapi import APIRouter, Depends, HTTPException
from ..core.config import get_db
from models_db import get_current, list_current_by_role, list_history

router = APIRouter(prefix="/api/v1/models", tags=["models"])

_VALID_ROLES = {"classifier", "compressor", "responder", "embedder", "training_base"}


@router.get("/registry")
def get_registry(conn: sqlite3.Connection = Depends(get_db)):
    """列出所有 role 的當前 yaml（前端 PhaseModels 初始載入用）"""
    rows = conn.execute(
        """SELECT * FROM model_registry
           WHERE is_current=1 AND change_kind != 'removed'
           ORDER BY role, display_name"""
    ).fetchall()
    import json
    result = []
    for r in rows:
        d = dict(r)
        d["snapshot"] = json.loads(d["snapshot"])
        result.append(d)
    return result


@router.get("/registry/by-role/{role}")
def get_by_role(role: str, conn: sqlite3.Connection = Depends(get_db)):
    """列指定 role 的當前候選 yaml（dropdown 用）"""
    if role not in _VALID_ROLES:
        raise HTTPException(status_code=400, detail=f"role={role!r} 不合法")
    return list_current_by_role(conn, role)


@router.get("/{model_name}/history")
def get_model_history(model_name: str, conn: sqlite3.Connection = Depends(get_db)):
    """取某 yaml 的完整版本歷史（最新在前）"""
    rows = list_history(conn, model_name)
    if not rows:
        raise HTTPException(status_code=404, detail=f"找不到 model_name={model_name!r}")
    return rows
