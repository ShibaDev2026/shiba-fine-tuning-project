"""Layer 2 設定與資料庫初始化

路徑與 URL 統一由 shiba_config.CONFIG 提供，本檔只保留 Layer 2 特有欄位
（精煉器模型參數、Schema 路徑、表清單、migration 等）。
"""
import sqlite3
from pathlib import Path

from shiba_config import CONFIG

# ── 路徑設定（對外維持 DB_PATH 名稱，值來自 CONFIG）────────────────
DB_PATH      = CONFIG.paths.db
SCHEMA_PATH  = Path(__file__).parent.parent / "db" / "schema_layer2.sql"

# ── Qwen 精煉器設定（OLLAMA_BASE_URL 依 runtime 擇一，由 CONFIG 提供）
OLLAMA_BASE_URL     = CONFIG.services.ollama_base_url
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
            source          TEXT NOT NULL CHECK(source IN ('layer1_bridge', 'layer1_bridge_v2', 'error_repair')),
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
            reviewed_at     TEXT,
            weight          REAL NOT NULL DEFAULT 1.0
        );

        INSERT INTO training_samples_new
            (id, source, session_id, question_id, teacher_id, event_type,
             instruction, input, output,
             refined_instruction, expected_answer, pii_scrubbed,
             score, score_reason, status, adapter_block, created_at, reviewed_at, weight)
        SELECT id, source, session_id, question_id, teacher_id, event_type,
               instruction, input, output,
               refined_instruction, expected_answer, pii_scrubbed,
               score, score_reason,
               CASE WHEN status = 'pending' THEN 'pending' ELSE status END,
               adapter_block, created_at, reviewed_at,
               COALESCE(weight, 1.0)
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


def _run_quota_migration(conn: sqlite3.Connection) -> None:
    """幂等 migration：新增配額監控欄位"""
    for sql in [
        "ALTER TABLE teachers ADD COLUMN is_daily_limit_reached INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE teacher_usage_logs ADD COLUMN response_status TEXT",
    ]:
        try:
            conn.execute(sql)
        except Exception:
            pass  # duplicate column name → 已執行過，忽略
    conn.commit()


def _run_token_quota_migration(conn: sqlite3.Connection) -> None:
    """幂等 migration：新增 token 維度配額與今日計數欄位"""
    for sql in [
        # teachers 新欄位
        "ALTER TABLE teachers ADD COLUMN daily_request_limit INTEGER DEFAULT 250",
        "ALTER TABLE teachers ADD COLUMN daily_token_limit INTEGER DEFAULT NULL",
        "ALTER TABLE teachers ADD COLUMN quota_reset_period TEXT DEFAULT 'daily'",
        "ALTER TABLE teachers ADD COLUMN requests_today INTEGER DEFAULT 0",
        "ALTER TABLE teachers ADD COLUMN input_tokens_today INTEGER DEFAULT 0",
        "ALTER TABLE teachers ADD COLUMN output_tokens_today INTEGER DEFAULT 0",
        "ALTER TABLE teachers ADD COLUMN quota_exhausted_at TEXT DEFAULT NULL",
        "ALTER TABLE teachers ADD COLUMN quota_exhausted_type TEXT DEFAULT NULL",
        # teacher_usage_logs 新欄位（保留 tokens_used = input + output 合計）
        "ALTER TABLE teacher_usage_logs ADD COLUMN input_tokens INTEGER DEFAULT 0",
        "ALTER TABLE teacher_usage_logs ADD COLUMN output_tokens INTEGER DEFAULT 0",
    ]:
        try:
            conn.execute(sql)
        except Exception:
            pass  # 欄位已存在，忽略
    conn.commit()


