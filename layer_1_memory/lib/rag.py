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
from typing import Literal

import yaml

from .db import get_connection
from .embedder import get_embedding, cosine_similarity

logger = logging.getLogger(__name__)

# 每個 token 約 4 字元（中英混合保守估計）
_CHARS_PER_TOKEN = 4
# FTS5 snippet 函式的最大 token 數
_SNIPPET_TOKENS = 32

# RAG 召回路徑標記 — 由 callee 顯式回傳，避免 caller 用字串 sniff 推斷
RagSource = Literal["vector", "fts5", "none"]

# 同意詞判定閾值：一個 instruction 衍生出 >= 3 種不同 commands 即視為「無指向性」。
# 與 _vector_search 結果側過濾用的字面 3 一致——同一原則的查詢側對應（改值請兩處同步）。
_DIVERGENCE_THRESHOLD = 3


def is_low_signal_query(query: str) -> bool:
    """查詢側前置 gate：判斷 query 是否為「已學會的同意詞」（無召回價值）。

    純資料驅動：拿 query 精確比對 `exchange_embeddings.instruction`，若該 instruction
    在歷史裡衍生出 >= _DIVERGENCE_THRESHOLD 種不同 commands，代表它無法單一指向特定
    操作（如「好/ok/繼續」或命令雜訊），召回只會引入混淆 → 回 True，呼叫端跳過召回。

    設計約束：
    - 走 SQLite（不依賴 Ollama），離線亦有效。
    - 累積後再學：新詞 / 出現次數不足、divergence 未達閾值 → 回 False，照常召回。
    - 任何 DB 例外一律回 False（fail-open：寧可多召回，不可誤殺正常查詢）。
    """
    q = (query or "").strip()
    if not q:
        return False
    try:
        with get_connection() as conn:
            row = conn.execute(
                """
                SELECT count(DISTINCT commands) AS divergence
                FROM exchange_embeddings
                WHERE instruction = ?
                """,
                (q,),
            ).fetchone()
    except sqlite3.Error:
        # fail-open：任何 DB 例外都回 False（寧可多召回，不可誤殺正常查詢，
        # 更不可讓例外冒泡到 hook 外層 handler 而靜默吞掉整個召回流程）
        return False
    divergence = row["divergence"] if row else 0
    return divergence >= _DIVERGENCE_THRESHOLD


# harness / remember 外掛產生的「系統 prompt」前綴白名單——這些不是 Shiba 的自然語言
# 查詢，而是記憶系統（remember 外掛 save-session / compress-ndc）與 Claude Code harness
# （子任務通知 / context 續接摘要）自動 spawn 的內部 LLM 呼叫，會經同一個 UserPromptSubmit
# hook。它們召回無意義，且會污染 recall_log、誤觸 macOS 通知、留下無法配對的孤兒 pending。
#
# 為何用 content-prefix 而非 env marker：這些來源是不可控的第三方外掛/harness，無法注入
# SHIBA_INTERNAL 之類的環境標記。改錨定「穩定且夠長」的開頭前綴——這些是固定的外掛 prompt
# 檔與 harness 結構標籤，不會逐對話漂移；錨定開頭可避免誤殺 Shiba 引用這些字串的真實討論。
_SYSTEM_META_PREFIXES = (
    "You are summarizing a Claude Code session",   # remember 外掛 save-session.prompt
    "Apply maximum non-destructive compression",   # remember 外掛 compress-ndc.prompt
    "<task-notification>",                          # harness 子任務完成通知
    "This session is being continued from a previous conversation",  # harness context 續接摘要
)


def is_system_meta_query(query: str) -> bool:
    """查詢側結構性 gate：判斷 query 是否為 harness/外掛產生的系統 prompt（非 Shiba 查詢）。

    與 is_low_signal_query（資料驅動同意詞）正交：本函式純前綴比對，不查 DB、零延遲，
    對「結構上就不是使用者輸入」的內部 LLM 呼叫一刀攔下——不召回、不寫 log、不通知、
    不寫 pending（杜絕孤兒 pending 的主要來源）。

    設計約束：
    - 錨定開頭（startswith）：避免誤殺 Shiba 在真實討論中引用這些字串的查詢。
    - 不可控來源：簽章來自第三方 remember 外掛 prompt 檔與 harness 結構標籤，故用穩定前綴
      而非 env marker（無法對外掛 spawn 的 session 注入環境變數）。
    """
    q = (query or "").strip()
    if not q:
        return False
    return q.startswith(_SYSTEM_META_PREFIXES)


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


