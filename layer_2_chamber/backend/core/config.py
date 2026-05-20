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


def _run_teachers_vendor_migration(conn: sqlite3.Connection) -> None:
    """
    A 幂等 migration：teachers 新增 vendor 欄位，並 backfill 已知 teacher 的廠牌。
    multi_judge C1 早停會強制 ≥2 vendor，避免 Gemini Flash + Flash-Lite 同源鎖死。
    """
    if _column_exists(conn, "teachers", "vendor"):
        return

    conn.execute(
        "ALTER TABLE teachers ADD COLUMN vendor TEXT NOT NULL DEFAULT 'unknown'"
    )

    # backfill 已知 model_id → vendor 對應；未知值保留 'unknown'，由人工修正
    vendor_map = [
        ("google",   ("gemini-2.5-flash", "gemini-2.5-flash-lite")),
        ("xai",      ("grok-3-mini",)),
        ("openai",   ("gpt-4o-mini",)),
        ("mistral",  ("open-mistral-7b",)),
        ("local",    ("qwen2.5:7b",)),
    ]
    for vendor, model_ids in vendor_map:
        placeholders = ",".join("?" for _ in model_ids)
        conn.execute(
            f"UPDATE teachers SET vendor = ? WHERE model_id IN ({placeholders})",
            (vendor, *model_ids),
        )
    conn.commit()


def _run_finetune_manual_migration(conn: sqlite3.Connection) -> None:
    """
    D 幂等 migration：finetune_runs 新增首次訓練人工把關三欄，
    並以重建表方式把 status CHECK 對齊 runner.py 實際使用的值（含 gate_eval / gate_rejected）。
    """
    if not _table_exists(conn, "finetune_runs"):
        return  # Layer 1 尚未初始化，跳過
    if _column_exists(conn, "finetune_runs", "requires_manual_approval"):
        return  # 已 migration

    # 先用 ADD COLUMN 加三欄（不改 CHECK，用 executescript 重建時一起改）
    for sql in [
        "ALTER TABLE finetune_runs ADD COLUMN requires_manual_approval INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE finetune_runs ADD COLUMN approved_by_human INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE finetune_runs ADD COLUMN approved_at TEXT",
    ]:
        try:
            conn.execute(sql)
        except Exception:
            pass

    # 重建表以更新 status CHECK（加入 pending_manual / gate_eval / gate_rejected）
    conn.executescript("""
        PRAGMA foreign_keys=OFF;

        CREATE TABLE IF NOT EXISTS finetune_runs_d (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            adapter_block INTEGER NOT NULL,
            status        TEXT NOT NULL DEFAULT 'pending'
                            CHECK(status IN (
                                'pending', 'pending_manual',
                                'running', 'gate_eval', 'gate_rejected',
                                'done', 'failed'
                            )),
            dataset_path  TEXT,
            adapter_path  TEXT,
            gguf_path     TEXT,
            ollama_model  TEXT,
            sample_count  INTEGER,
            error_msg     TEXT,
            started_at    TEXT,
            finished_at   TEXT,
            created_at    TEXT NOT NULL DEFAULT (datetime('now')),
            requires_manual_approval INTEGER NOT NULL DEFAULT 0,
            approved_by_human        INTEGER NOT NULL DEFAULT 0,
            approved_at              TEXT
        );

        INSERT INTO finetune_runs_d
            (id, adapter_block, status, dataset_path, adapter_path, gguf_path,
             ollama_model, sample_count, error_msg, started_at, finished_at, created_at,
             requires_manual_approval, approved_by_human, approved_at)
        SELECT
            id, adapter_block,
            CASE status
                WHEN 'pending'       THEN 'pending'
                WHEN 'pending_manual' THEN 'pending_manual'
                WHEN 'running'       THEN 'running'
                WHEN 'gate_eval'     THEN 'gate_eval'
                WHEN 'gate_rejected' THEN 'gate_rejected'
                WHEN 'done'          THEN 'done'
                WHEN 'failed'        THEN 'failed'
                ELSE 'failed'
            END,
            dataset_path, adapter_path, gguf_path,
            ollama_model, sample_count, error_msg, started_at, finished_at, created_at,
            COALESCE(requires_manual_approval, 0),
            COALESCE(approved_by_human, 0),
            approved_at
        FROM finetune_runs;

        DROP TABLE finetune_runs;
        ALTER TABLE finetune_runs_d RENAME TO finetune_runs;

        CREATE INDEX IF NOT EXISTS idx_finetune_runs_block_status
            ON finetune_runs(adapter_block, status, id);

        PRAGMA foreign_keys=ON;
    """)
    conn.commit()


def _run_golden_samples_migration(conn: sqlite3.Connection) -> None:
    """
    C 幂等 migration：建立 golden_samples 表（凍結歷史高分樣本，shadow gate retention 用）。
    schema_layer2.sql 已含 CREATE TABLE IF NOT EXISTS，但既有 DB 不會自動重跑 schema，
    這裡在 init 時保證該表與索引存在。
    """
    if _table_exists(conn, "golden_samples"):
        return

    conn.executescript("""
        CREATE TABLE IF NOT EXISTS golden_samples (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            source_sample_id INTEGER NOT NULL REFERENCES training_samples(id),
            instruction      TEXT NOT NULL,
            input            TEXT NOT NULL DEFAULT '',
            expected_output  TEXT NOT NULL,
            event_type       TEXT NOT NULL,
            score            REAL NOT NULL,
            frozen_at        TEXT NOT NULL DEFAULT (datetime('now')),
            is_active        INTEGER NOT NULL DEFAULT 1
        );
        CREATE INDEX IF NOT EXISTS idx_golden_event ON golden_samples(event_type, is_active);
    """)
    conn.commit()


