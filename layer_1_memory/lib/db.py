"""
db.py — SQLite 連線管理、WAL 設定、init_db、基本 CRUD
支援舊版 DB 自動 migration（PRAGMA table_info 檢查欄位後再 ALTER）
"""

import json
import logging
import sqlite3
import zlib
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import yaml

# 設定 logger
logger = logging.getLogger(__name__)

# 讀取設定檔（config.yaml 同層上兩層）
_CONFIG_PATH = Path(__file__).parent.parent / "config.yaml"


def _load_config() -> dict:
    """讀取 config.yaml，取得 DB 路徑等設定"""
    with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def get_db_path() -> Path:
    """從 config.yaml 取得 DB 絕對路徑"""
    cfg = _load_config()
    path = Path(cfg["db"]["path"]).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


@contextmanager
def get_connection():
    """
    取得 SQLite 連線（context manager）。
    自動啟用 WAL 模式與 foreign_keys，離開時自動關閉。
    """
    db_path = get_db_path()
    conn = sqlite3.connect(str(db_path), timeout=10)
    conn.row_factory = sqlite3.Row  # 讓查詢結果可用欄位名稱存取
    try:
        # WAL 模式：允許多讀一寫，防止 Hook / FastAPI 並發衝突
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA busy_timeout=5000;")
        conn.execute("PRAGMA foreign_keys=ON;")
        yield conn
    finally:
        conn.close()


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    """檢查指定資料表是否已有某欄位（用於 migration 前判斷）"""
    rows = conn.execute(f"PRAGMA table_info({table});").fetchall()
    return any(row["name"] == column for row in rows)


def compress_text(text: str | None) -> tuple[bytes | str | None, int]:
    """若文字的位元組長度大於 1024 Bytes，則套用 zlib 壓縮返回 (BLOB, 1)，否則返回 (TEXT, 0)。"""
    if not text:
        return text, 0
    encoded = text.encode("utf-8")
    if len(encoded) > 1024:
        return zlib.compress(encoded), 1
    return text, 0


def init_db() -> None:
    """
    初始化 DB：執行 schema.sql，並對舊版 DB 執行 migration。
    SQLite 不支援 ALTER TABLE ADD COLUMN IF NOT EXISTS，
    因此透過 PRAGMA table_info 先確認欄位是否存在。
    """
    schema_path = Path(__file__).parent.parent / "db" / "schema.sql"
    schema_sql = schema_path.read_text(encoding="utf-8")

    with get_connection() as conn:
        # 執行完整 schema（CREATE TABLE IF NOT EXISTS 安全重複執行）
        conn.executescript(schema_sql)

        # Migration：對舊版 branches 表補上 decay 欄位
        decay_columns = [
            ("last_accessed", "TEXT"),
            ("access_count",  "INTEGER DEFAULT 0"),
            ("decay_score",   "REAL DEFAULT 1.0"),
        ]
        for col_name, col_def in decay_columns:
            if not _column_exists(conn, "branches", col_name):
                conn.execute(
                    f"ALTER TABLE branches ADD COLUMN {col_name} {col_def};"
                )
                logger.info("Migration: branches 表新增欄位 %s", col_name)

        if not _column_exists(conn, "messages", "raw_content"):
            conn.execute("ALTER TABLE messages ADD COLUMN raw_content TEXT;")
            logger.info("Migration: messages 表新增欄位 raw_content")

        new_msg_columns = [
            ("input_tokens", "INTEGER DEFAULT 0"),
            ("output_tokens", "INTEGER DEFAULT 0"),
            ("cache_creation_input_tokens", "INTEGER DEFAULT 0"),
            ("cache_read_input_tokens", "INTEGER DEFAULT 0"),
            ("char_count", "INTEGER DEFAULT 0"),
            ("byte_count", "INTEGER DEFAULT 0"),
            ("encoding", "TEXT DEFAULT 'utf-8'"),
            ("is_compressed", "INTEGER DEFAULT 0"),
            ("message_time", "TEXT"),
            ("model_name", "TEXT"),
        ]
        for col_name, col_def in new_msg_columns:
            if not _column_exists(conn, "messages", col_name):
                conn.execute(f"ALTER TABLE messages ADD COLUMN {col_name} {col_def};")
                logger.info("Migration: messages 表新增欄位 %s", col_name)

        conn.commit()
        logger.info("DB 初始化完成：%s", get_db_path())


