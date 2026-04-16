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
-- FTS5 全文索引：加速 RAG 語義檢索
-- ============================================================

-- 建立 FTS5 虛擬表（對應 sessions 的摘要資訊）
CREATE VIRTUAL TABLE IF NOT EXISTS sessions_fts USING fts5(
    session_uuid,       -- sessions.uuid
    project_path,       -- 所屬專案路徑
    event_types,        -- 事件分類（空格分隔）
    content_summary,    -- 可檢索的內容摘要（message content 精簡版）
    files_list,         -- 修改的檔案清單
    ended_at            -- session 結束時間（排序用）
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
