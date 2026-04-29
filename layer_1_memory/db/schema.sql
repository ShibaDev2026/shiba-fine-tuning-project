-- ============================================================
-- shiba-brain.db — Layer 1 記憶層完整 Schema
-- 採用 WAL 模式防止 Hook / FastAPI 並發衝突
-- ============================================================

-- WAL 模式（Write-Ahead Logging，允許多讀一寫並發）
PRAGMA journal_mode=WAL;
-- 衝突時最多重試 5 秒，避免 SQLITE_BUSY 錯誤
PRAGMA busy_timeout=5000;
-- 外鍵約束啟用
PRAGMA foreign_keys=ON;

-- ============================================================
-- Layer 1：四層記憶結構
-- projects → sessions → branches → messages
-- ============================================================

-- 專案表：對應 Claude Code 的 working directory
CREATE TABLE IF NOT EXISTS projects (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,          -- 專案名稱（目錄名）
    path        TEXT NOT NULL UNIQUE,   -- 專案絕對路徑（hash 對應）
    hash        TEXT NOT NULL UNIQUE,   -- Claude Code 的 project hash
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Session 表：對應一次 Claude Code 對話
CREATE TABLE IF NOT EXISTS sessions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id   INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    uuid         TEXT NOT NULL UNIQUE,  -- Claude Code session UUID
    started_at   TEXT NOT NULL DEFAULT (datetime('now')),
    ended_at     TEXT,
    -- 統計摘要欄位
    exchange_count   INTEGER DEFAULT 0, -- user/assistant 對話回合數
    files_modified   INTEGER DEFAULT 0, -- 修改的檔案數
    commits          INTEGER DEFAULT 0, -- git commit 次數
    tool_counts      TEXT DEFAULT '{}', -- JSON：各 tool 使用次數
    event_types      TEXT DEFAULT '[]', -- JSON array：本 session 的事件分類
    context_summary  TEXT               -- 壓縮後的 context 摘要（Phase 3 填入）
);

-- Branch 表：追蹤 rewind 產生的對話分支
CREATE TABLE IF NOT EXISTS branches (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    branch_idx  INTEGER NOT NULL DEFAULT 0,  -- 第幾條分支（0 = 主線）
    is_active   INTEGER NOT NULL DEFAULT 1,  -- 1 = 當前有效分支
    leaf_uuid   TEXT,                        -- 最末節點的 UUID
    -- 統計欄位（從 parser 計算）
    exchange_count   INTEGER DEFAULT 0,
    files_modified   INTEGER DEFAULT 0,
    commits          INTEGER DEFAULT 0,
    -- 時間戳
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    ended_at    TEXT,
    -- 記憶衰減欄位（Phase 7 啟用邏輯，此處預留）
    last_accessed TEXT,                      -- 最後被 RAG 檢索的時間
    access_count  INTEGER DEFAULT 0,         -- 被 RAG 命中次數
    decay_score   REAL DEFAULT 1.0,          -- 衰減分數 0.0~1.0（低於 0.2 歸檔）
    UNIQUE(session_id, branch_idx)
);