# ============================================================
# Project CRUD
# ============================================================

def upsert_project(conn: sqlite3.Connection, name: str, path: str, hash_: str) -> int:
    """
    新增或更新 project 記錄，回傳 project.id。
    若 hash 已存在則直接回傳 id，不修改現有資料。
    """
    row = conn.execute(
        "SELECT id FROM projects WHERE hash = ?", (hash_,)
    ).fetchone()
    if row:
        return row["id"]

    cur = conn.execute(
        "INSERT INTO projects (name, path, hash) VALUES (?, ?, ?)",
        (name, path, hash_),
    )
    conn.commit()
    return cur.lastrowid


# ============================================================
# Session CRUD
# ============================================================

def upsert_session(
    conn: sqlite3.Connection,
    project_id: int,
    uuid: str,
    started_at: str | None = None,
) -> int:
    """
    新增或取得 session 記錄，回傳 session.id。
    若 UUID 已存在則直接回傳 id。
    """
    row = conn.execute(
        "SELECT id FROM sessions WHERE uuid = ?", (uuid,)
    ).fetchone()
    if row:
        return row["id"]

    cur = conn.execute(
        """INSERT INTO sessions (project_id, uuid, started_at)
           VALUES (?, ?, COALESCE(?, datetime('now')))""",
        (project_id, uuid, started_at),
    )
    conn.commit()
    return cur.lastrowid


def update_session_stats(
    conn: sqlite3.Connection,
    session_id: int,
    exchange_count: int,
    files_modified: int,
    commits: int,
    tool_counts: dict,
    event_types: list[str],
    ended_at: str | None = None,
) -> None:
    """更新 session 統計摘要欄位"""
    conn.execute(
        """UPDATE sessions
           SET exchange_count = ?,
               files_modified = ?,
               commits        = ?,
               tool_counts    = ?,
               event_types    = ?,
               ended_at       = COALESCE(?, datetime('now'))
           WHERE id = ?""",
        (
            exchange_count,
            files_modified,
            commits,
            json.dumps(tool_counts, ensure_ascii=False),
            json.dumps(event_types, ensure_ascii=False),
            ended_at,
            session_id,
        ),
    )
    conn.commit()


# ============================================================
# Branch CRUD
# ============================================================

def upsert_branch(
    conn: sqlite3.Connection,
    session_id: int,
    branch_idx: int,
    is_active: bool,
    leaf_uuid: str | None,
    exchange_count: int,
    files_modified: int,
    commits: int,
) -> int:
    """新增或更新 branch 記錄，回傳 branch.id"""
    row = conn.execute(
        "SELECT id FROM branches WHERE session_id = ? AND branch_idx = ?",
        (session_id, branch_idx),
    ).fetchone()

    if row:
        conn.execute(
            """UPDATE branches
               SET is_active = ?, leaf_uuid = ?,
                   exchange_count = ?, files_modified = ?,
                   commits = ?, ended_at = datetime('now')
               WHERE id = ?""",
            (
                1 if is_active else 0,
                leaf_uuid,
                exchange_count,
                files_modified,
                commits,
                row["id"],
            ),
        )
        conn.commit()
        return row["id"]

    cur = conn.execute(
        """INSERT INTO branches
           (session_id, branch_idx, is_active, leaf_uuid,
            exchange_count, files_modified, commits, ended_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))""",
        (
            session_id,
            branch_idx,
            1 if is_active else 0,
            leaf_uuid,
            exchange_count,
            files_modified,
            commits,
        ),
    )
    conn.commit()
    return cur.lastrowid


