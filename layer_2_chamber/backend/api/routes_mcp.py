"""
routes_mcp.py — MCP (Model Context Protocol) 工具端點

POST /mcp/tools/query_memory    — RAG 搜尋歷史記憶
POST /mcp/tools/get_stats       — 取得訓練樣本統計

供 Claude Code MCP server 呼叫，讓 Claude 可直接查詢 shiba-brain.db。
"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel
import sqlite3

from ..core.config import get_db
from ..extraction.dataset_formatter import get_export_stats

router = APIRouter(prefix="/mcp/tools", tags=["mcp"])


class QueryMemoryRequest(BaseModel):
    query: str
    project_path: str | None = None
    top_n: int = 3


class QueryMemoryResponse(BaseModel):
    results: list[dict]
    query: str


@router.post("/query_memory", response_model=QueryMemoryResponse)
def query_memory(
    req: QueryMemoryRequest,
    conn: sqlite3.Connection = Depends(get_db),
):
    """
    FTS5 trigram 搜尋歷史 session，供 Claude 注入 context。
    對應 Layer 1 rag.py 的 search_sessions，但透過 HTTP 提供給 MCP。
    """
    safe_query = _sanitize(req.query)
    if not safe_query:
        return QueryMemoryResponse(results=[], query=req.query)

    sql = """
        SELECT session_uuid, project_path, event_types, ended_at,
               snippet(sessions_fts, 3, '', '', '...', 20) AS snippet
        FROM sessions_fts
        WHERE sessions_fts MATCH ?
        ORDER BY rank
        LIMIT ?
    """
    rows = conn.execute(sql, (safe_query, req.top_n * 2)).fetchall()

    results = [
        {
            "session_uuid": r["session_uuid"],
            "project_path": r["project_path"],
            "event_types": r["event_types"].split() if r["event_types"] else [],
            "ended_at": r["ended_at"] or "",
            "snippet": r["snippet"] or "",
        }
        for r in rows
    ]

    # 同專案優先
    if req.project_path:
        results.sort(key=lambda r: (0 if r["project_path"] == req.project_path else 1))

    return QueryMemoryResponse(results=results[: req.top_n], query=req.query)


@router.post("/get_stats")
def get_stats(conn: sqlite3.Connection = Depends(get_db)):
    """回傳訓練樣本統計，供 Claude 了解訓練進度"""
    return get_export_stats(conn)


def _sanitize(query: str) -> str:
    """移除 FTS5 特殊字元，trigram 最少需 3 字元"""
    for ch in ('"', "'", "(", ")", "*", ":", "-", "+"):
        query = query.replace(ch, " ")
    query = query[:200].strip()
    return query if len(query) >= 3 else ""