-- Messages 表：儲存所有原始訊息
CREATE TABLE IF NOT EXISTS messages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    uuid        TEXT NOT NULL UNIQUE,   -- 訊息 UUID（來自 .jsonl）
    parent_uuid TEXT,                   -- 父節點 UUID（建 DAG 用）
    role        TEXT NOT NULL,          -- 'user' | 'assistant'
    content     TEXT,                   -- 訊息純文字內容
    raw_content TEXT,                   -- 完整 JSON 序列化結構（含 tool_result 等）
    input_tokens INTEGER DEFAULT 0,     -- 輸入 token 消耗
    output_tokens INTEGER DEFAULT 0,    -- 輸出 token 消耗
    cache_creation_input_tokens INTEGER DEFAULT 0, -- Cache 建立消耗 
    cache_read_input_tokens INTEGER DEFAULT 0,     -- Cache 讀取節省
    char_count INTEGER DEFAULT 0,       -- 字元數
    byte_count INTEGER DEFAULT 0,       -- 位元組大小
    encoding TEXT DEFAULT 'utf-8',      -- 編碼格式
    is_compressed INTEGER DEFAULT 0,    -- 內文是否經過 zlib 壓縮
    message_time TEXT,                  -- 真實對話時間戳
    model_name   TEXT,                  -- 使用模型，例：claude-3-7-sonnet
    has_tool_use INTEGER DEFAULT 0,     -- 是否含工具呼叫
    tool_names  TEXT DEFAULT '[]',      -- JSON array：使用的工具名稱
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ============================================================
-- Tool Executions 表：從 raw_content 拆分出來供後續正規化與壓縮
-- ============================================================
CREATE TABLE IF NOT EXISTS tool_executions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id    INTEGER NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
    tool_use_id   TEXT NOT NULL,
    tool_name     TEXT NOT NULL,
    input_cmd     TEXT,               -- 傳入的指令參數 (不壓縮)
    output_log    BLOB,               -- 執行結果 (gzip 壓縮)
    is_error      INTEGER DEFAULT 0,  -- 是否失敗 (exit code != 0)
    is_compressed INTEGER DEFAULT 0,  -- output_log 是否經過 zlib 壓縮
    duration_ms   INTEGER,
    UNIQUE(message_id, tool_use_id)
);

-- Branch-Messages 橋接表：記錄哪些訊息屬於哪條分支
CREATE TABLE IF NOT EXISTS branch_messages (
    branch_id   INTEGER NOT NULL REFERENCES branches(id) ON DELETE CASCADE,
    message_id  INTEGER NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
    seq         INTEGER NOT NULL,       -- 在此分支中的順序
    PRIMARY KEY (branch_id, message_id)
);

-- ============================================================
-- Exchanges 表：四步循環語意層（衍生自 messages + tool_executions）
-- 邊界：從一個真正的 user 訊息開始，到下一個真正的 user 訊息之前
-- 純衍生資料，可從 messages + tool_executions 完整重建
-- ============================================================
CREATE TABLE IF NOT EXISTS exchanges (
    id                          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id                  INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    branch_id                   INTEGER NOT NULL REFERENCES branches(id) ON DELETE CASCADE,
    exchange_idx                INTEGER NOT NULL,             -- 該 branch 內第 N 個 exchange（0-based）

    user_message_id             INTEGER NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
    final_assistant_message_id  INTEGER REFERENCES messages(id) ON DELETE SET NULL,

    message_count               INTEGER NOT NULL DEFAULT 0,   -- 包含的 messages 總數
    assistant_message_count     INTEGER NOT NULL DEFAULT 0,
    tool_round_count            INTEGER NOT NULL DEFAULT 0,   -- 含 tool_use 的 assistant 訊息數
    tool_use_count              INTEGER NOT NULL DEFAULT 0,   -- tool_executions 配對總數

    has_tool_use                INTEGER NOT NULL DEFAULT 0,
    has_error                   INTEGER NOT NULL DEFAULT 0,   -- 任一 tool_executions.is_error=1 即為 1
    has_final_text              INTEGER NOT NULL DEFAULT 0,
    tool_names                  TEXT NOT NULL DEFAULT '[]',   -- JSON array：本 exchange 用到的所有工具

    user_text_preview           TEXT,                          -- user content 截 300 字
    final_text_preview          TEXT,                          -- final assistant content 截 500 字

    status                      TEXT NOT NULL DEFAULT 'completed'
        CHECK(status IN ('in_progress', 'completed', 'abandoned')),
    started_at                  TEXT NOT NULL,                 -- = user_message.message_time
    ended_at                    TEXT,                          -- = final_assistant.message_time
    created_at                  TEXT NOT NULL DEFAULT (datetime('now')),

    UNIQUE(branch_id, exchange_idx)
);

CREATE INDEX IF NOT EXISTS idx_exchanges_session       ON exchanges(session_id);
CREATE INDEX IF NOT EXISTS idx_exchanges_branch        ON exchanges(branch_id, exchange_idx);
CREATE INDEX IF NOT EXISTS idx_exchanges_user_msg      ON exchanges(user_message_id);
CREATE INDEX IF NOT EXISTS idx_exchanges_final_msg     ON exchanges(final_assistant_message_id);
CREATE INDEX IF NOT EXISTS idx_exchanges_status        ON exchanges(status);
CREATE INDEX IF NOT EXISTS idx_exchanges_filter        ON exchanges(session_id, status, has_tool_use, has_error);

