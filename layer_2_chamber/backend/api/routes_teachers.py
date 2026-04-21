"""
routes_teachers.py — Teacher 配額監控與管理

GET   /api/v1/teachers          列出所有 teacher（含當日 req 數、token 用量、配額剩餘）
PATCH /api/v1/teachers/{id}     修改 daily_limit 或 is_active
POST  /api/v1/teachers/{id}/test 對指定 teacher 發送測試 prompt
GET   /teacher-test             Teacher 測試前端頁面
"""

import sqlite3
import logging
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, Field

from ..core.config import get_db
from ..services.teacher_service import call_teacher_for_test, get_teacher_by_id

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/teachers", tags=["teachers"])
html_router = APIRouter(tags=["teacher-ui"])

_LIST_SQL = """
SELECT t.id, t.name, t.model_id, t.api_base, t.priority,
       t.daily_limit,
       COALESCE(t.daily_request_limit, t.daily_limit)          AS daily_request_limit,
       t.daily_token_limit,
       COALESCE(t.quota_reset_period, 'daily')                 AS quota_reset_period,
       t.is_active, t.is_daily_limit_reached,
       COALESCE(t.requests_today, 0)                           AS today_requests,
       COALESCE(t.input_tokens_today, 0) + COALESCE(t.output_tokens_today, 0)
                                                               AS today_tokens,
       t.quota_exhausted_at,
       CASE
           WHEN COALESCE(t.daily_request_limit, t.daily_limit) IS NULL THEN NULL
           ELSE MAX(0, COALESCE(t.daily_request_limit, t.daily_limit) - COALESCE(t.requests_today, 0))
       END                                                     AS quota_remaining
FROM teachers t
ORDER BY t.priority
"""


class TeacherPatch(BaseModel):
    daily_limit: int | None = Field(default=None, ge=1)
    is_active: bool | None = None


class TestRequest(BaseModel):
    prompt: str = "請用一句話介紹你自己。"


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


@router.post("/{teacher_id}/test")
def test_teacher(
    teacher_id: int,
    body: TestRequest,
    conn: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    """對指定 Teacher 發送測試 prompt，回傳 response + token 計量 + latency"""
    teacher = get_teacher_by_id(conn, teacher_id)
    if not teacher:
        raise HTTPException(status_code=404, detail=f"Teacher id={teacher_id} 不存在")

    start = time.monotonic()
    text, input_t, output_t, status = call_teacher_for_test(teacher, body.prompt)
    latency_ms = int((time.monotonic() - start) * 1000)

    error: str | None = None
    if status == "no_key":
        error = "API Key 未設定（請先執行 setup_teachers.py --setup）"
    elif status == "quota_exceeded":
        error = "配額已滿（429）"
    elif text is None:
        error = "API 呼叫失敗"

    return {
        "teacher_id": teacher_id,
        "name": teacher["name"],
        "model_id": teacher["model_id"],
        "response": text,
        "input_tokens": input_t,
        "output_tokens": output_t,
        "latency_ms": latency_ms,
        "error": error,
    }


@html_router.get("/teacher-test", response_class=HTMLResponse)
def teacher_test_page() -> FileResponse:
    """Teacher 測試前端頁面"""
    html_path = Path(__file__).parent.parent.parent / "static" / "teacher_test.html"
    if not html_path.exists():
        return HTMLResponse("<h1>teacher_test.html 找不到</h1>", status_code=404)
    return FileResponse(str(html_path), media_type="text/html")
