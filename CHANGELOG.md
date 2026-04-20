# Changelog

所有版本變更依照 [Keep a Changelog](https://keepachangelog.com/zh-TW/1.0.0/) 格式記錄。
版本號遵循 [Semantic Versioning](https://semver.org/lang/zh-TW/)。

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
