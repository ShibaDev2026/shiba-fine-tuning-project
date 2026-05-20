-- model_registry
-- 每個 yaml 的每個版本一行；is_current=1 標記該 yaml 的當前版
-- yaml 檔案 sha256 變動時自動寫入新版（append-only），保留完整版本歷史
-- sync 觸發點：layer_2 backend FastAPI lifespan startup
-- snapshot JSON 內容：description / yaml_version / ollama_tag / hf_repo /
--                     inference / prompt / training / meta / maintenance
CREATE TABLE IF NOT EXISTS model_registry (
  id            INTEGER PRIMARY KEY,                    -- SQLite rowid 別名（勿加 AUTOINCREMENT）
  model_name    TEXT NOT NULL,                          -- yaml stem，e.g. classifier-gemma3-4b（同 stem 多版本，故不 UNIQUE）
  version_seq   INTEGER NOT NULL,                       -- 同 model_name 內遞增（1, 2, 3...）；前端顯示 v3 用
  is_current    INTEGER NOT NULL DEFAULT 0,             -- 1 = 該 model_name 最新版；同 stem 僅一行為 1（partial unique index 強制）
  content_hash  TEXT NOT NULL,                          -- sha256(file bytes)，變動偵測核心
  role          TEXT NOT NULL CHECK (role IN
                  ('classifier','compressor','responder','embedder','training_base')),
  display_name  TEXT NOT NULL,                          -- 給人看；前端 dropdown 直接用
  snapshot      TEXT NOT NULL,                          -- 完整 yaml 解析後 JSON
  change_kind   TEXT NOT NULL CHECK (change_kind IN
                  ('created','modified','restored','removed')),
  recorded_at   TEXT NOT NULL DEFAULT (datetime('now')),-- UTC（與專案其他表一致；前端顯示時 +8h）
  UNIQUE (model_name, version_seq),                     -- 版本序號不重
  UNIQUE (model_name, content_hash)                     -- restored 必須 hash 不同；禁止拆此約束
);

-- 同 model_name 僅一筆 is_current=1
CREATE UNIQUE INDEX IF NOT EXISTS uq_registry_current
  ON model_registry(model_name) WHERE is_current = 1;

-- dropdown 查詢：WHERE is_current=1 AND role=? ORDER BY display_name
CREATE INDEX IF NOT EXISTS idx_registry_role_current
  ON model_registry(role, is_current) WHERE is_current = 1;

-- 歷史查詢：WHERE model_name=? ORDER BY version_seq DESC
CREATE INDEX IF NOT EXISTS idx_registry_history
  ON model_registry(model_name, version_seq DESC);
