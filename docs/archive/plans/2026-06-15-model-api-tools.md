# model_api_tools — 模型清單爬取與本機選型目錄

> 設計日期：2026-06-15　狀態：spec（待 Shiba review → writing-plans）
> 完成驗證後依規範刪除本檔。

## 目的

觸發式爬取 **Ollama library** 與 **HuggingFace（LM Studio 用）** 的官方模型清單，寫入統一 DB 的 `search_model_list` 表，作為**本機閉環選型目錄**——知道有哪些可用模型、規格為何、哪些已在本機，據此決定要拉/要跑哪個（不再依賴付費 API）。

非目標：訓練後 adapter 的版本/指標管理（那是 `model_registry`，與本表無關）。

---

## 鎖定的 scope 決策

1. **混合深度**：遠端只抓「清單端點給得起」的淺層；本機已安裝者補深層（`ollama show` / 本地 GGUF metadata，**在本機免費**，不打 HTTP detail）。
2. **日期範圍**（可異動參數）：過濾 `lastModified`，預設 `[2025-06-01, 2026-06-15]`。
   - HF：`sort=lastModified&direction=-1`，分頁到越過 start 即停 + `max_records` 安全上限。
   - Ollama index 僅相對時間（"1 year ago"）→ 解析為**近似日期**（已確認貼近即可，不補 detail page）。
3. **官方範圍**：
   - **Ollama**：整個 `ollama.com/library`（本身即官方策展），全抓 + 套日期，無白名單。
   - **HF**：白名單 `{lmstudio-community, mlx-community, ggml-org}` + 原廠自出 GGUF/MLX（白名單為可異動參數）。原廠 org 多 safetensors、少 GGUF/MLX，故不採「原廠 only」。
4. **格式**：HF 開**雙 lane**（`filter=gguf` + `filter=mlx`），`model_format` **由 lane 直接標記**（不靠 tags——驗證發現 `mlx-community/Nex-N2-Pro-mlx-8bit` 無 mlx tag 仍是 MLX）。納入哪些 format 為可異動參數（預設兩者）。Ollama 一律 `gguf`。
5. **快照策略**：**Append-only**（每次觸發寫新列，共用 `scrape_run_id`/`scraped_at`，保留下載量趨勢）；另給 view 取「每 model 最新列」。

---

## 架構（模組）

```
model_api_tools/
├── core/
│   ├── ollama_scraper.py   # ollama.com/library HTML → 淺層 records（source=ollama）
│   ├── hf_scraper.py       # HF /api/models（白名單 × format lane）→ 淺層 records
│   ├── local_scanner.py    # ollama list/show + lms ls → 本機 deep + 標 is_local_installed
│   └── store.py            # 寫 search_model_list / model_local_detail（DIP：抓取不碰 SQL）
├── cli.py                  # CLI 觸發 adapter
└── api.py                  # FastAPI 觸發 adapter（獨立 app，不掛 Layer 2 backend）
```

SRP：抓取 / 本機掃描 / 持久化 / 觸發 四者分離。DIP：CLI 與 FastAPI 共用同一份 `core`，不重複邏輯。

---

## Schema（統一 DB `./data/shiba-brain.db`）

### `search_model_list`（目錄主表，~20 欄）

```sql
CREATE TABLE IF NOT EXISTS search_model_list (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    -- 來源 / 識別（人·地）
    source          TEXT NOT NULL CHECK(source IN ('ollama','huggingface')),
    name            TEXT NOT NULL,          -- ollama: library slug / hf: repo id
    author          TEXT,                   -- hf author；ollama NULL
    source_url      TEXT,                   -- 該 model 來源連結
    -- 描述 / 用途
    description     TEXT,                   -- ollama index 有；hf 淺層 NULL
    usage           TEXT,                   -- 用途/Usage 合一：ollama 能力標籤 / hf pipeline_tag
    tags            TEXT,                   -- 原始標籤 JSON array（raw provenance hedge）
    -- 時間（時）
    updated_at      TEXT,                   -- ISO；hf lastModified / ollama 近似
    -- 量化指標（語意不可混 → 分欄標明）
    download_count  INTEGER,
    download_metric TEXT CHECK(download_metric IN ('cumulative','30d')),
    -- 規格（深層才填）
    model_format    TEXT CHECK(model_format IN ('gguf','mlx','safetensors','other')),
    param_size      TEXT,                   -- "8b/70b"（ollama index csv）
    context_length  INTEGER,                -- 本機 deep；遠端 NULL
    file_size_bytes INTEGER,                -- 本機 deep；遠端 NULL
    quantization    TEXT,                   -- 深層
    -- 本機狀態（物）
    is_local_installed INTEGER NOT NULL DEFAULT 0,   -- ollama list / lms ls（含原 is_downloaded 語意）
    -- 追溯 / 快照（事）
    detail_level    TEXT NOT NULL CHECK(detail_level IN ('shallow','deep')),
    scraped_at      TEXT NOT NULL,          -- 本列爬取時戳
    scrape_run_id   TEXT NOT NULL           -- 同次觸發批次 id
);

CREATE INDEX IF NOT EXISTS idx_sml_source_name ON search_model_list(source, name);
CREATE INDEX IF NOT EXISTS idx_sml_run         ON search_model_list(scrape_run_id);
```

> 已砍：`is_downloaded`（併入 `is_local_installed`）、`likes`、`created_at_src`、`updated_at_raw`（理由：對「選哪個來跑」無增量資訊）。

### `model_local_detail`（本機深層 metadata 子表，SRP 外移）

```sql
CREATE TABLE IF NOT EXISTS model_local_detail (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    model_id     INTEGER NOT NULL REFERENCES search_model_list(id),
    raw_metadata TEXT,                       -- ollama show / GGUF metadata 全量 JSON
    scraped_at   TEXT NOT NULL
);
```

