"""
routes_teachers.py — Teacher 配額監控與管理

GET   /api/v1/teachers          列出所有 teacher（含 vendor / has_api_key 等擴充欄位）
GET   /api/v1/teachers/{id}     單一師父詳情
POST  /api/v1/teachers          新增師父 metadata（不含 api_key）
PUT   /api/v1/teachers/{id}     完整更新師父 metadata（不含 api_key）
PATCH /api/v1/teachers/{id}     修改 daily_limit 或 is_active（向下相容）
POST  /api/v1/teachers/{id}/test 對指定 teacher 發送測試 prompt
GET   /teacher-test             Teacher 測試前端頁面
"""

import sqlite3
import logging
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status as http_status
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, Field

from ..core.config import get_db
from ..services.teacher_service import call_teacher_for_test, get_teacher_by_id

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/teachers", tags=["teachers"])
html_router = APIRouter(tags=["teacher-ui"])

# 共用欄位集（list 與 single 共用，避免重複）
_SELECT_COLS = """
    t.id, t.name, t.model_id, t.api_base, t.priority,
    t.vendor,
    t.daily_limit,
    COALESCE(t.daily_request_limit, t.daily_limit)          AS daily_request_limit,
    t.daily_token_limit,
    COALESCE(t.quota_reset_period, 'daily')                 AS quota_reset_period,
    t.is_active, t.is_daily_limit_reached,
    COALESCE(t.requests_today, 0)                           AS today_requests,
    COALESCE(t.input_tokens_today, 0)                       AS input_tokens_today,
    COALESCE(t.output_tokens_today, 0)                      AS output_tokens_today,
    COALESCE(t.input_tokens_today, 0) + COALESCE(t.output_tokens_today, 0)
                                                            AS today_tokens,
    t.quota_exhausted_at,
    t.quota_exhausted_type,
    t.created_at,
    CASE WHEN COALESCE(t.keychain_ref, '') != '' THEN 1 ELSE 0 END AS has_api_key,
    CASE
        WHEN COALESCE(t.daily_request_limit, t.daily_limit) IS NULL THEN NULL
        ELSE MAX(0, COALESCE(t.daily_request_limit, t.daily_limit) - COALESCE(t.requests_today, 0))
    END                                                     AS quota_remaining
"""

_LIST_SQL = f"SELECT {_SELECT_COLS} FROM teachers t ORDER BY t.priority"
_SINGLE_SQL = f"SELECT {_SELECT_COLS} FROM teachers t WHERE t.id = ?"


# ── Pydantic 模型 ─────────────────────────────────────────

class TeacherPatch(BaseModel):
    """向下相容的 PATCH（僅 daily_limit / is_active）"""
    daily_limit: int | None = Field(default=None, ge=1)
    is_active: bool | None = None


class TeacherCreate(BaseModel):
    """新增師父 metadata（不含 api_key，設 key 請用 setup_teachers.py）"""
    name: str
    model_id: str
    api_base: str
    vendor: str = "unknown"
    priority: int = 0
    daily_request_limit: int = Field(default=250, ge=1)
    daily_token_limit: int | None = None
    quota_reset_period: str = "daily"
    is_active: bool = True


class TeacherUpdate(BaseModel):
    """完整更新師父 metadata（name 不可改；省略欄位保持不變）"""
    model_id: str | None = None
    api_base: str | None = None
    vendor: str | None = None
    priority: int | None = None
    daily_request_limit: int | None = Field(default=None, ge=1)
    daily_token_limit: int | None = None
    quota_reset_period: str | None = None
    is_active: bool | None = None


class TestRequest(BaseModel):
    prompt: str = "請用一句話介紹你自己。"


# ── 端點 ─────────────────────────────────────────────────

@router.get("")
def list_teachers(conn: sqlite3.Connection = Depends(get_db)) -> list[dict[str, Any]]:
    rows = conn.execute(_LIST_SQL).fetchall()
    return [dict(r) for r in rows]


@router.get("/{teacher_id}")
def get_teacher(teacher_id: int, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    row = conn.execute(_SINGLE_SQL, (teacher_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail=f"Teacher id={teacher_id} 不存在")
    return dict(row)


@router.post("", status_code=http_status.HTTP_201_CREATED)
def create_teacher(
    body: TeacherCreate,
    conn: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    existing = conn.execute("SELECT id FROM teachers WHERE name = ?", (body.name,)).fetchone()
    if existing:
        raise HTTPException(status_code=409, detail=f"師父名稱 '{body.name}' 已存在")

    cursor = conn.execute(
        """INSERT INTO teachers
           (name, model_id, api_base, vendor, priority,
            daily_request_limit, daily_limit, daily_token_limit,
            quota_reset_period, is_active)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            body.name, body.model_id, body.api_base, body.vendor, body.priority,
            body.daily_request_limit,
            body.daily_request_limit,   # daily_limit 與 daily_request_limit 保持同步（向下相容）
            body.daily_token_limit,
            body.quota_reset_period, int(body.is_active),
        ),
    )
    conn.commit()
    logger.info("新師父 '%s' 建立 id=%s", body.name, cursor.lastrowid)
    return {"id": cursor.lastrowid, "name": body.name}


@router.put("/{teacher_id}")
def update_teacher(
    teacher_id: int,
    body: TeacherUpdate,
    conn: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    existing = conn.execute("SELECT id FROM teachers WHERE id = ?", (teacher_id,)).fetchone()
    if not existing:
        raise HTTPException(status_code=404, detail=f"Teacher id={teacher_id} 不存在")

    updates = body.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(status_code=422, detail="至少提供一個更新欄位")

    fields: list[str] = []
    values: list[Any] = []
    for field, val in updates.items():
        fields.append(f"{field} = ?")
        values.append(int(val) if isinstance(val, bool) else val)
        # daily_request_limit 變更時同步 daily_limit（確保 is_quota_available 計算正確）
        if field == "daily_request_limit" and val is not None:
            fields.append("daily_limit = ?")
            values.append(val)

    values.append(teacher_id)
    conn.execute(f"UPDATE teachers SET {', '.join(fields)} WHERE id = ?", values)
    conn.commit()
    logger.info("Teacher id=%s 已更新：%s", teacher_id, list(updates.keys()))
    return {"teacher_id": teacher_id, "updated": list(updates.keys())}


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
