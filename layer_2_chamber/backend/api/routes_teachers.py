"""
routes_teachers.py — Teacher 配額監控與管理

GET  /api/v1/teachers         列出所有 teacher（含當日 req 數、token 用量、配額剩餘）
PATCH /api/v1/teachers/{id}   修改 daily_limit 或 is_active
"""

import sqlite3
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..core.config import get_db

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/teachers", tags=["teachers"])

_LIST_SQL = """
SELECT t.id, t.name, t.model_id, t.api_base, t.priority,
       t.daily_limit, t.is_active, t.is_daily_limit_reached,
       COUNT(l.id)                                                                    AS today_requests,
       COALESCE(SUM(CASE WHEN l.response_status = 'success' THEN l.tokens_used ELSE 0 END), 0) AS today_tokens,
       MAX(0, t.daily_limit - COUNT(l.id))                                           AS quota_remaining
FROM teachers t
LEFT JOIN teacher_usage_logs l
    ON l.teacher_id = t.id
    AND l.used_at >= date('now', 'localtime')
GROUP BY t.id
ORDER BY t.priority
"""


class TeacherPatch(BaseModel):
    daily_limit: int | None = Field(default=None, ge=1)
    is_active: bool | None = None


@router.get("")
def list_teachers(conn: sqlite3.Connection = Depends(get_db)) -> list[dict[str, Any]]:
    rows = conn.execute(_LIST_SQL).fetchall()
    return [dict(r) for r in rows]  # keychain_ref 不在 SELECT 中，安全


@router.patch("/{teacher_id}")
def patch_teacher(
    teacher_id: int,
    body: TeacherPatch,
    conn: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    if body.daily_limit is None and body.is_active is None:
        raise HTTPException(status_code=422, detail="至少提供 daily_limit 或 is_active 其中之一")

    existing = conn.execute("SELECT id FROM teachers WHERE id = ?", (teacher_id,)).fetchone()
    if not existing:
        raise HTTPException(status_code=404, detail=f"Teacher id={teacher_id} 不存在")

    updated: list[str] = []
    if body.daily_limit is not None:
        conn.execute("UPDATE teachers SET daily_limit = ? WHERE id = ?", (body.daily_limit, teacher_id))
        updated.append("daily_limit")
    if body.is_active is not None:
        conn.execute("UPDATE teachers SET is_active = ? WHERE id = ?", (int(body.is_active), teacher_id))
        updated.append("is_active")

    conn.commit()
    logger.info("Teacher id=%s 已更新：%s", teacher_id, updated)
    return {"teacher_id": teacher_id, "updated": updated}