def _run_rpm_migration(conn: sqlite3.Connection) -> None:
    """
    E 幂等 migration：teachers 新增 RPM 速率限制欄位。

    新欄位：
      rpm_limit            — 每分鐘請求上限（NULL = 不限）
      rpm_window_start     — 當前 60s 窗口起點（ISO8601）
      rpm_count_in_window  — 窗口內已用請求數
      transient_backoff_until — RPM 超限後短暫回退結束時間（NULL = 無回退中）

    backfill：依各廠牌 Paid Tier 上限取 50% buffer 設定 rpm_limit / daily_request_limit。
    （2026-05-20 升級為 Paid Tier；舊 DB 已透過 _run_paid_tier_upgrade_migration 手動 UPDATE）
    """
    if _column_exists(conn, "teachers", "rpm_limit"):
        return  # 已 migration 過

    for sql in [
        "ALTER TABLE teachers ADD COLUMN rpm_limit INTEGER DEFAULT NULL",
        "ALTER TABLE teachers ADD COLUMN rpm_window_start TEXT DEFAULT NULL",
        "ALTER TABLE teachers ADD COLUMN rpm_count_in_window INTEGER DEFAULT 0",
        "ALTER TABLE teachers ADD COLUMN transient_backoff_until TEXT DEFAULT NULL",
    ]:
        conn.execute(sql)

    # Gemini Paid Tier 50% buffer：
    #   Flash      上限 1000 RPM / 10000 RPD → 設 500 / 5000
    #   Flash-Lite 上限 4000 RPM / Unlimited  → 設 2000 / 999999（Unlimited 用大值表示）
    conn.execute(
        "UPDATE teachers SET rpm_limit = 500, daily_request_limit = 5000 "
        "WHERE model_id = 'gemini-2.5-flash'",
    )
    conn.execute(
        "UPDATE teachers SET rpm_limit = 2000, daily_request_limit = 999999 "
        "WHERE model_id = 'gemini-2.5-flash-lite'",
    )
    # Anthropic Tier 1（針對 Sonnet 4.6）：RPM 50；無 RPD 概念（token-based monthly quota），
    # daily_limit / daily_request_limit 統一設極大值表示不適用，等同 Flash-Lite 處理方式。
    conn.execute(
        "UPDATE teachers SET rpm_limit = 50, daily_limit = 999999, daily_request_limit = 999999 "
        "WHERE model_id = 'claude-sonnet-4-6'",
    )
    # local：rpm_limit 保留 NULL（不限）
    # xai：smoke_test_teacher 為 dummy；未來新增實際 Grok teacher 時需補正確值
    #       （Grok 3 Free Tier 約 60 RPM/1200 RPD，於 $25 credits 用盡前）


def _run_router_config_migration(conn: sqlite3.Connection) -> None:
    """幂等 migration：建立 router_config 表並 seed 預設選擇值。

    router_config 儲存「目前各 role 選用哪個 yaml stem」與 Ollama 維護狀態。
    - 每個 key 一列（key/value pattern）
    - ollama_status：'online' | 'offline'（維護模式由此 flag 控制）
    - *_model_yaml：各 role 當前選用的 yaml stem
    初次建立時從 models_loader 取第一個 stem 當預設值（依 stem 字典序）。
    """
    if _table_exists(conn, "router_config"):
        return

    conn.executescript("""
        CREATE TABLE IF NOT EXISTS router_config (
            key         TEXT PRIMARY KEY,           -- e.g. classifier_model_yaml / ollama_status
            value       TEXT NOT NULL,              -- stem 或 status string
            updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
        );
    """)

    # seed 預設值（只在建表時執行一次）
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))
    from models_loader import MODELS

    defaults: list[tuple[str, str]] = [
        ("ollama_status", "online"),
    ]
    role_key_map = {
        "classifier":    "classifier_model_yaml",
        "compressor":    "compressor_model_yaml",
        "responder":     "responder_model_yaml",
        "training_base": "training_base_block1_yaml",
    }
    for role, key in role_key_map.items():
        stems = MODELS.stems_by_role(role)
        if stems:
            defaults.append((key, stems[0]))   # 字典序第一個

    # training_base block2 預設與 block1 同
    block1 = next((v for k, v in defaults if k == "training_base_block1_yaml"), None)
    if block1:
        defaults.append(("training_base_block2_yaml", block1))

    conn.executemany(
        "INSERT OR IGNORE INTO router_config(key, value) VALUES (?, ?)", defaults
    )
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
    回傳已套好全套 PRAGMA 的 connection（由 shiba_db 統一管理）。
    """
    from shiba_db import open_connection
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = open_connection("writer")

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
    # A：teachers.vendor 欄位（廠牌異質性，C1 早停判定用）
    _run_teachers_vendor_migration(conn)
    # C：golden_samples 表（retention 評估，gatekeeper 第 4 條件用）
    _run_golden_samples_migration(conn)
    # D：finetune_runs 首次訓練人工把關欄位 + status CHECK 修正
    _run_finetune_manual_migration(conn)
    # E：teachers RPM 速率欄位 + backfill（區分 RPM 超限 vs 每日配額）
    _run_rpm_migration(conn)
    # F：router_config 模型選擇表 + ollama_status
    _run_router_config_migration(conn)

    return conn


def get_db() -> sqlite3.Connection:
    """FastAPI dependency — 每個 request 取得獨立 connection"""
    conn = init_layer2_db()
    try:
        yield conn
    finally:
        conn.close()
