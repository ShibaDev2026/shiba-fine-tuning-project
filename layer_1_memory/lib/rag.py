"""
rag.py — 語意向量 + FTS5 雙路召回 RAG 注入
功能：
1. 嘗試向量召回 exchange_embeddings（語意匹配因果對）
2. 若 Ollama 不可用或無資料，fallback FTS5 sessions_fts
3. 輸出 Claude Code hookSpecificOutput 格式的 Markdown 字串
"""

import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import yaml

from .db import get_connection
from .embedder import get_embedding, cosine_similarity

logger = logging.getLogger(__name__)

# 每個 token 約 4 字元（中英混合保守估計）
_CHARS_PER_TOKEN = 4
# FTS5 snippet 函式的最大 token 數
_SNIPPET_TOKENS = 32


def retrieve_relevant_sessions(
    query: str,
    project_path: str | None = None,
    top_n: int = 5,
) -> list[dict]:
    """
    用 FTS5 MATCH 搜尋相關 session，回傳最多 top_n 筆。
    每筆包含：session_uuid / project_path / event_types / snippet / ended_at

    Args:
        query: 搜尋關鍵字（來自目前 session 的訊息內容）
        project_path: 若指定則優先同專案結果
        top_n: 最多回傳幾筆
    """
    if not query or not query.strip():
        return []

    results: list[dict] = []

    try:
        with get_connection() as conn:
            # 清理 query（FTS5 對特殊字元敏感）
            safe_query = _sanitize_fts_query(query)
            if not safe_query:
                return []

            # FTS5 檢索：使用 snippet() 函式取摘要片段
            sql = """
                SELECT
                    session_uuid,
                    project_path,
                    event_types,
                    ended_at,
                    snippet(sessions_fts, 3, '', '', '...', ?)  AS snippet
                FROM sessions_fts
                WHERE sessions_fts MATCH ?
                ORDER BY rank
                LIMIT ?
            """
            rows = conn.execute(sql, (_SNIPPET_TOKENS, safe_query, top_n * 2)).fetchall()

            for row in rows:
                results.append({
                    "session_uuid": row["session_uuid"],
                    "project_path": row["project_path"],
                    "event_types": row["event_types"].split() if row["event_types"] else [],
                    "ended_at": row["ended_at"] or "",
                    "snippet": row["snippet"] or "",
                })

    except sqlite3.OperationalError as e:
        # FTS5 表不存在或 query 語法錯誤時靜默處理
        logger.debug("FTS5 檢索失敗（可能 DB 尚未初始化）：%s", e)
        return []

    # 同專案結果優先排序
    if project_path:
        results.sort(key=lambda r: (0 if r["project_path"] == project_path else 1))

    # 更新 access_count 與 last_accessed（非同步，失敗不影響主流程）
    _update_access_stats(results[:top_n])

    return results[:top_n]


def build_rag_output(
    sessions: list[dict],
    token_budget: int = 500,
) -> str:
    """
    將檢索結果格式化為 hookSpecificOutput Markdown 字串。
    超出 token_budget 時截斷最舊的幾筆。

    回傳格式範例：
    ## 相關歷史記憶（top 3）
    ### [git_ops] 2026-04-10 — 3 exchanges
    修改了 Dockerfile、docker-compose.yml，執行了 git commit -m "fix: ..."
    """
    if not sessions:
        return ""

    char_budget = token_budget * _CHARS_PER_TOKEN
    header = "## 相關歷史記憶（top {}）\n".format(len(sessions))
    sections: list[str] = []

    for s in sessions:
        event_str = ", ".join(s["event_types"]) if s["event_types"] else "general"
        date_str = _format_date(s["ended_at"])
        snippet = s["snippet"].strip()

        section = "### [{}] {}\n{}\n".format(event_str, date_str, snippet)
        sections.append(section)

    # 逐筆加入，直到接近預算上限
    body = ""
    for section in sections:
        candidate = body + section
        if len(header) + len(candidate) > char_budget:
            break
        body = candidate

    if not body:
        # 至少放一筆（截斷內容）
        first = sections[0]
        remaining = char_budget - len(header) - 3  # 3 for "..."
        body = first[:max(remaining, 50)] + "...\n"

    return header + body


def get_rag_context(
    query: str,
    project_path: str | None = None,
    top_n: int = 3,
    token_budget: int = 500,
) -> str:
    """
    主要入口：一站式取得 RAG 注入字串。
    優先向量召回 exchange_embeddings；Ollama 不可用時 fallback FTS5。
    """
    # 嘗試語意向量召回
    vector_results = _vector_search(query, top_n=top_n)
    if vector_results:
        return _build_exchange_context(vector_results, token_budget=token_budget)

    # Fallback：FTS5 關鍵字召回
    sessions = retrieve_relevant_sessions(
        query=query,
        project_path=project_path,
        top_n=top_n,
    )
    if not sessions:
        return ""
    return build_rag_output(sessions, token_budget=token_budget)


