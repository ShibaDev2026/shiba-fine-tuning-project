-- ============================================================
-- shiba-brain.db — 核心 Schema（PR-O-1 立案，雙寫並存階段）
--
-- 本檔為「核心 phase 0-3」的唯一 schema source of truth；
-- feature 模組專屬表移至 modules/<topic>/db/<topic>.sql，
-- 由 core.feature_registry.apply_features 在對應 flag=true 時套用。
--
-- 強約束（驗收標準 §11.2）：
--   - 本檔內任何 FK 不得指向 modules/ 任何 schema 的表
--   - feature 表名（gatekeeper_*, ragas_*, multi_judge_v2_*, paraphrase_*）
--     一律不得出現在本檔
--
-- PR-O-1 階段：本檔僅供新建 DB 使用，舊 schema 檔（layer_1_memory/db/schema.sql、
-- layer_2_chamber/backend/db/schema_layer2.sql）仍由各 layer 自行載入，雙寫並存；
-- 待 PR-O-2 ~ -9 逐步遷移後，舊檔將在 PR-O-9 刪除。
-- ============================================================

-- ============================================================
-- Layer 1：四層記憶結構（projects → sessions → branches → messages）
-- ============================================================

CREATE TABLE IF NOT EXISTS projects (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    path        TEXT NOT NULL UNIQUE,
    hash        TEXT NOT NULL UNIQUE,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS sessions (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id       INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    uuid             TEXT NOT NULL UNIQUE,
    started_at       TEXT NOT NULL DEFAULT (datetime('now')),
    ended_at         TEXT,
    exchange_count   INTEGER DEFAULT 0,
    files_modified   INTEGER DEFAULT 0,
    commits          INTEGER DEFAULT 0,
    tool_counts      TEXT DEFAULT '{}',
    event_types      TEXT DEFAULT '[]',
    context_summary  TEXT
);

CREATE TABLE IF NOT EXISTS branches (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    branch_idx      INTEGER NOT NULL DEFAULT 0,
    is_active       INTEGER NOT NULL DEFAULT 1,
    leaf_uuid       TEXT,
    exchange_count  INTEGER DEFAULT 0,
    files_modified  INTEGER DEFAULT 0,
    commits         INTEGER DEFAULT 0,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    ended_at        TEXT,
    last_accessed   TEXT,
    access_count    INTEGER DEFAULT 0,
    decay_score     REAL DEFAULT 1.0,
    UNIQUE(session_id, branch_idx)
);

CREATE TABLE IF NOT EXISTS messages (
    id                          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id                  INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    uuid                        TEXT NOT NULL UNIQUE,
    parent_uuid                 TEXT,
    role                        TEXT NOT NULL,
    content                     TEXT,
    raw_content                 TEXT,
    input_tokens                INTEGER DEFAULT 0,
    output_tokens               INTEGER DEFAULT 0,
    cache_creation_input_tokens INTEGER DEFAULT 0,
    cache_read_input_tokens     INTEGER DEFAULT 0,
    char_count                  INTEGER DEFAULT 0,
    byte_count                  INTEGER DEFAULT 0,
    encoding                    TEXT DEFAULT 'utf-8',
    is_compressed               INTEGER DEFAULT 0,
    message_time                TEXT,
    model_name                  TEXT,
    has_tool_use                INTEGER DEFAULT 0,
    tool_names                  TEXT DEFAULT '[]',
    created_at                  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS tool_executions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id    INTEGER NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
    tool_use_id   TEXT NOT NULL,
    tool_name     TEXT NOT NULL,
    input_cmd     TEXT,
    output_log    BLOB,
    is_error      INTEGER DEFAULT 0,
    is_compressed INTEGER DEFAULT 0,
    duration_ms   INTEGER,
    UNIQUE(message_id, tool_use_id)
);

CREATE TABLE IF NOT EXISTS branch_messages (
    branch_id   INTEGER NOT NULL REFERENCES branches(id) ON DELETE CASCADE,
    message_id  INTEGER NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
    seq         INTEGER NOT NULL,
    PRIMARY KEY (branch_id, message_id)
);

-- ============================================================
-- Exchanges 語意層（衍生自 messages + tool_executions）
-- ============================================================

CREATE TABLE IF NOT EXISTS exchanges (
    id                          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id                  INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    branch_id                   INTEGER NOT NULL REFERENCES branches(id) ON DELETE CASCADE,
    exchange_idx                INTEGER NOT NULL,
    user_message_id             INTEGER NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
    final_assistant_message_id  INTEGER REFERENCES messages(id) ON DELETE SET NULL,
    message_count               INTEGER NOT NULL DEFAULT 0,
    assistant_message_count     INTEGER NOT NULL DEFAULT 0,
    tool_round_count            INTEGER NOT NULL DEFAULT 0,
    tool_use_count              INTEGER NOT NULL DEFAULT 0,
    has_tool_use                INTEGER NOT NULL DEFAULT 0,
    has_error                   INTEGER NOT NULL DEFAULT 0,
    has_final_text              INTEGER NOT NULL DEFAULT 0,
    tool_names                  TEXT NOT NULL DEFAULT '[]',
    user_text_preview           TEXT,
    final_text_preview          TEXT,
    status                      TEXT NOT NULL DEFAULT 'completed'
        CHECK(status IN ('in_progress', 'completed', 'abandoned')),
    started_at                  TEXT NOT NULL,
    ended_at                    TEXT,
    created_at                  TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(branch_id, exchange_idx)
);

CREATE INDEX IF NOT EXISTS idx_exchanges_session   ON exchanges(session_id);
CREATE INDEX IF NOT EXISTS idx_exchanges_branch    ON exchanges(branch_id, exchange_idx);
CREATE INDEX IF NOT EXISTS idx_exchanges_user_msg  ON exchanges(user_message_id);
CREATE INDEX IF NOT EXISTS idx_exchanges_final_msg ON exchanges(final_assistant_message_id);
CREATE INDEX IF NOT EXISTS idx_exchanges_status    ON exchanges(status);
CREATE INDEX IF NOT EXISTS idx_exchanges_filter    ON exchanges(session_id, status, has_tool_use, has_error);

CREATE TABLE IF NOT EXISTS exchange_messages (
    exchange_id      INTEGER NOT NULL REFERENCES exchanges(id) ON DELETE CASCADE,
    message_id       INTEGER NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
    seq              INTEGER NOT NULL,
    role_in_exchange TEXT NOT NULL,
    PRIMARY KEY (exchange_id, message_id)
);

CREATE INDEX IF NOT EXISTS idx_exchange_messages_msg ON exchange_messages(message_id);
CREATE INDEX IF NOT EXISTS idx_exchange_messages_seq ON exchange_messages(exchange_id, seq);

-- ============================================================
-- FTS5 全文索引
-- ============================================================

CREATE VIRTUAL TABLE IF NOT EXISTS sessions_fts USING fts5(
    session_uuid,
    project_path,
    event_types,
    content_summary,
    files_list,
    ended_at,
    tokenize="trigram"
);

-- ============================================================
-- Embedding 表（語意向量召回，核心能力）
-- 註（PR-O-7）：source_instruction 欄位留在核心 exchange_embeddings —
--   原始 embedding 寫入時也用此欄位（NULL=原始；非 NULL=paraphrase 變體），
--   feature 拆出的是「生成 paraphrase 的服務」而非欄位本身。
--   feature off 時 background 排程不註冊 paraphrase hook → tick noop。
-- ============================================================

CREATE TABLE IF NOT EXISTS exchange_embeddings (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    session_uuid       TEXT NOT NULL,
    instruction        TEXT NOT NULL,
    source_instruction TEXT,
    commands           TEXT NOT NULL,
    embedding          BLOB NOT NULL,
    model              TEXT NOT NULL DEFAULT 'bge-m3',
    exchange_id        INTEGER REFERENCES exchanges(id),
    created_at         TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_exchange_embeddings_session  ON exchange_embeddings(session_uuid);
CREATE INDEX IF NOT EXISTS idx_exchange_embeddings_exchange ON exchange_embeddings(exchange_id);

-- ============================================================
-- 索引：sessions / branches / messages / projects / tool_executions
-- ============================================================

CREATE INDEX IF NOT EXISTS idx_sessions_project    ON sessions(project_id);
CREATE INDEX IF NOT EXISTS idx_sessions_uuid       ON sessions(uuid);
CREATE INDEX IF NOT EXISTS idx_branches_session    ON branches(session_id);
CREATE INDEX IF NOT EXISTS idx_branches_active     ON branches(session_id, is_active);
CREATE INDEX IF NOT EXISTS idx_messages_session    ON messages(session_id);
CREATE INDEX IF NOT EXISTS idx_messages_uuid       ON messages(uuid);
CREATE INDEX IF NOT EXISTS idx_messages_parent     ON messages(parent_uuid);
CREATE INDEX IF NOT EXISTS idx_projects_hash       ON projects(hash);
CREATE INDEX IF NOT EXISTS idx_tool_executions_msg ON tool_executions(message_id);
CREATE INDEX IF NOT EXISTS idx_tool_executions_err ON tool_executions(tool_name, is_error);

-- ============================================================
-- Layer 0 / Layer 3 共用核心表
-- ============================================================

-- Layer 0 路由決策遙測（router_config 由 schema_model_registry.sql 之外的
-- backend 啟動流程動態建立；本檔不重複建以免雙重 DDL）
CREATE TABLE IF NOT EXISTS router_decisions (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id        TEXT,
    prompt_hash       TEXT NOT NULL,
    classification    TEXT NOT NULL,
    reason            TEXT,
    local_output      TEXT,
    user_accepted     INTEGER,
    user_rewrote      INTEGER DEFAULT 0,
    acceptance_source TEXT,
    latency_ms        INTEGER,
    tokens_prompt     INTEGER,
    tokens_response   INTEGER,
    created_at        TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_router_decisions_session   ON router_decisions(session_id);
CREATE INDEX IF NOT EXISTS idx_router_decisions_class_acc ON router_decisions(classification, user_accepted);
CREATE INDEX IF NOT EXISTS idx_router_decisions_created   ON router_decisions(created_at);

-- Layer 3 訓練 run 紀錄（PR-O-2 將移除 server.py 內重複 DDL，統一以本檔為來源）
CREATE TABLE IF NOT EXISTS finetune_runs (
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

CREATE INDEX IF NOT EXISTS idx_finetune_runs_block_status ON finetune_runs(adapter_block, status, id);

-- ============================================================
-- Layer 2 核心表（Chamber 訓練資料層）
-- 已排除 feature 表 golden_samples（將於 PR-O-3 移至 modules/gatekeeper/）
-- ============================================================

CREATE TABLE IF NOT EXISTS teachers (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    name                    TEXT NOT NULL UNIQUE,
    model_id                TEXT NOT NULL,
    api_base                TEXT NOT NULL,
    keychain_ref            TEXT,
    priority                INTEGER NOT NULL DEFAULT 0,
    daily_limit             INTEGER NOT NULL DEFAULT 250,
    is_active               INTEGER NOT NULL DEFAULT 1,
    is_daily_limit_reached  INTEGER NOT NULL DEFAULT 0,
    vendor                  TEXT NOT NULL DEFAULT 'unknown',
    rpm_limit               INTEGER DEFAULT NULL,
    rpm_window_start        TEXT DEFAULT NULL,
    rpm_count_in_window     INTEGER DEFAULT 0,
    transient_backoff_until TEXT DEFAULT NULL,
    daily_request_limit     INTEGER DEFAULT 250,
    daily_token_limit       INTEGER DEFAULT NULL,
    quota_reset_period      TEXT DEFAULT 'daily',
    requests_today          INTEGER DEFAULT 0,
    input_tokens_today      INTEGER DEFAULT 0,
    output_tokens_today     INTEGER DEFAULT 0,
    quota_exhausted_at      TEXT DEFAULT NULL,
    quota_exhausted_type    TEXT DEFAULT NULL,
    created_at              TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS question_sets (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL UNIQUE,
    event_type  TEXT NOT NULL,
    description TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS questions (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    set_id     INTEGER NOT NULL REFERENCES question_sets(id),
    prompt     TEXT NOT NULL,
    difficulty INTEGER NOT NULL DEFAULT 5,
    is_active  INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS training_samples (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    source              TEXT NOT NULL CHECK(source IN ('layer1_bridge', 'layer1_bridge_v2', 'error_repair')),
    session_id          TEXT,
    question_id         INTEGER REFERENCES questions(id),
    teacher_id          INTEGER REFERENCES teachers(id),
    event_type          TEXT NOT NULL,
    instruction         TEXT NOT NULL,
    input               TEXT NOT NULL DEFAULT '',
    output              TEXT NOT NULL,
    score               REAL,
    score_reason        TEXT,
    refined_instruction TEXT,
    expected_answer     TEXT,
    pii_scrubbed        INTEGER NOT NULL DEFAULT 0,
    source_exchange_ids TEXT,
    status              TEXT NOT NULL DEFAULT 'raw'
                            CHECK(status IN ('raw','pending','approved','rejected','needs_review')),
    adapter_block       INTEGER,
    weight              REAL NOT NULL DEFAULT 1.0,
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    reviewed_at         TEXT
);

CREATE TABLE IF NOT EXISTS teacher_usage_logs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    teacher_id      INTEGER NOT NULL REFERENCES teachers(id),
    used_at         TEXT NOT NULL DEFAULT (datetime('now')),
    sample_id       INTEGER REFERENCES training_samples(id),
    tokens_used     INTEGER,
    input_tokens    INTEGER DEFAULT 0,
    output_tokens   INTEGER DEFAULT 0,
    response_status TEXT
);

CREATE INDEX IF NOT EXISTS idx_training_samples_status     ON training_samples(status);
CREATE INDEX IF NOT EXISTS idx_training_samples_event_type ON training_samples(event_type);
CREATE INDEX IF NOT EXISTS idx_training_samples_adapter    ON training_samples(adapter_block);
CREATE INDEX IF NOT EXISTS idx_teacher_usage_date          ON teacher_usage_logs(teacher_id, used_at);
