# layer_2_chamber/backend/api/routes_router_config.py
"""Router Config API — 讀取 / 更新 router_config 表（模型選擇 + Ollama 維護狀態）"""

import sqlite3
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from ..core.config import get_db
from models_db import list_current_by_role

router = APIRouter(prefix="/api/v1/router-config", tags=["router-config"])

# 允許更新的 key 白名單（防止任意寫入）
_MUTABLE_KEYS = {
    "classifier_model_yaml",
    "compressor_model_yaml",
    "responder_model_yaml",
    "training_base_block1_yaml",
    "training_base_block2_yaml",
    "ollama_status",
}

_ROLE_KEY_MAP = {
    "classifier_model_yaml":        "classifier",
    "compressor_model_yaml":        "compressor",
    "responder_model_yaml":         "responder",
    "training_base_block1_yaml":    "training_base",
    "training_base_block2_yaml":    "training_base",
}


class PutBody(BaseModel):
    value: str


@router.get("")
def get_router_config(conn: sqlite3.Connection = Depends(get_db)):
    """取全部 router_config 設定（含 ollama_status + 各 role 選擇）"""
    rows = conn.execute(
        "SELECT key, value, updated_at FROM router_config ORDER BY key"
    ).fetchall()
    return {r["key"]: {"value": r["value"], "updated_at": r["updated_at"]} for r in rows}


@router.get("/candidates")
def get_candidates(conn: sqlite3.Connection = Depends(get_db)):
    """回傳各 key 的可選 yaml stem 清單（給前端 dropdown 渲染用）"""
    result: dict[str, list[str]] = {}
    for key, role in _ROLE_KEY_MAP.items():
        if role not in result:
            result[key] = [m["model_name"] for m in list_current_by_role(conn, role)]
    return result


@router.put("/{key}")
def update_router_config(
    key: str,
    body: PutBody,
    conn: sqlite3.Connection = Depends(get_db),
):
    """更新單一 router_config 設定。

    - ollama_status：只接受 'online' | 'offline'
    - *_model_yaml：value 必須是該 role 的合法 is_current stem
    """
    if key not in _MUTABLE_KEYS:
        raise HTTPException(status_code=400, detail=f"key={key!r} 不允許修改")

    value = body.value.strip()

    # ollama_status 格式驗證
    if key == "ollama_status":
        if value not in ("online", "offline"):
            raise HTTPException(status_code=400, detail="ollama_status 只接受 'online' 或 'offline'")

    # model yaml key：確認 stem 存在於 is_current registry
    elif key in _ROLE_KEY_MAP:
        role = _ROLE_KEY_MAP[key]
        candidates = [m["model_name"] for m in list_current_by_role(conn, role)]
        if value not in candidates:
            raise HTTPException(
                status_code=400,
                detail=f"{key} 的值 {value!r} 不在可用候選內（{candidates}）"
            )

    conn.execute(
        "UPDATE router_config SET value=?, updated_at=datetime('now') WHERE key=?",
        (value, key),
    )
    conn.commit()

    if conn.execute("SELECT changes()").fetchone()[0] == 0:
        # key 不存在（不應發生，seed 已補上，但防禦性處理）
        raise HTTPException(status_code=404, detail=f"key={key!r} 不存在於 router_config")

    return {"key": key, "value": value}