def deactivate_old_branches(conn: sqlite3.Connection, session_id: int) -> None:
    """將同一 session 的所有舊分支標為非活躍（rewind 時使用）"""
    conn.execute(
        "UPDATE branches SET is_active = 0 WHERE session_id = ?",
        (session_id,),
    )
    conn.commit()


# ============================================================
# Message CRUD
# ============================================================

def insert_message(
    conn: sqlite3.Connection,
    session_id: int,
    uuid: str,
    parent_uuid: str | None,
    role: str,
    content: str | None,
    raw_content: str | None,
    input_tokens: int,
    output_tokens: int,
    cache_creation_input_tokens: int,
    cache_read_input_tokens: int,
    char_count: int,
    byte_count: int,
    encoding: str,
    has_tool_use: bool,
    tool_names: list[str],
    message_time: str | None = None,
    model_name: str | None = None,
) -> int:
    """新增訊息記錄（UUID 已存在則忽略），回傳 message.id。若字串超過 1024 即自動壓為 BLOB。"""
    row = conn.execute(
        "SELECT id FROM messages WHERE uuid = ?", (uuid,)
    ).fetchone()
    if row:
        return row["id"]

    compressed_raw, is_raw_comp = compress_text(raw_content)

    cur = conn.execute(
        """INSERT INTO messages
           (session_id, uuid, parent_uuid, role, content, raw_content, 
            input_tokens, output_tokens, cache_creation_input_tokens, cache_read_input_tokens, 
            char_count, byte_count, encoding, has_tool_use, tool_names, is_compressed, message_time, model_name)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            session_id,
            uuid,
            parent_uuid,
            role,
            content,
            compressed_raw,
            input_tokens,
            output_tokens,
            cache_creation_input_tokens,
            cache_read_input_tokens,
            char_count,
            byte_count,
            encoding,
            1 if has_tool_use else 0,
            json.dumps(tool_names, ensure_ascii=False),
            is_raw_comp,
            message_time,
            model_name,
        ),
    )
    conn.commit()
    return cur.lastrowid


def insert_branch_message(
    conn: sqlite3.Connection, branch_id: int, message_id: int, seq: int
) -> None:
    """建立 branch-message 橋接關係（已存在則忽略）"""
    conn.execute(
        """INSERT OR IGNORE INTO branch_messages (branch_id, message_id, seq)
           VALUES (?, ?, ?)""",
        (branch_id, message_id, seq),
    )
    conn.commit()


def insert_tool_execution(
    conn: sqlite3.Connection,
    message_id: int,
    tool_use_id: str,
    tool_name: str,
    input_cmd: str | None,
    output_log: str | None,
    is_error: bool,
    duration_ms: int | None = None,
) -> int:
    """寫入分離出來的 tool execution，並套用自動壓縮。"""
    compressed_out, is_comp = compress_text(output_log)
    cur = conn.execute(
        """INSERT OR IGNORE INTO tool_executions
           (message_id, tool_use_id, tool_name, input_cmd, output_log, is_error, is_compressed, duration_ms)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            message_id,
            tool_use_id,
            tool_name,
            input_cmd,
            compressed_out,
            1 if is_error else 0,
            is_comp,
            duration_ms,
        ),
    )
    conn.commit()
    return cur.lastrowid



# ============================================================
# FTS5 CRUD
# ============================================================

def upsert_sessions_fts(
    conn: sqlite3.Connection,
    session_uuid: str,
    project_path: str,
    event_types: list[str],
    content_summary: str,
    files_list: str,
    ended_at: str,
) -> None:
    """
    更新 FTS5 全文索引。
    FTS5 不支援 UPDATE，採用 DELETE + INSERT 方式。
    """
    conn.execute(
        "DELETE FROM sessions_fts WHERE session_uuid = ?", (session_uuid,)
    )
    conn.execute(
        """INSERT INTO sessions_fts
           (session_uuid, project_path, event_types,
            content_summary, files_list, ended_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (
            session_uuid,
            project_path,
            " ".join(event_types),  # FTS5 以空格分詞
            content_summary,
            files_list,
            ended_at,
        ),
    )
    conn.commit()