def _run_exchange_ids_migration(conn: sqlite3.Connection) -> None:
    """
    C3 幂等 migration：training_samples 新增 source_exchange_ids（JSON list）。
    既有 layer1_bridge_v2 樣本以「該 session 當下所有乾淨 exchange」backfill，
    讓 dedup 從 session-level 升為 exchange-level，
    保留 SEAL「跳過失敗重試、保留成功 exchange」哲學。
    """
    if _column_exists(conn, "training_samples", "source_exchange_ids"):
        return  # 已 migration 過

    conn.execute(
        "ALTER TABLE training_samples ADD COLUMN source_exchange_ids TEXT"
    )

    # 僅 backfill v2 樣本；舊版 layer1_bridge / error_repair 不適用 exchange-level
    rows = conn.execute(
        "SELECT id, session_id FROM training_samples "
        "WHERE source = 'layer1_bridge_v2' AND session_id IS NOT NULL"
    ).fetchall()
    if rows and _table_exists(conn, "exchanges"):
        import json as _json
        for row in rows:
            ex_ids = [
                r[0] for r in conn.execute(
                    "SELECT e.id FROM exchanges e "
                    "JOIN sessions s ON s.id = e.session_id "
                    "WHERE s.uuid = ? "
                    "  AND e.has_error = 0 "
                    "  AND e.has_final_text = 1 "
                    "  AND e.status = 'completed'",
                    (row["session_id"],),
                ).fetchall()
            ]
            conn.execute(
                "UPDATE training_samples SET source_exchange_ids = ? WHERE id = ?",
                (_json.dumps(ex_ids), row["id"]),
            )
    conn.commit()


def _run_keychain_nullable_migration(conn: sqlite3.Connection) -> None:
    """
    C6 幂等 migration：teachers.keychain_ref NOT NULL → nullable（支援本地 Ollama teacher）。
    SQLite 不支援 ALTER COLUMN DROP NOT NULL，需用重建表格的方式。
    """
    info = conn.execute("PRAGMA table_info(teachers)").fetchall()
    keychain_col = next((r for r in info if r[1] == "keychain_ref"), None)
    if keychain_col is None or keychain_col[3] == 0:
        return  # 欄位不存在或已是 nullable，跳過

    conn.executescript("""
        PRAGMA foreign_keys=OFF;

        CREATE TABLE IF NOT EXISTS teachers_c6 (
            id                      INTEGER PRIMARY KEY AUTOINCREMENT,
            name                    TEXT NOT NULL UNIQUE,
            model_id                TEXT NOT NULL,
            api_base                TEXT NOT NULL,
            keychain_ref            TEXT,
            priority                INTEGER NOT NULL DEFAULT 0,
            daily_limit             INTEGER NOT NULL DEFAULT 250,
            is_active               INTEGER NOT NULL DEFAULT 1,
            is_daily_limit_reached  INTEGER NOT NULL DEFAULT 0,
            created_at              TEXT NOT NULL DEFAULT (datetime('now')),
            daily_request_limit     INTEGER DEFAULT 250,
            daily_token_limit       INTEGER DEFAULT NULL,
            quota_reset_period      TEXT DEFAULT 'daily',
            requests_today          INTEGER DEFAULT 0,
            input_tokens_today      INTEGER DEFAULT 0,
            output_tokens_today     INTEGER DEFAULT 0,
            quota_exhausted_at      TEXT DEFAULT NULL,
            quota_exhausted_type    TEXT DEFAULT NULL
        );

        INSERT INTO teachers_c6
            (id, name, model_id, api_base, keychain_ref, priority, daily_limit,
             is_active, is_daily_limit_reached, created_at,
             daily_request_limit, daily_token_limit, quota_reset_period,
             requests_today, input_tokens_today, output_tokens_today,
             quota_exhausted_at, quota_exhausted_type)
        SELECT
            id, name, model_id, api_base, keychain_ref, priority, daily_limit,
            is_active, is_daily_limit_reached, created_at,
            COALESCE(daily_request_limit, daily_limit),
            daily_token_limit,
            COALESCE(quota_reset_period, 'daily'),
            COALESCE(requests_today, 0),
            COALESCE(input_tokens_today, 0),
            COALESCE(output_tokens_today, 0),
            quota_exhausted_at, quota_exhausted_type
        FROM teachers;

        DROP TABLE teachers;
        ALTER TABLE teachers_c6 RENAME TO teachers;

        PRAGMA foreign_keys=ON;
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
    # C5：timeout=30s，避免多排程併發 + Layer 1 hook 同時寫入時 lock contention
    conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=30.0)
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
    # 配額監控欄位 migration（幂等）
    _run_quota_migration(conn)
    # Token 維度配額 migration（幂等）
    _run_token_quota_migration(conn)
    # C6：keychain_ref NOT NULL → nullable（支援本地 Ollama teacher）
    _run_keychain_nullable_migration(conn)
    # C3：source_exchange_ids 欄位（exchange-level dedup）
    _run_exchange_ids_migration(conn)

    return conn


def get_db() -> sqlite3.Connection:
    """FastAPI dependency — 每個 request 取得獨立 connection"""
    conn = init_layer2_db()
    try:
        yield conn
    finally:
        conn.close()
