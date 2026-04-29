-- Layer 2 精神時光屋 資料庫 Schema
-- 與 Layer 1 共用 ~/.local-brain/shiba-brain.db

-- ── 師父（外部 LLM Teacher）──────────────────────────────────────────
CREATE TABLE IF NOT EXISTS teachers (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT NOT NULL UNIQUE,           -- 顯示名稱，e.g. "Gemini 2.5 Flash"
    model_id      TEXT NOT NULL,                  -- API model string
    api_base      TEXT NOT NULL,                  -- OpenAI-compatible endpoint
    keychain_ref  TEXT NOT NULL,                  -- macOS Keychain item name（不存 key 本身）
    priority      INTEGER NOT NULL DEFAULT 0,     -- 數字越小越優先
    daily_limit   INTEGER NOT NULL DEFAULT 250,   -- 每日請求上限
    is_active     INTEGER NOT NULL DEFAULT 1,     -- 0=停用
    is_daily_limit_reached INTEGER NOT NULL DEFAULT 0, -- 1=當日額度耗盡
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ── 問題集（題目分組）────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS question_sets (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT NOT NULL UNIQUE,
    event_type    TEXT NOT NULL,                  -- 對應 Layer 1 event_type
    description   TEXT,
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ── 問題（每道訓練題）────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS questions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    set_id        INTEGER NOT NULL REFERENCES question_sets(id),
    prompt        TEXT NOT NULL,                  -- 題目正文
    difficulty    INTEGER NOT NULL DEFAULT 5,     -- 1-10
    is_active     INTEGER NOT NULL DEFAULT 1,
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ── 訓練樣本（Teacher 評分結果）──────────────────────────────────────
CREATE TABLE IF NOT EXISTS training_samples (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    -- 來源：路徑A = Layer1橋接；路徑B = error-repair 重生
    source          TEXT NOT NULL CHECK(source IN ('layer1_bridge', 'layer1_bridge_v2', 'error_repair')),
    session_id      TEXT,                         -- Layer 1 session_id（路徑A）
    question_id     INTEGER REFERENCES questions(id), -- 路徑B 題目
    teacher_id      INTEGER REFERENCES teachers(id),
    event_type      TEXT NOT NULL,
    instruction     TEXT NOT NULL,                -- Alpaca instruction 欄位
    input           TEXT NOT NULL DEFAULT '',     -- Alpaca input 欄位
    output          TEXT NOT NULL,                -- Alpaca output 欄位
    score           REAL,                         -- Teacher 評分 0-10
    score_reason    TEXT,                         -- 評分理由
    refined_instruction TEXT,                        -- Qwen 改寫後的自包含版本
    expected_answer TEXT,                            -- Qwen 草擬的預期答案（供 Teacher 參考）
    pii_scrubbed    INTEGER NOT NULL DEFAULT 0,      -- 1=已過 PII scrub
    status          TEXT NOT NULL DEFAULT 'raw'
                        CHECK(status IN ('raw','pending','approved','rejected','needs_review')),
    adapter_block   INTEGER,                      -- 1 或 2，對應 LoRA block
    weight          REAL NOT NULL DEFAULT 1.0,    -- P1-3 隱性標籤權重（1.0/1.5/2.0）
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    reviewed_at     TEXT
);

-- ── Teacher 使用日誌（配額追蹤）──────────────────────────────────────
CREATE TABLE IF NOT EXISTS teacher_usage_logs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    teacher_id    INTEGER NOT NULL REFERENCES teachers(id),
    used_at       TEXT NOT NULL DEFAULT (datetime('now')),
    sample_id     INTEGER REFERENCES training_samples(id),
    tokens_used   INTEGER,                        -- 可選，記錄 token 消耗
    response_status TEXT                          -- 'success' | 'quota_exceeded' | 'error'
);

-- ── 索引 ─────────────────────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_training_samples_status     ON training_samples(status);
CREATE INDEX IF NOT EXISTS idx_training_samples_event_type ON training_samples(event_type);
CREATE INDEX IF NOT EXISTS idx_training_samples_adapter    ON training_samples(adapter_block);
CREATE INDEX IF NOT EXISTS idx_teacher_usage_date          ON teacher_usage_logs(teacher_id, used_at);