def _retrieve(
    query: str,
    project_path: str | None,
    top_n: int,
    token_budget: int,
) -> tuple[str, RagSource, list[dict]]:
    """核心召回：回 (context, source, hits)。

    hits 為命中的原始結構化結果（vector 帶 cosine `score`+instruction/commands；
    fts5 帶 `snippet`/`session_uuid`、無 cosine 分數）。ctx 為空時 hits 一律回 []，
    讓「有召回」判斷（len(hits)>0）與顯示內容一致。get_rag_context（不破壞既有簽章）
    與 get_rag_context_with_hits 皆委派此函式（DRY）。
    """
    # 嘗試語意向量召回
    vector_results = _vector_search(query, top_n=top_n)
    if vector_results:
        ctx = _build_exchange_context(vector_results, token_budget=token_budget)
        return (ctx, "vector", vector_results) if ctx else ("", "none", [])

    # Fallback：FTS5 關鍵字召回
    sessions = retrieve_relevant_sessions(
        query=query,
        project_path=project_path,
        top_n=top_n,
    )
    if not sessions:
        return ("", "none", [])
    ctx = build_rag_output(sessions, token_budget=token_budget)
    return (ctx, "fts5", sessions) if ctx else ("", "none", [])


def get_rag_context(
    query: str,
    project_path: str | None = None,
    top_n: int = 3,
    token_budget: int = 500,
) -> tuple[str, RagSource]:
    """
    主要入口：一站式取得 RAG 注入字串 + 召回路徑來源。
    優先向量召回 exchange_embeddings；Ollama 不可用時 fallback FTS5。

    回傳：(context, source)
      - context 為 "" 時，source 為 "none"
      - vector 命中時 source="vector"，FTS5 命中時 source="fts5"

    caller 拿 source 用於觀測 / debug echo / metrics，不再用字串 sniff 推斷。
    """
    ctx, source, _hits = _retrieve(query, project_path, top_n, token_budget)
    return (ctx, source)


def get_rag_context_with_hits(
    query: str,
    project_path: str | None = None,
    top_n: int = 3,
    token_budget: int = 500,
) -> tuple[str, RagSource, list[dict]]:
    """get_rag_context 的擴充版：額外回結構化 hits 供 recall_log 記「召回原因」。

    既有 get_rag_context 簽章不變（向後相容）；新呼叫端（session_start_hook）改用本函式。
    """
    return _retrieve(query, project_path, top_n, token_budget)


def retrieve_for_eval_with_context(
    query: str,
    project_path: str | None = None,
    top_n: int = 3,
    window_k: int = 2,
    preview_chars: int = 200,
) -> dict:
    """
    評估專用召回 API（擴展版）：每個 hit 額外帶 ±window_k 個鄰居 exchange 上下文。

    與 retrieve_for_eval 的差異：
    - 命中向量召回後，用 exchange_id 反查 (branch_id, exchange_idx)
    - 拉出同一 branch 內 [idx-K, idx+K] 範圍的鄰居 exchange
    - 每筆呈現「Q: user_text_preview / A: final_text_preview」，命中那筆標 ★
    - 若 hit 沒有 exchange_id（舊資料 backfill 失敗）→ 退回單 exchange 行為

    回傳結構與 retrieve_for_eval 相容；額外加 `expanded`（True 表示有任何 hit 真的擴展）。
    """
    vector_results = _vector_search(query, top_n=top_n)
    if vector_results:
        contexts: list[str] = []
        any_expanded = False
        seen_uuids: list[str] = []
        for hit in vector_results:
            if hit["session_uuid"] not in seen_uuids:
                seen_uuids.append(hit["session_uuid"])

            block, expanded = _build_context_block(hit, window_k, preview_chars)
            contexts.append(block)
            if expanded:
                any_expanded = True

        return {
            "query": query,
            "source": "vector",
            "retrieved_contexts": contexts,
            "retrieved_session_uuids": seen_uuids,
            "expanded": any_expanded,
            "window_k": window_k,
        }

    # Fallback：FTS5（與 retrieve_for_eval 同行為，不擴展）
    sessions = retrieve_relevant_sessions(query=query, project_path=project_path, top_n=top_n)
    if not sessions:
        return {
            "query": query, "source": "fts5", "retrieved_contexts": [],
            "retrieved_session_uuids": [], "expanded": False, "window_k": window_k,
        }
    return {
        "query": query,
        "source": "fts5",
        "retrieved_contexts": [
            "session: {}\n{}".format(s.get("session_uuid", ""), s.get("snippet", ""))
            for s in sessions
        ],
        "retrieved_session_uuids": [s.get("session_uuid", "") for s in sessions],
        "expanded": False,
        "window_k": window_k,
    }


def _build_context_block(
    hit: dict,
    window_k: int,
    preview_chars: int,
) -> tuple[str, bool]:
    """
    對單一 hit 構建 context 字串。
    回傳 (block, expanded)：expanded=True 表示成功取到鄰居並擴展。
    """
    exchange_id = hit.get("exchange_id")
    instruction = hit["instruction"].strip()
    commands = hit["commands"].strip()

    # 無 exchange_id 或 window_k=0 → 退回單 exchange 行為
    if not exchange_id or window_k <= 0:
        return ("問題：{}\n指令：{}".format(instruction, commands), False)

    neighbors = _fetch_neighbor_exchanges(exchange_id, window_k)
    if not neighbors:
        # 找不到鄰居（可能 hit exchange 已被刪除），fallback
        return ("問題：{}\n指令：{}".format(instruction, commands), False)

    # 找出 hit 在 neighbors 裡的位置，標 ★
    hit_idx = next(
        (n["exchange_idx"] for n in neighbors if n["id"] == exchange_id),
        None,
    )

    lines = [
        f"### 對話片段（session={hit['session_uuid'][:8]}, exchange {neighbors[0]['exchange_idx']}-{neighbors[-1]['exchange_idx']}）"
    ]
    for n in neighbors:
        marker = " ★" if n["exchange_idx"] == hit_idx else ""
        user_p = (n["user_text_preview"] or "").strip()[:preview_chars]
        final_p = (n["final_text_preview"] or "").strip()[:preview_chars]
        lines.append(f"[i={n['exchange_idx']}]{marker}")
        if user_p:
            lines.append(f"  Q: {user_p}")
        if final_p:
            lines.append(f"  A: {final_p}")
    return ("\n".join(lines), True)


