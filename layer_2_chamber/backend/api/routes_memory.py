# layer_2_chamber/backend/api/routes_memory.py
"""Phase 1 日常記憶層 API — sessions 查詢、統計、訊息內容"""

import json
import sqlite3
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Query
from ..core.config import get_db

router = APIRouter(prefix="/api/v1/memory", tags=["memory"])

EVENT_TYPES = [
    "code_gen", "git_ops", "terminal_ops", "debugging",
    "architecture", "knowledge_qa", "fine_tuning_ops",
]


@router.get("/sessions")
def list_sessions(
    date_from: Optional[str] = Query(None, description="YYYY-MM-DD"),
    date_to: Optional[str] = Query(None, description="YYYY-MM-DD"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    conn: sqlite3.Connection = Depends(get_db),
):
    """列出 sessions，支援起迄日期過濾"""
    where_clauses = []
    params: list = []

    if date_from:
        where_clauses.append("date(COALESCE(s.ended_at, s.started_at)) >= ?")
        params.append(date_from)
    if date_to:
        where_clauses.append("date(COALESCE(s.ended_at, s.started_at)) <= ?")
        params.append(date_to)

    where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
    params += [limit, offset]

    rows = conn.execute(
        f"""SELECT s.id, s.uuid, s.event_types, s.exchange_count,
                   s.files_modified, s.commits, s.ended_at, s.started_at,
                   s.context_summary
            FROM sessions s
            {where_sql}
            ORDER BY s.id DESC
            LIMIT ? OFFSET ?""",
        params,
    ).fetchall()
    return [dict(r) for r in rows]


@router.get("/stats")
def memory_stats(conn: sqlite3.Connection = Depends(get_db)):
    """Sessions 統計 + 7 日趨勢（依 event_type 分組）"""
    total = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]

    seven_days_ago = (datetime.utcnow() - timedelta(days=7)).strftime("%Y-%m-%d")
    week_total = conn.execute(
        "SELECT COUNT(*) FROM sessions WHERE date(COALESCE(ended_at, started_at)) >= ?",
        (seven_days_ago,),
    ).fetchone()[0]

    # 平均每 session 對話數與 commits
    avgs = conn.execute(
        "SELECT AVG(exchange_count) AS avg_exchanges, AVG(commits) AS avg_commits FROM sessions"
    ).fetchone()

    rows = conn.execute(
        """SELECT date(COALESCE(ended_at, started_at)) AS day, event_types
           FROM sessions
           WHERE date(COALESCE(ended_at, started_at)) >= ?
           ORDER BY day""",
        (seven_days_ago,),
    ).fetchall()

    trend: dict = {}
    for row in rows:
        day = row["day"]
        if not day:
            continue
        if day not in trend:
            trend[day] = {et: 0 for et in EVENT_TYPES}
        try:
            types = json.loads(row["event_types"] or "[]")
            for et in types:
                if et in trend[day]:
                    trend[day][et] += 1
        except Exception:
            pass

    return {
        "total_sessions": total,
        "week_total": week_total,
        "avg_exchanges": round(avgs["avg_exchanges"]) if avgs["avg_exchanges"] else 0,
        "avg_commits": round(avgs["avg_commits"], 1) if avgs["avg_commits"] else 0,
        "trend": trend,
    }


@router.get("/sessions/{session_id}/messages")
def session_messages(
    session_id: int,
    limit: int = Query(10, ge=1, le=30),
    conn: sqlite3.Connection = Depends(get_db),
):
    """取得 session 最近 N 筆有內容的訊息（供 Detail Panel 顯示對話脈絡）"""
    msgs = conn.execute(
        """SELECT role, content, message_time, has_tool_use, tool_names
           FROM messages
           WHERE session_id = ?
             AND content IS NOT NULL AND content != ''
           ORDER BY message_time DESC
           LIMIT ?""",
        (session_id, limit),
    ).fetchall()
    return [dict(m) for m in reversed(msgs)]
