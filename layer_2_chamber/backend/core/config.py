"""Layer 2 設定與資料庫初始化"""
import sqlite3
from pathlib import Path

# ── 路徑設定 ─────────────────────────────────────────────────────────
DB_PATH      = Path.home() / ".local-brain" / "shiba-brain.db"
SCHEMA_PATH  = Path(__file__).parent.parent / "db" / "schema_layer2.sql"

# ── Qwen 精煉器設定 ──────────────────────────────────────────────────
OLLAMA_BASE_URL     = "http://localhost:11434"
REFINER_MODEL       = "qwen3.6:35b-a3b-nvfp4"
REFINER_BATCH_LIMIT = 10
REFINER_TIMEOUT     = 120  # seconds

# think:false 關閉 thinking 模式（速度提升 30x）；num_ctx 節省記憶體
REFINER_OPTIONS = {
    "think": False,
    "num_ctx": 4096,
}

# ── Layer 2 五張表（用於 migration 檢查）────────────────────────────
LAYER2_TABLES = [
    "teachers",
    "question_sets",
    "questions",
    "training_samples",
    "teacher_usage_logs",
]


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    """檢查欄位是否已存在"""
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(r["name"] == column for r in rows)


def _run_refiner_migration(conn: sqlite3.Connection) -> None:
    """
    幂等 migration：新增 refined_instruction / expected_answer / pii_scrubbed，
    並更新 status CHECK constraint 加入 'raw'（需做 table rename dance）。
    """
    needs_new_cols = not _column_exists(conn, "training_samples", "pii_scrubbed")
    needs_status_fix = not _column_exists(conn, "training_samples", "pii_scrubbed")  # 同步判斷

    if not needs_new_cols:
        return  # 已 migration 過，跳過

    # Step 1：新增欄位（ADD COLUMN 幂等）
    for col_sql in [
        "ALTER TABLE training_samples ADD COLUMN refined_instruction TEXT",
        "ALTER TABLE training_samples ADD COLUMN expected_answer TEXT",
        "ALTER TABLE training_samples ADD COLUMN pii_scrubbed INTEGER NOT NULL DEFAULT 0",
    ]:
        try:
            conn.execute(col_sql)
        except Exception:
            pass  # 欄位已存在時 SQLite 會報錯，忽略

    # Step 2：重建 training_samples 以更新 status CHECK（加入 'raw'）
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS training_samples_new (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            source          TEXT NOT NULL CHECK(source IN ('layer1_bridge', 'error_repair')),
            session_id      TEXT,
            question_id     INTEGER REFERENCES questions(id),
            teacher_id      INTEGER REFERENCES teachers(id),
            event_type      TEXT NOT NULL,
            instruction     TEXT NOT NULL,
            input           TEXT NOT NULL DEFAULT '',
            output          TEXT NOT NULL,
            refined_instruction TEXT,
            expected_answer TEXT,
            pii_scrubbed    INTEGER NOT NULL DEFAULT 0,
            score           REAL,
            score_reason    TEXT,
            status          TEXT NOT NULL DEFAULT 'raw'
                                CHECK(status IN ('raw','pending','approved','rejected','needs_review')),
            adapter_block   INTEGER,
            created_at      TEXT NOT NULL DEFAULT (datetime('now')),
            reviewed_at     TEXT
        );

        INSERT INTO training_samples_new
            (id, source, session_id, question_id, teacher_id, event_type,
             instruction, input, output,
             refined_instruction, expected_answer, pii_scrubbed,
             score, score_reason, status, adapter_block, created_at, reviewed_at)
        SELECT id, source, session_id, question_id, teacher_id, event_type,
               instruction, input, output,
               refined_instruction, expected_answer, pii_scrubbed,
               score, score_reason,
               CASE WHEN status = 'pending' THEN 'pending' ELSE status END,
               adapter_block, created_at, reviewed_at
        FROM training_samples;

        DROP TABLE training_samples;
        ALTER TABLE training_samples_new RENAME TO training_samples;

        CREATE INDEX IF NOT EXISTS idx_training_samples_status
            ON training_samples(status);
        CREATE INDEX IF NOT EXISTS idx_training_samples_event_type
            ON training_samples(event_type);
        CREATE INDEX IF NOT EXISTS idx_training_samples_adapter
            ON training_samples(adapter_block);
    """)
    conn.commit()


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

    # 精煉器欄位 migration（幂等）
    _run_refiner_migration(conn)

    return conn


def get_db() -> sqlite3.Connection:
    """FastAPI dependency — 每個 request 取得獨立 connection"""
    conn = init_layer2_db()
    try:
        yield conn
    finally:
        conn.close()
