"""AI API 呼叫歷程共用記錄器。

所有透過 clients/ 子模組（Gemini / 未來 Anthropic / OpenAI）發出的 AI 呼叫
都會在此寫入 `ai_api_call_logs` 表，無論成功或失敗。

為什麼集中在這：呼叫端只關心業務邏輯，歷程記錄由共用層自動處理；
未來分析 / 對帳 / 配額追蹤都從這張表出。
"""

from __future__ import annotations

import logging
import sqlite3
import sys
from pathlib import Path

# 為了能 import 既有 get_connection（統一 SQLite 路徑，避免雙連線管理）
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from layer_1_memory.lib.db import get_connection  # noqa: E402

logger = logging.getLogger(__name__)

# ── Schema（CREATE TABLE IF NOT EXISTS，雙保險：手動 migration + 程式自動建立）─
_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS ai_api_call_logs (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,

    -- 廠商與路由
    vendor                TEXT NOT NULL,
    api_base              TEXT NOT NULL,
    model_id              TEXT NOT NULL,

    -- 請求/回應內容（全存，便於 debug）
    request_text          TEXT NOT NULL,
    response_text         TEXT,
    request_char_len      INTEGER NOT NULL,
    response_char_len     INTEGER,

    -- Token 計量
    input_tokens          INTEGER DEFAULT 0,
    output_tokens         INTEGER DEFAULT 0,

    -- 結果
    http_status           INTEGER,
    status                TEXT NOT NULL,
    error_category        TEXT,
    error_message         TEXT,

    -- 時間（UTC ISO8601，毫秒精度）
    request_sent_at       TEXT NOT NULL,
    response_received_at  TEXT,
    latency_ms            INTEGER,

    -- 業務關聯
    caller_module         TEXT,
    teacher_id            INTEGER,
    sample_id             INTEGER,

    created_at            TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

_INDEXES_SQL = [
    "CREATE INDEX IF NOT EXISTS idx_ai_logs_vendor_model ON ai_api_call_logs(vendor, model_id)",
    "CREATE INDEX IF NOT EXISTS idx_ai_logs_created_at   ON ai_api_call_logs(created_at)",
    "CREATE INDEX IF NOT EXISTS idx_ai_logs_status       ON ai_api_call_logs(status)",
    "CREATE INDEX IF NOT EXISTS idx_ai_logs_caller       ON ai_api_call_logs(caller_module)",
]

_schema_ready = False


def _ensure_schema(conn: sqlite3.Connection) -> None:
    """確保表與索引存在（process 內只跑一次）"""
    global _schema_ready
    if _schema_ready:
        return
    conn.executescript(_SCHEMA_SQL)
    for sql in _INDEXES_SQL:
        conn.execute(sql)
    conn.commit()
    _schema_ready = True


def log_api_call(
    *,
    vendor: str,
    api_base: str,
    model_id: str,
    request_text: str,
    response_text: str | None,
    input_tokens: int,
    output_tokens: int,
    http_status: int | None,
    status: str,
    error_category: str | None,
    error_message: str | None,
    request_sent_at: str,
    response_received_at: str | None,
    latency_ms: int | None,
    caller_module: str | None = None,
    teacher_id: int | None = None,
    sample_id: int | None = None,
) -> int | None:
    """寫入一筆 AI API 呼叫歷程。

    失敗時僅 log warning，不拋例外（避免 log 寫失敗影響主流程）。
    回傳新增列的 id（失敗 None）。
    """
    request_char_len = len(request_text)
    response_char_len = len(response_text) if response_text is not None else None

    try:
        with get_connection() as conn:
            _ensure_schema(conn)
            cursor = conn.execute(
                """
                INSERT INTO ai_api_call_logs (
                    vendor, api_base, model_id,
                    request_text, response_text, request_char_len, response_char_len,
                    input_tokens, output_tokens,
                    http_status, status, error_category, error_message,
                    request_sent_at, response_received_at, latency_ms,
                    caller_module, teacher_id, sample_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    vendor, api_base, model_id,
                    request_text, response_text, request_char_len, response_char_len,
                    input_tokens, output_tokens,
                    http_status, status, error_category, error_message,
                    request_sent_at, response_received_at, latency_ms,
                    caller_module, teacher_id, sample_id,
                ),
            )
            conn.commit()
            return cursor.lastrowid
    except Exception as e:
        # 寫 log 失敗不影響主流程：僅警告
        logger.warning(
            "ai_api_call_logs 寫入失敗 vendor=%s model=%s status=%s: %s",
            vendor, model_id, status, e,
        )
        return None