def _vector_search(query: str, top_n: int = 3) -> list[dict]:
    """
    向量召回：取得 query embedding → cosine similarity 掃描 exchange_embeddings。
    Ollama 不可用或表為空時回傳空 list。
    """
    query_vec = get_embedding(query)
    if query_vec is None:
        return []

    try:
        with get_connection() as conn:
            # 過濾高發散 instruction：
            # 同一句話（instruction）衍生出 3 種以上不同 commands，
            # 代表它無法單一指向特定操作（例如「好」「ok」「繼續」），
            # 召回這類結果反而會引入雜訊，故自動排除。
            # 閾值 3 = 允許一句話對應最多 2 種合理變體（如 git add + git commit）
            rows = conn.execute("""
                SELECT session_uuid, instruction, commands, embedding
                FROM exchange_embeddings
                WHERE instruction IN (
                    SELECT instruction
                    FROM exchange_embeddings
                    GROUP BY instruction
                    HAVING count(DISTINCT commands) < 3
                )
            """).fetchall()
    except sqlite3.OperationalError:
        return []

    if not rows:
        return []

    scored = []
    for row in rows:
        try:
            vec = json.loads(row["embedding"])
            score = cosine_similarity(query_vec, vec)
            scored.append({
                "session_uuid": row["session_uuid"],
                "instruction": row["instruction"],
                "commands": row["commands"],
                "score": score,
            })
        except Exception:
            continue

    scored.sort(key=lambda x: x["score"], reverse=True)
    # 只回傳相似度 > 0.35 的結果（降低門檻以提高召回率）
    return [r for r in scored[:top_n] if r["score"] > 0.35]


def _build_exchange_context(exchanges: list[dict], token_budget: int = 500) -> str:
    """將因果對格式化為 RAG 注入字串"""
    char_budget = token_budget * _CHARS_PER_TOKEN
    header = "## 相關歷史記憶（top {}）\n".format(len(exchanges))
    body = ""
    for ex in exchanges:
        section = "### 問題：{}\n指令：{}\n".format(
            ex["instruction"].strip(), ex["commands"].strip()
        )
        if len(header) + len(body) + len(section) > char_budget:
            break
        body += section
    return header + body if body else ""


# ============================================================
# 內部輔助函式
# ============================================================

def _sanitize_fts_query(query: str) -> str:
    """
    清理 FTS5 查詢字串：
    - 移除 FTS5 特殊字元（避免語法錯誤）
    - 截斷過長查詢（FTS5 效能考量）
    """
    # 移除 FTS5 運算子與特殊字元
    sanitized = query.replace('"', " ").replace("'", " ")
    sanitized = sanitized.replace("(", " ").replace(")", " ")
    sanitized = sanitized.replace("*", " ").replace(":", " ")
    sanitized = sanitized.replace("-", " ").replace("+", " ")

    # 取前 200 字元，避免超長 query
    sanitized = sanitized[:200].strip()

    # trigram 最少需 3 字元才能命中索引
    if len(sanitized) < 3:
        return ""

    return sanitized


def _format_date(ended_at: str) -> str:
    """將 ISO datetime 字串格式化為可讀日期（2026-04-10）"""
    if not ended_at:
        return "unknown date"
    try:
        dt = datetime.fromisoformat(ended_at.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d")
    except (ValueError, AttributeError):
        return ended_at[:10] if len(ended_at) >= 10 else ended_at


def _update_access_stats(sessions: list[dict]) -> None:
    """
    更新被 RAG 命中的 branch 存取統計（access_count / last_accessed）。
    Phase 7 的衰減邏輯依賴這些數據。
    失敗時靜默處理，不影響 RAG 主流程。
    """
    if not sessions:
        return

    uuids = [s["session_uuid"] for s in sessions]
    now = datetime.now(timezone.utc).isoformat()

    try:
        with get_connection() as conn:
            for uuid in uuids:
                conn.execute(
                    """UPDATE branches
                       SET access_count  = access_count + 1,
                           last_accessed = ?
                       WHERE session_id IN (
                           SELECT id FROM sessions WHERE uuid = ?
                       )
                       AND is_active = 1""",
                    (now, uuid),
                )
            conn.commit()
    except Exception as e:  # noqa: BLE001
        logger.debug("更新 RAG access stats 失敗（無害）：%s", e)