### `v_search_model_latest`（每 model 最新列）

```sql
CREATE VIEW IF NOT EXISTS v_search_model_latest AS
SELECT s.* FROM search_model_list s
WHERE s.scraped_at = (
    SELECT MAX(s2.scraped_at) FROM search_model_list s2
    WHERE s2.source = s.source AND s2.name = s.name
);
```

Migration 落點：`config/db/` 新增 migration（與現有 schema 管理一致）。

---

## Data flow

1. **Trigger**（CLI / FastAPI）帶參數：`{sources, start, end, max_records, hf_whitelist, formats}`；產生單一 `scrape_run_id` + `scraped_at`。
2. **遠端淺層**：
   - `ollama_scraper`：抓 library HTML → 解析每張 model card（name/description/usage 標籤/param_size/pulls/近似 updated_at）→ `model_format='gguf'`、`download_metric='cumulative'`、`detail_level='shallow'`，套日期過濾。
   - `hf_scraper`：對 `whitelist × formats` 各 lane 打 `/api/models?author=&filter=&sort=lastModified`，分頁到越過 start / 達 `max_records`；`model_format`=lane、`download_metric='30d'`、`detail_level='shallow'`。
3. **本機掃描 + 深層**：`local_scanner` 跑 `ollama list` + `lms ls`；命中者設 `is_local_installed=1`、升級 `detail_level='deep'`，由 `ollama show` / 本地 GGUF 補 `context_length`/`file_size_bytes`/`quantization`，全量 JSON 寫 `model_local_detail`。本機有、但遠端清單沒有的，仍補一列（deep）。
4. **Store**：append 全部列，共用 `scrape_run_id`/`scraped_at`。

---

## 實作前提（已確認 2026-06-15）

- **`lms` CLI 可用**（已驗證在 PATH，`~/.lmstudio/models` 存在）→ 本機掃描走 `lms ls` 主路徑；保留掃 models 目錄為防禦 fallback（路徑由 CONFIG 提供，不硬編個人路徑）。
- **FastAPI = 獨立 app**（不掛 Layer 2 backend）；Vue dashboard 觸發按鈕另接此 app。
- **Ollama 相對時間：貼近即可**，不補 detail page、不追求精確。

## 實作步驟（bottom-up，單次異動原則：一步驗證過才進下一步）

> model/effort 切換時機 = **每步邊界**。核心解析/協調 → Opus high；樣板/整合 → Sonnet medium；驗證收尾 → Haiku low。

| # | 步驟 | 交付 | 驗證 | model / effort |
|---|------|------|------|----------------|
| 1 | Schema | `config/db/` 新增 schema（`search_model_list` + `model_local_detail` + `v_search_model_latest`），以現有方式套用 | 套用後三物件存在；CHECK 約束生效 | Sonnet / medium |
| 2 | `core/store.py` | append 寫入 + batch `scrape_run_id`/`scraped_at`；deep 列寫 `model_local_detail` | roundtrip（寫→讀）短＋長各一；view 取最新列正確 | Sonnet / medium |
| 3 | `core/ollama_scraper.py` | 抓 library HTML → 解析 card（name/desc/usage 標籤/param/pulls/近似時間）→ shallow records + 日期過濾 | 錄製 fixture 解析 → 欄位對映 + `model_format='gguf'` / `download_metric='cumulative'` | Sonnet / medium（HTML 解析脆弱則升 Opus high）|
| 4 | `core/hf_scraper.py` | `whitelist × {gguf,mlx}` lane 打 `/api/models`，分頁到越過 start / 達 `max_records` | fixture 解析 → `model_format`=lane、`download_metric='30d'`、日期停損正確 | Sonnet / medium |
| 5 | `core/local_scanner.py` | `ollama list`+`ollama show`、`lms ls` → 標 `is_local_installed`、deep 補 context/size/quant + raw JSON | mock 輸出 → `is_local_installed` + deep 欄位 + 本機獨有列補建 | Sonnet / medium |
| 6 | `core/runner.py` | `run_scrape(params)` 協調：遠端 scrape → 本機 scan/enrich → store（單一 run_id）；cli/api 共用（DIP） | 整合 smoke：跑一次 → 列數合理、shallow/deep 標記正確 | Sonnet / medium |
| 7 | `cli.py` + `api.py` | CLI argparse 觸發；獨立 FastAPI `POST /scrape/{ollama\|hf}` body`{start,end,max_records,whitelist,formats}`，皆呼叫 `run_scrape` | CLI dry-run；FastAPI TestClient POST → 200 + 列寫入 | cli Haiku / low；api Sonnet / medium |
| 8 | 測試 + 收尾 | 補齊下節測試；跑 `pytest tests/ -q` | 綠燈且 ≥ baseline 145 | Haiku / low |

**依賴**：HTML 解析優先用 stdlib `html.parser`（避免新依賴）；若專案已有 `bs4` 則用之（Step 3 先確認）。API 走 `urllib`（沿用 `embedder.py` 模式）。FastAPI 沿用專案既有版本。

## 測試（最小集合，依測試精簡原則）

- `ollama_scraper` / `hf_scraper`：各用一份**錄製 fixture**（不打即時網路）解析 → 欄位對映正確。
- `local_scanner`：mock `ollama list`/`ollama show` 輸出 → `is_local_installed` + deep 欄位正確。
- `store`：roundtrip（寫入 → 讀回）短＋長各一；append 後 view 取最新列正確。

## 不在範圍（YAGNI）

- 遠端 description / file_size 補抓（HF 淺層不補；只本機補 deep）。
- 自動排程（先手動觸發；cron 之後再說）。
- 模型實際下載/安裝動作（本工具只「紀錄」，不執行 pull）。