-- Exchange-Messages 橋接表：記錄每個 exchange 包含哪些 messages（含順序與語意角色）
-- 同 branch_messages 風格；同一 message 在多分支可屬於不同 exchange
CREATE TABLE IF NOT EXISTS exchange_messages (
    exchange_id      INTEGER NOT NULL REFERENCES exchanges(id) ON DELETE CASCADE,
    message_id       INTEGER NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
    seq              INTEGER NOT NULL,
    role_in_exchange TEXT NOT NULL,
        -- 'user_open'        : 開啟 exchange 的真正 user 訊息
        -- 'assistant_tool'   : 含 tool_use 的 assistant（中間步驟）
        -- 'tool_result_user' : 包裝 tool_result 的 user 訊息
        -- 'assistant_final'  : 最終文字回應的 assistant
        -- 'assistant_text'   : 有文字但非最終的 assistant（罕見）
    PRIMARY KEY (exchange_id, message_id)
);

CREATE INDEX IF NOT EXISTS idx_exchange_messages_msg ON exchange_messages(message_id);
CREATE INDEX IF NOT EXISTS idx_exchange_messages_seq ON exchange_messages(exchange_id, seq);

-- ============================================================
-- FTS5 全文索引：加速 RAG 語義檢索
-- ============================================================

-- 建立 FTS5 虛擬表（對應 sessions 的摘要資訊）
CREATE VIRTUAL TABLE IF NOT EXISTS sessions_fts USING fts5(
    session_uuid,       -- sessions.uuid
    project_path,       -- 所屬專案路徑
    event_types,        -- 事件分類（空格分隔）
    content_summary,    -- 可檢索的內容摘要（message content 精簡版）
    files_list,         -- 修改的檔案清單
    ended_at,           -- session 結束時間（排序用）
    tokenize="trigram"  -- 支援中文子字串匹配（3字元滑動視窗）
);

-- ============================================================
-- 索引：加速常見查詢
-- ============================================================

CREATE INDEX IF NOT EXISTS idx_sessions_project   ON sessions(project_id);
CREATE INDEX IF NOT EXISTS idx_sessions_uuid      ON sessions(uuid);
CREATE INDEX IF NOT EXISTS idx_branches_session   ON branches(session_id);
CREATE INDEX IF NOT EXISTS idx_branches_active    ON branches(session_id, is_active);
CREATE INDEX IF NOT EXISTS idx_messages_session   ON messages(session_id);
CREATE INDEX IF NOT EXISTS idx_messages_uuid      ON messages(uuid);
CREATE INDEX IF NOT EXISTS idx_messages_parent    ON messages(parent_uuid);
CREATE INDEX IF NOT EXISTS idx_projects_hash      ON projects(hash);

CREATE INDEX IF NOT EXISTS idx_tool_executions_msg ON tool_executions(message_id);
CREATE INDEX IF NOT EXISTS idx_tool_executions_err ON tool_executions(tool_name, is_error);

-- ============================================================
-- Embedding 表：語意向量召回（Layer 1 升級）
-- ============================================================

-- 因果對 embedding：user 說的話（因）→ 實際執行指令（果）
CREATE TABLE IF NOT EXISTS exchange_embeddings (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    session_uuid       TEXT NOT NULL,
    instruction        TEXT NOT NULL,   -- user 的原始說法（因）
    source_instruction TEXT,            -- NULL=原始；非 NULL=paraphrase 來源，防止二次展開
    commands           TEXT NOT NULL,   -- 實際執行的 bash/git 指令（果）
    embedding          BLOB NOT NULL,   -- instruction 的 JSON float array 向量
    model              TEXT NOT NULL DEFAULT 'nomic-embed-text',
    created_at         TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_exchange_embeddings_session ON exchange_embeddings(session_uuid);