def _fetch_neighbor_exchanges(exchange_id: int, window_k: int) -> list[dict]:
    """
    取 hit exchange 周圍 ±window_k 個鄰居（含 hit 本身），按 exchange_idx 升序回傳。
    失敗時回傳空 list（呼叫端會 fallback 單 exchange 行為）。
    """
    try:
        with get_connection() as conn:
            rows = conn.execute(
                """
                WITH hit AS (
                    SELECT branch_id, exchange_idx FROM exchanges WHERE id = ?
                )
                SELECT e.id, e.exchange_idx, e.user_text_preview, e.final_text_preview
                FROM exchanges e
                JOIN hit ON e.branch_id = hit.branch_id
                WHERE e.exchange_idx BETWEEN hit.exchange_idx - ? AND hit.exchange_idx + ?
                ORDER BY e.exchange_idx
                """,
                (exchange_id, window_k, window_k),
            ).fetchall()
    except sqlite3.OperationalError:
        return []

    return [
        {
            "id": r["id"],
            "exchange_idx": r["exchange_idx"],
            "user_text_preview": r["user_text_preview"],
            "final_text_preview": r["final_text_preview"],
        }
        for r in rows
    ]


def retrieve_for_eval(
    query: str,
    project_path: str | None = None,
    top_n: int = 3,
    exclude_session_uuids: set[str] | None = None,
) -> dict:
    """
    評估專用 read-only 召回 API（不動 hot path）。
    回傳結構化三元組供 RAGAS 計算 Context Precision / Recall。

    exclude_session_uuids：leave-one-out 評估用，兩條召回路徑（vector / FTS5）
    都會排除 source session，避免「召回到答案自身來源」灌水。
    """
    vector_results = _vector_search(query, top_n=top_n, exclude_session_uuids=exclude_session_uuids)
    if vector_results:
        return {
            "query": query,
            "source": "vector",
            "retrieved_contexts": [
                "{}\n指令：{}".format(r["instruction"].strip(), r["commands"].strip())
                for r in vector_results
            ],
            "retrieved_session_uuids": list({r["session_uuid"] for r in vector_results}),
        }

    # Fallback：FTS5（同樣套用 leave-one-out 排除）
    sessions = retrieve_relevant_sessions(query=query, project_path=project_path, top_n=top_n)
    if exclude_session_uuids:
        sessions = [s for s in sessions if s.get("session_uuid") not in exclude_session_uuids]
    if not sessions:
        return {"query": query, "source": "fts5", "retrieved_contexts": [], "retrieved_session_uuids": []}

    return {
        "query": query,
        "source": "fts5",
        "retrieved_contexts": [
            "session: {}\n{}".format(s.get("session_uuid", ""), s.get("summary", ""))
            for s in sessions
        ],
        # 保序去重：與 vector 路徑一致（sessions_fts 當前 session 層級已 unique，
        # 此為防禦+一致性，防未來 schema 改 exchange 層級時悄悄 inflate metrics）
        "retrieved_session_uuids": list(dict.fromkeys(s.get("session_uuid", "") for s in sessions)),
    }


def _vector_search(
    query: str,
    top_n: int = 3,
    exclude_session_uuids: set[str] | None = None,
) -> list[dict]:
    """
    向量召回：取得 query embedding → cosine similarity 掃描 exchange_embeddings。
    Ollama 不可用或表為空時回傳空 list。

    exclude_session_uuids：leave-one-out 評估用——排除指定 source session
    （在 top_n 截斷「之前」過濾，避免靜默 under-retrieve）。排除後候選池若空，
    回傳空 list 即可，**不得 fallback 含回 source**——空池本身就是「此答案只能從
    自身來源召回」的 finding，fallback 會遮蔽正在測的東西。
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
                SELECT session_uuid, instruction, commands, embedding, exchange_id
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
                "exchange_id": row["exchange_id"],
            })
        except Exception:
            continue

    scored.sort(key=lambda x: x["score"], reverse=True)
    # leave-one-out：排除 source session 必須在 top_n 截斷「前」，否則會靜默 under-retrieve
    if exclude_session_uuids:
        scored = [r for r in scored if r["session_uuid"] not in exclude_session_uuids]
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
