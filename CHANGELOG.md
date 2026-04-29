# Changelog

所有版本變更依照 [Keep a Changelog](https://keepachangelog.com/zh-TW/1.0.0/) 格式記錄。
版本號遵循 [Semantic Versioning](https://semver.org/lang/zh-TW/)。

## [1.1.1] - 2026-04-29

### Fixed

- **C1 `config.py` migration**：`_run_refiner_migration` 重建的 `training_samples_new` 補入 `layer1_bridge_v2` 與 `weight` 欄位，避免 migration 重跑時蓋掉正確 CHECK 導致 v2 樣本永遠無法入庫
- **W1 `runner.py`**：`finished_at="datetime('now')"` 字串字面量改為 Python 端 `datetime.now(timezone.utc).isoformat()`，修正 Ebbinghaus 間隔訓練因 `fromisoformat` 解析失敗而靜默失效
- **W2 `pipeline.py _has_error_tool`**：改傳 `conn + msg_id`，查 `tool_executions` 精確比對 `tool_use_id`，避免 session 有任何工具錯誤就污染全部 exchange
- **W3 `init_db()` + `server.py`**：`init_db()` 補建 `router_decisions` 表；Layer 3 server startup 補建 `finetune_runs` 表，確保新環境初始化不因表不存在崩潰
- **W4 `background.py`**：extraction job 結束後查逾 24h raw 樣本，非零時 `logger.warning`，方便及早發現 refiner/Ollama 離線造成的鏈路斷裂
- **W5 `background.py`**：extraction 完成後對新 raw 樣本補一次 `sync_sample_weights`，修正 stop_hook 執行時樣本尚未存在導致採納 weight 回饋白白浪費

## [1.1.0] - 2026-04-29

### Added

- **Layer 1 — exchanges 語意層（commit 7091d4e）**
  - 新增 `exchanges` + `exchange_messages` 兩張語意表，記錄每個四步循環（user → tool → tool_result → final_assistant）的完整邊界與預計算欄位（`has_error` / `has_final_text` / `status`）
  - `lib/exchanges.py`：`ExchangeBuilder` state machine，`backfill_exchanges()` 批次補填
  - `hooks/stop_hook.py` 整合：每次 session 結束自動寫入 exchanges
  - backfill 驗證：17,790 筆 exchange，`status='completed'` 率 > 95%

- **Layer 2 — Path A v2（exchanges 語意層，commit ba0ec43）**
  - `extraction/pipeline.py`：新增 `run_extraction_v2` / `_extract_path_a_v2` / `_materialize_exchange_v2` / `_resolve_user_text`（raw_content zlib fallback）
  - 直接讀 `exchanges` 表取代舊版 state machine，解決三個結構性問題：邊界判定脆弱、錯誤標記過粗、語意層重複實作
  - `background.py` + `routes_dataset.py`：caller 切換至 `run_extraction_v2`（source=`layer1_bridge_v2`）
  - `schema_layer2.sql`：`training_samples.source` CHECK 加入 `layer1_bridge_v2`
  - `tools/compare_extraction.py`：A/B 對比腳本（純讀）
  - `tests/layer2/test_pipeline_v2.py`：9 tests（block1/2、has_error、decay_score、去重、resolve_user_text）
  - 舊版 `run_extraction` / `_extract_path_a` 保留不動，Path B 不受影響

## [1.0.0] - 2026-04-25

### Added

- **Phase 3 — Vue 3 + Vite 前端 bootstrap**
  - `frontend-vue/`：Vue 3 + TypeScript + Vite 8 + vue-router 4 + Pinia
  - `tailwind.config.js`：全部 CSS 設計 token 轉換（colors / fontFamily / fontSize / borderRadius / boxShadow）
  - `src/style.css`：Google Fonts（Noto Sans TC / IBM Plex Mono / Space Grotesk）+ Tailwind base

- **Phase 4 — 元件搬遷（React CDN → Vue 3 SFC）**
  - 10 shared 元件：Badge、StatusDot、QuotaBar、DataTable、DetailPanel、SectionHeader、StatCard、Btn、Pagination、DateFilterBar
  - 2 圖表元件：MemoryBarChart（Chart.js stacked bar）、RouterDonut（doughnut）
  - Sidebar（vue-router-link + backend 狀態探測）
  - 4 Phase views：PhaseRouter（決策紀錄 + donut + 對話脈絡）、PhaseMemory（sessions + 趨勢圖）、PhaseTeachers（師父配額 + 投票）、PhasePipeline（flow 動畫 + Ollama 資源）
  - `src/api/client.ts`（native fetch wrapper，base `/api/v1`）、`src/api/dateFilter.ts`（共用日期 QS 建構器）

- **Phase 5 — docker-compose 整合**
  - `frontend-vue/Dockerfile`：multi-stage（node:20-alpine build → nginx:alpine serve）
  - `frontend-vue/nginx.conf`：SPA fallback + `/api/` proxy → backend:8000
  - `docker-compose.yml`：frontend:9590 + backend:8000（internal） + `./data` / `./backups` volume

- **Phase 6 — Layer 3 獨立服務**
  - `layer_3_pipeline/server.py`：FastAPI :8001，`/health` / `/trigger/{block}` / `/runs`
  - `com.shiba.layer3.plist` + `setup_layer3_launchd.sh`：launchd 常駐安裝腳本
  - Layer 2 `routes_finetune.py` + `background.py`：direct import → HTTP POST（`httpx`）至 Layer 3；Layer 3 掛掉時 log warning 不拋異常
  - `requirements.txt` 補 `httpx==0.28.1`

- **Phase 7 — 收尾**
  - `scripts/db_backup.sh`：SQLite `.backup` 確保 WAL 一致性，路徑從 `config/shiba.yaml` 讀取
  - `frontend/_legacy_react_cdn/`：舊 React CDN 原始碼重命名保留

## [0.9.0] - 2026-04-24

### Added

- **Phase 1 — 設定集中化（Vue 3 + docker-compose 重構前置作業）**
  - `config/shiba.yaml`：全專案唯一 source of truth（paths / services / runtime）
  - `shiba_config.py`（專案根）：frozen dataclass singleton，依 `SHIBA_RUNTIME` env 自動擇一 host/docker URL
  - `data/`、`backups/` 骨架（`.gitkeep` 占位，DB/log/queue 依 `.gitignore` 排除）
  - Layer 1 hooks 檔頭 SHIBA_PROJECT_ROOT env pattern：同時支援專案原位與 `~/.claude/plugins/local-brain/` plugin 同步兩種部署

- **Phase 0 — 路由層儀表板後端（前端支援端點）**
  - `routes_router.py`：`/api/v1/router/decisions`（日期篩選 + 分頁）、`/status`（Ollama 連線探測）、`/decisions/{id}/adopt`（採納更新）
  - `routes_memory.py`：`/api/v1/memory/sessions`（日期篩選 + 分頁）、`/sessions/{id}/messages`、`/stats`
  - `routes_finetune.py` 擴充：`/trigger-status`（各 block 距觸發條件距離）、`/ollama-status`
  - `main.py` 啟用 CORS middleware + 註冊新 router

### Changed

- **Phase 1 呼叫點改寫（15+ 處硬寫路徑 → `CONFIG`）**
  - Layer 0：`router/classifier/compressor/telemetry.py` 的 `OLLAMA_BASE`、`DB_PATH` 讀 `CONFIG`
  - Layer 1：`lib/db.py`、`lib/embedder.py` 改讀 `CONFIG`；`config.yaml` 瘦身只留邏輯調參（rag / decay / event_importance / logging.level）
  - Layer 2：`core/config.py`、`extraction/dataset_formatter.py`、`scripts/brain_status.py`、`scripts/setup_teachers.py` 全部改讀 `CONFIG`
  - Layer 3：`db.py`、`gatekeeper.py` 改讀 `CONFIG`；`runner.py` 的 `_DEFAULT_WORK_DIR` 刻意保留硬寫並加註解（MLX 訓練工作區為 Layer 3 私有實作細節，不跨 layer）

- **資料遷移**：`~/.local-brain/shiba-brain.db{,-wal,-shm}` + `logs/` + `queue/` → 專案 `./data/`（36 sessions 保留、integrity ok）

### Fixed

- 清除搬檔後一個 1.5 個月前遺留的 ghost uvicorn process（讀舊 config.py 把 `~/.local-brain/shiba-brain.db` 重建為 4096 byte 空殼）

## [0.8.0] - 2026-04-21

### Added

- **Phase A — 管線穩定性**
  - `layer_2_chamber/scripts/run_scorer.py`：獨立 Scorer CLI，直接呼叫 `score_pending_samples`，不依賴 FastAPI / APScheduler，支援批次輪詢直到配額耗盡
  - `layer_2_chamber/scripts/setup_launchd.sh`：產生並載入 `com.shiba.layer2` LaunchAgent（KeepAlive + RunAtLoad，log → `~/.local-brain/layer2.log`）

- **Phase B — DB Schema 擴充**
  - `teachers` 表新增 8 欄位：`daily_request_limit`、`daily_token_limit`、`quota_reset_period`（`daily`/`monthly`/`none`）、`requests_today`、`input_tokens_today`、`output_tokens_today`、`quota_exhausted_at`、`quota_exhausted_type`
  - `teacher_usage_logs` 表新增 `input_tokens`、`output_tokens` 分拆欄位（`tokens_used` 保留為合計）
  - `config.py` 新增 `_run_token_quota_migration`（幂等，lifespan 自動執行）

- **Phase C — Teacher Service 升級**
  - C1 雙維度配額：`_pick_available_teacher` 新增 `requests_today >= daily_request_limit` 與 `token 總量 >= daily_token_limit` 兩層排除
  - C2 Input/Output 分拆：`_call_gemini_rest` 改用 `promptTokenCount` / `candidatesTokenCount`；`_call_openai_compat` 改用 `prompt_tokens` / `completion_tokens`；簽名改為回傳 `(text, input_t, output_t, status)`
  - C2 `_log_usage` 統一至 `_call_teacher` 內部處理，新增 `_record_teacher_usage`（更新 `requests_today` / `input_tokens_today` / `output_tokens_today`）
  - C3 `keychain_ref = NULL` 支援：本地 Qwen 跳過 Keychain，傳入 dummy `"none"` key
  - 新增 `_mark_quota_exhausted`（記錄耗盡時間與類型）、`call_teacher_for_test`（測試用，不計入 usage log）
  - `multi_judge.py` 移除重複的 `_log_usage` 呼叫（已由 `_call_teacher` 內部統一處理）

- **Phase D — 新 Teacher 預填**
  - `setup_teachers.py` 擴充 4 個新 Teacher：Grok 3 Mini（priority=2）、GitHub GPT-4o-mini（priority=3）、Mistral 7B（priority=4）、Local Qwen 7B（priority=5，keychain_ref=NULL）
  - 現有 Gemini Flash / Flash-Lite 更新 `daily_request_limit` 欄位
  - 新增 `--dry-run` 參數（只印出將插入的資料，不寫入 DB）

- **Phase E — Teacher 前端測試頁**
  - `POST /api/v1/teachers/{id}/test`：發送任意 prompt，回傳 response + input/output tokens + latency_ms
  - `GET /teacher-test`：返回 `static/teacher_test.html`（Tailwind CSS CDN + Test All 並行測試）

- **Phase F — 冷啟動品質改善**
  - F1 Few-shot 校準：`_SCORE_PROMPT` 嵌入 YAML 校準範例（3 個 9-10 分 + 3 個 2-4 分，針對 code/debugging/git_ops）
  - F2 動態 LoRA rank：`mlx_trainer.py` 依 `approved_count` 動態設定 rank（<50 → rank=8 防過擬合；≥50 → rank=16）；`runner.py` 傳入 `approved_count`
  - F3 外部資料集：`dataset_formatter.py` 新增 `_load_external_dataset`，從 `~/.local-brain/external_dataset/*.jsonl` 讀取 Alpaca JSONL，注入 10% 槽位；目錄不存在靜默跳過

- **Phase G — 診斷 CLI**
  - `layer_2_chamber/scripts/brain_status.py`：一鍵顯示 Pipeline（pending/approved/block 進度）、Teacher 配額狀態（含 token 用量）、外部資料集配置狀況

### Changed

- `background.py` `_reset_daily_limits`：每日重置擴充至清除 `requests_today`、`input_tokens_today`、`output_tokens_today`、`quota_exhausted_at`、`quota_exhausted_type`
- `routes_teachers.py` `_LIST_SQL`：改用 `requests_today` 欄位計算配額剩餘，支援新的 `daily_request_limit` / `daily_token_limit` 欄位

---

## [0.7.0] - 2026-04-21

### Added

- **Teacher API 配額監控與管理**
  - `teachers` 表新增 `is_daily_limit_reached` 欄位（標記當日額度耗盡）
  - `teacher_usage_logs` 表新增 `response_status` 欄位（`success` / `quota_exceeded` / `error`）
  - `config.py` 加幂等 migration（`_run_quota_migration`），lifespan 啟動時自動補欄位
  - `_call_gemini_rest` / `_call_openai_compat` 改回傳 `(text, tokens, status)` tuple，捕捉 HTTP 429 / RateLimitError
  - `_call_teacher` 接收 `conn` + `sample_id`，quota_exceeded / error 皆內部寫 log，成功回傳 `tokens_used`
  - `_mark_daily_limit_reached`：helper，標記 teacher 並 WARNING log
  - `is_quota_available` 計數達限時自動呼叫 `_mark_daily_limit_reached`
  - `_pick_available_teacher` 硬性排除 `is_daily_limit_reached=1` 的 teacher
  - `_log_usage` 新增 `tokens_used` / `response_status` optional 參數
  - `background.py` 新增 UTC 00:05 每日重置排程（`_reset_daily_limits`）
  - `routes_teachers.py`：`GET /api/v1/teachers`（LEFT JOIN 當日用量）/ `PATCH /api/v1/teachers/{id}`（修改 daily_limit / is_active）

## [0.6.0] - 2026-04-20

### Added

- **P0-1 Router Telemetry**（採納率追蹤）
  - `layer_0_router/telemetry.py`：`record_decision` / `update_acceptance` / `infer_acceptance_from_text` / `sync_sample_weights`
  - `router_decisions` 表（schema_layer3.sql migration）
  - `router.py` 加 telemetry 寫入與計時，`session_start_hook` 傳入 `session_id`
  - `stop_hook` 新增 `_infer_router_acceptance()`：對話結束後自動語意比對採納狀態

- **P0-2 Shadow Gate**（A/B 上線守門員）
  - `layer_3_pipeline/gatekeeper.py`：本地 Qwen 自評零成本，bootstrap 95% CI + latency ratio 三條件
  - `runner.py` 在 `push_to_ollama` 前插入 gate，未通過回傳 `gate_rejected`

- **P1-1 動態訓練觸發**（取代固定 approved≥30）
  - `layer_3_pipeline/trigger_policy.py`：Ebbinghaus 壁鐘間隔 / 採納退化 / embedding 分布偏移 三信號
  - `runner.py` 改用 `should_trigger()` 決定是否訓練

- **P1-2 多 Judge 投票**（SEAL ReSTEM^EM 精神）
  - `layer_2_chamber/backend/services/multi_judge.py`：三方投票，3票=1.0 / 2票=soft 0.5 / ≤1票=rejected / Shiba採納覆蓋
  - `background.py` 評分排程改用 `multi_judge_score`

- **P1-3 隱性標籤 weight**
  - `training_samples.weight` 欄位（migration, DEFAULT 1.0）
  - `sync_sample_weights`：stop_hook 採納後自動同步 weight（1.0/1.5/2.0）
  - `dataset_formatter.py`：Ebbinghaus 分桶 replay + weight 展開（soft 0.5/正常/×2/×3）

## [0.5.0] - 2026-04-19

### Added

- **Layer 0 路由層**
  - `layer_0_router/classifier.py`：Gemma E2B（gemma3:2b）分類任務 local/claude，ROUTER_TIMEOUT=30s（含 model swap）
  - `layer_0_router/compressor.py`：Gemma E4B（gemma3:4b）壓縮長 RAG context
  - `layer_0_router/router.py`：主協調器，local → compress → Qwen → 注入 🤖 建議；任何失敗靜默 fallback
  - `session_start_hook.py` 整合：router 結果 + RAG context 合併注入
  - 9 個單元測試，全數通過

## [0.4.0] - 2026-04-19

### Added

- **Layer 3 Fine-tuning Pipeline** 全自動化
  - `layer_3_pipeline/db.py`：`finetune_runs` 表 CRUD
  - `layer_3_pipeline/mlx_trainer.py`：呼叫 `mlx_lm.lora` 執行 LoRA 訓練
  - `layer_3_pipeline/gguf_converter.py`：`mlx_lm.fuse` + `convert_hf_to_gguf.py` 轉換 GGUF
  - `layer_3_pipeline/ollama_updater.py`：`ollama create` 更新本地模型
  - `layer_3_pipeline/runner.py`：主協調器，approved≥30 自動觸發完整 pipeline
  - `layer_2_chamber/backend/api/routes_finetune.py`：手動觸發 API（POST /trigger/{block}、GET /runs）
  - `background.py` 新增 `finetune_check` 排程（每 6 小時）
  - `~/.local-brain/schema_layer3.sql`：`finetune_runs` 表定義
  - 11 個單元測試，全數通過

### Fixed

- `stop_hook.py`：新增 session 層級 embedding 補捕，預期 capture 率大幅提升（原 4/15 sessions）
- `rag.py`：cosine similarity 門檻 0.5 → 0.35，提高 RAG 召回率
- `teacher_service.py`：Gemini REST 加 `responseMimeType: application/json`，修復評分 JSON 解析錯誤

## [0.1.0] - 2026-04-17

### Added

- **Layer 1 記憶層**核心實作
  - `layer_1_memory/lib/parser.py`：解析 Claude Code JSONL session 檔案（branch 追蹤、tool_use 偵測）
  - `layer_1_memory/lib/classifier.py`：規則型事件分類器（7 種 event_type）
  - `layer_1_memory/lib/db.py`：SQLite 連線管理、schema 初始化、migration 機制
  - `layer_1_memory/lib/rag.py`：FTS5 記憶查詢與 RAG context 格式化
  - `layer_1_memory/hooks/stop_hook.py`：Claude Code Stop Hook，背景 spawn 同步
  - `layer_1_memory/hooks/sync_session.py`：背景同步主邏輯（parse → classify → upsert DB）
  - `layer_1_memory/hooks/session_start_hook.py`：SessionStart Hook，RAG 注入歷史 context
  - `layer_1_memory/db/schema.sql`：四層 schema（projects / sessions / branches / messages + FTS5）
  - `layer_1_memory/config.yaml`：路徑、閾值設定
  - `layer_1_memory/setup.sh`：一鍵部署腳本（venv、DB 初始化、settings.json hooks 寫入）
- **單元測試** `tests/memory/`：db / parser / classifier / rag 共 18 個測試案例，全數通過

### Changed

- **Layer 1 記憶記錄完整性與成本追蹤補強**
  - 修復 `tool_result` 遭到 `parser.py` 拋棄的問題。
  - `layer_1_memory/db/schema.sql`：在 `messages` 表新增了 8 個欄位。包含 `raw_content` TEXT 欄位，用以保存未經過濾的最原始 JSON 結構；以及 7 個量測數值的欄位：`input_tokens`, `output_tokens`, `cache_creation_input_tokens`, `cache_read_input_tokens`, `char_count`, `byte_count`, `encoding`，全面涵蓋成本與流量追蹤。
  - `layer_1_memory/lib/parser.py`：`_parse_entry` 現在會攔截 `message["content"]` 以及 `message["usage"]` 將其拆解、並且透過 python 計算物理位元組字元數。
  - `layer_1_memory/lib/db.py`：在 `init_db()` 加入 7 項新欄位新增的 Migration 控制；並擴充 `insert_message`。
  - `layer_1_memory/hooks/stop_hook.py`：串接流量追蹤參數至資料庫 `insert_message` 儲存階段。
  - `tests/memory/test_parser.py`：新增驗證單元測試，確保字元數、Token 消耗能被準確萃取與計算。
  - `tests/memory/test_classifier.py`：補上改版遺失的占位符。

- **Layer 1 生命週期與效能優化 (延遲壓縮與工具正規化)**
  - **時間戳與模型紀錄**：於 `messages` 分別新增 `message_time`, `model_name`，讓儀表板可精算真實時間與費率。
  - **工具紀錄正規化 (`tool_executions` 表)**：成功從 `raw_content` 獨立拆分，並使用 `(tool_name, is_error)` 建立索引，方便未來 Layer 2 背景程式毫秒級掃描出問題的 `Bash` 指令。
  - **Application-Level 即時壓縮機制**：引入 Python `zlib`。在寫入 DB 前，如果分析到 `output_log` 或 `raw_content` 的位元組超過 `1024 Bytes`，會直接啟動 `.compress()` 包裝成 `BLOB` 寫入。完全不拖慢背景掛勾且解決硬碟未來爆滿問題，並設有 `is_compressed=1` 的彈性旗標。
