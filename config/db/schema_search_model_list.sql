-- search_model_list — Ollama library + HuggingFace 官方模型爬取目錄
-- 每次觸發爬取寫入一批新列（append-only）；同批共用 scrape_run_id / scraped_at，保留歷史快照
-- 抓取深度：遠端只填「清單端點給得起」的淺層（shallow）；本機已安裝者升級為 deep
--           （ollama show / 本地 GGUF metadata，在本機免費，不打 HTTP detail）
-- 觸發點：model_api_tools CLI / 獨立 FastAPI（core/runner.run_scrape）
-- 語意提醒：download_count 因來源而異（ollama=cumulative pulls / hf=近 30 天），
--           故配 download_metric 標明，兩者數字不可直接比較
CREATE TABLE IF NOT EXISTS search_model_list (
  id              INTEGER PRIMARY KEY,                     -- SQLite rowid 別名（勿加 AUTOINCREMENT）
  -- 來源 / 識別（人·地）
  source          TEXT NOT NULL CHECK (source IN ('ollama','huggingface')),
  name            TEXT NOT NULL,                           -- ollama: library slug / hf: repo id
  author          TEXT,                                    -- hf author；ollama 為 NULL
  source_url      TEXT,                                    -- 該 model 來源連結
  -- 描述 / 用途
  description     TEXT,                                    -- ollama index 有；hf 淺層為 NULL
  usage           TEXT,                                    -- 用途/Usage 合一：ollama 能力標籤 / hf pipeline_tag
  tags            TEXT,                                    -- 原始標籤 JSON array（raw provenance；保留供日後重抽欄位）
  -- 時間（時）
  updated_at      TEXT,                                    -- ISO；hf lastModified / ollama 近似（相對時間解析）
  -- 量化指標（語意不可混 → download_metric 標明單位）
  download_count  INTEGER,
  download_metric TEXT CHECK (download_metric IN ('cumulative','30d')),
  -- 規格（context_length / file_size_bytes / quantization 僅 deep 才填）
  model_format    TEXT CHECK (model_format IN ('gguf','mlx','safetensors','other')),
  param_size      TEXT,                                    -- "8b/70b"（ollama index csv）
  context_length  INTEGER,                                 -- 本機 deep；遠端 NULL
  file_size_bytes INTEGER,                                 -- 本機 deep；遠端 NULL
  quantization    TEXT,                                    -- 深層（e.g. Q4_K_M / 4bit）
  -- 本機狀態（物）；含原 is_downloaded 語意（已合併）
  is_local_installed INTEGER NOT NULL DEFAULT 0,           -- 1 = ollama list / lms ls 命中
  -- 追溯 / 快照（事）
  detail_level    TEXT NOT NULL CHECK (detail_level IN ('shallow','deep')),
  scraped_at      TEXT NOT NULL DEFAULT (datetime('now')), -- UTC（與專案其他表一致；前端顯示 +8h）
  scrape_run_id   TEXT NOT NULL                            -- 同次觸發批次 id（uuid），可比對歷次 snapshot
);

-- 最新列查詢 / 按 (source,name) 聚合（view 的 MAX(scraped_at) 子查詢亦走此索引）
CREATE INDEX IF NOT EXISTS idx_sml_source_name
  ON search_model_list(source, name);

-- 同批快照查詢：WHERE scrape_run_id=?
CREATE INDEX IF NOT EXISTS idx_sml_run
  ON search_model_list(scrape_run_id);


-- model_local_detail — 本機深層 metadata 全量 JSON（SRP：與 catalog 主列分離，避免每列塞大 blob）
-- 來源：ollama show / 本地 GGUF metadata；僅 is_local_installed=1 的列會有對應 detail
CREATE TABLE IF NOT EXISTS model_local_detail (
  id           INTEGER PRIMARY KEY,                        -- SQLite rowid 別名
  model_id     INTEGER NOT NULL REFERENCES search_model_list(id),  -- 對應 search_model_list.id
  raw_metadata TEXT,                                       -- ollama show / GGUF metadata 全量 JSON
  scraped_at   TEXT NOT NULL DEFAULT (datetime('now'))     -- UTC
);

CREATE INDEX IF NOT EXISTS idx_mld_model_id
  ON model_local_detail(model_id);


-- v_search_model_latest — 每 (source,name) 取最新一批（最大 scraped_at）的列
-- 用途：前端/查詢預設看「現況」，不必每次處理 append-only 的歷史列
CREATE VIEW IF NOT EXISTS v_search_model_latest AS
SELECT s.* FROM search_model_list s
WHERE s.scraped_at = (
  SELECT MAX(s2.scraped_at) FROM search_model_list s2
  WHERE s2.source = s.source AND s2.name = s.name
);
