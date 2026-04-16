"""Layer 2 設定與資料庫初始化"""
import sqlite3
from pathlib import Path

# ── 路徑設定 ─────────────────────────────────────────────────────────
DB_PATH      = Path.home() / ".local-brain" / "shiba-brain.db"
SCHEMA_PATH  = Path(__file__).parent.parent / "db" / "schema_layer2.sql"

# ── Layer 2 五張表（用於 migration 檢查）────────────────────────────
LAYER2_TABLES = [
    "teachers",
    "question_sets",
    "questions",
    "training_samples",
    "teacher_usage_logs",
]


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    """檢查資料表是否存在"""
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    return row is not None


def init_layer2_db() -> sqlite3.Connection:
    """
    開啟 shiba-brain.db 並確保 Layer 2 schema 已建立。
    使用 PRAGMA table_info 判斷是否需要執行 migration。
    回傳已啟用 WAL + foreign_keys 的 connection。
    """
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    # WAL 模式減少 Layer 1 hook 與 Layer 2 API 的寫入競爭
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")

    # 判斷是否所有 Layer 2 表都已存在
    missing = [t for t in LAYER2_TABLES if not _table_exists(conn, t)]
    if missing:
        schema_sql = SCHEMA_PATH.read_text(encoding="utf-8")
        conn.executescript(schema_sql)
        conn.commit()

    return conn


def get_db() -> sqlite3.Connection:
    """FastAPI dependency — 每個 request 取得獨立 connection"""
    conn = init_layer2_db()
    try:
        yield conn
    finally:
        conn.close()
