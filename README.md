# shiba-fine-tuning-project

本地 Ollama 模型自我監督進化系統。透過對話記憶累積、自動評分、閉環反饋，讓本地模型逐步接手 Claude 的重複性任務。

## 系統架構

```
┌──────────────────────────────────────────────────────────────┐
│  前端儀表板   Vue 3 + Nginx        localhost:9590             │
│               ↕ /api/* proxy                                  │
│  Layer 0  路由層        Gemma 分類 → local / Claude           │
│  Layer 1  日常記憶層    Stop Hook → SQLite → FTS5 RAG         │
│  Layer 2  精神時光屋    問題集 × Judge → 訓練資料集（:8000）  │
│  Layer 3  訓練管道      MLX LoRA → GGUF → Ollama（:8001）    │
└──────────────────────────────────────────────────────────────┘
```

### Layer 0 — 路由層

每次對話開始時，由 Gemma 分類決定走本地模型或 Claude：

- `classifier.py`：gemma3:4b 任務分類（v1.5.0 起改讀 `model_registry.snapshot` JSON，不再 hardcode）
- `compressor.py`：gemma3:4b 壓縮 RAG context（同上 DB-driven）
- `router.py`：主協調器，local → 壓縮 → Qwen 推論 → 注入建議；offline kill switch 由 `router_config.ollama_status` 控制
- `_config.py`：snapshot 載入 + `is_local_enabled` + `split_inference`（拆出 `keep_alive` / `think` 至 Ollama body 頂層）
- `telemetry.py`：**P0-1** 採納率追蹤，寫入 `router_decisions` 表

### Layer 1 — 日常記憶層

對話結束時自動捕捉，建立可搜尋的長期記憶：

- `hooks/session_start_hook.py`：RAG 記憶注入 + Layer 0 路由整合
- `hooks/session_stop_hook.py`：解析對話 → SQLite（sessions / messages / FTS5）+ 採納判定
- `lib/rag.py`：FTS5 全文搜尋 + 向量語意搜尋（`nomic-embed-text` 768d，cosine ≥ 0.35；bge-m3 升級評估中）

### Layer 2 — 精神時光屋

將對話自動轉化為高品質訓練樣本：

- `extraction/pipeline.py`：Layer 1 橋接 v2（`exchanges` 語意層直接抽取）+ error-repair 路徑
- `services/multi_judge.py`：**P1-2** 三方 Judge 投票（SEAL ReSTEM^EM）
- `extraction/dataset_formatter.py`：Alpaca JSONL 輸出，Ebbinghaus 分桶 replay
- `api/`：FastAPI 監控儀表板 + MCP server

### Layer 3 — Fine-tuning 管道

全自動 LoRA 訓練到 Ollama 部署：

- `trigger_policy.py`：**P1-1** 動態觸發（Ebbinghaus / 採納退化 / 分布偏移）
- `mlx_trainer.py`：MLX LoRA 訓練（rank=8, lr=1e-4）
- `gguf_converter.py`：GGUF 轉換
- `gatekeeper.py`：**P0-2** Shadow A/B Gate（bootstrap CI + latency 三條件）
- `ollama_updater.py`：`ollama create` 部署

## 資料流（hook → fine-tuning → output）

```
┌──────────────────────────────────────────────────────────────────────────┐
│  Claude Code 對話結束（host 端觸發）                                       │
└────────────────────────────────┬─────────────────────────────────────────┘
                                 ▼
┌──────────────────────────────────────────────────────────────────────────┐
│  hooks/session_stop_hook.py   解析 ~/.claude/projects/*.jsonl             │
│     ├─ 4 段獨立事務（PR2 原子化）寫入 SQLite                              │
│     └─ router_decisions.user_accepted（採納判定 / Layer 0 反饋來源）       │
└────────────────────────────────┬─────────────────────────────────────────┘
                                 ▼
┌──── Layer 1 日常記憶層 ──────────────────────────────────────────────────┐
│  A: sessions / messages / branches    基礎對話結構                        │
│  B: exchanges                         四步語意單元（req→tool→resp→final）│
│  C: sessions_fts (FTS5)               中文 trigram 全文索引               │
│  D: exchange_embeddings               nomic-embed-text 768d 向量（RAG）   │
└────────────────────────────────┬─────────────────────────────────────────┘
                                 ▼
┌──── Layer 2 精神時光屋 ──────────────────────────────────────────────────┐
│  extraction/pipeline.py（layer1_bridge_v2 直讀 exchanges）                │
│     └─ training_samples（event_type 標籤 + Ebbinghaus weight）            │
│                                                                          │
│  APScheduler scoring（每小時 minute=3）                                   │
│     └─ services/multi_judge.py 三方 Judge 投票（SEAL ReSTEM^EM）          │
│         ├─ Gemini 2.5 Flash      （主審）                                 │
│         ├─ Claude Sonnet 4.6     （副審）                                 │
│         └─ Qwen3.6 35B Local     （本地審）                               │
│                                                                          │
│  狀態流轉：                                                              │
│     · 共識 approved / soft 0.5 / rejected                                 │
│     · user_accepted=1  →  強制 approved（覆蓋 judge）                     │
│     · Judge 全失敗 / 配額耗盡  →  pending（下輪 scoring job 重試）        │
└────────────────────────────────┬─────────────────────────────────────────┘
                                 ▼
┌──── Layer 3 Fine-tuning 管道（host launchd，MLX 走 MPS） ───────────────┐
│  trigger_policy.py   任一條件觸發：                                       │
│     · 各 block ≥ 30 approved 樣本                                         │
│     · Ebbinghaus 間隔 {1, 2, 4, 7, 15, 30} 日                             │
│     · 採納退化 / 分布偏移（drift alert）                                  │
│            │                                                              │
│            ▼                                                              │
│  mlx_trainer.py      Qwen2.5-7B MLX 4bit + LoRA (rank=8, lr=1e-4)        │
│                      訓練比例 70% 新 approved / 20% 歷史穩定 / 10% 通用集 │
│            │                                                              │
│            ▼                                                              │
│  gguf_converter.py   LoRA  →  GGUF                                       │
│            │                                                              │
│            ▼                                                              │
│  gatekeeper.py       Shadow A/B Gate                                     │
│                      bootstrap CI + latency + retention ≥ 0.85           │
│                      （首次訓練 requires_manual approval，v1.3.0）        │
│            │                                                              │
│            ▼ pass                                                         │
│  ollama_updater.py   ollama create shiba-block1 / shiba-block2           │
└────────────────────────────────┬─────────────────────────────────────────┘
                                 ▼
┌──── 產出 Output ─────────────────────────────────────────────────────────┐
│  · Ollama 內部模型                                                        │
│       shiba-block1   git_ops + terminal_ops + code_gen                   │
│       shiba-block2   debugging + architecture + knowledge_qa + ft_ops    │
│                                                                          │
│  · Layer 0 router 下一輪優先走本地 Qwen + LoRA，Claude 退為 fallback      │
│  · 採納率回饋 router_decisions  →  trigger_policy 下次觸發判斷           │
│                                                                          │
│  最終目標：本地模型逐步接手 Claude 的重複性任務（重複勞動 → 自動化）       │
└──────────────────────────────────────────────────────────────────────────┘
```

## 模型設定

| 用途 | 模型 | yaml |
|------|------|------|
| 分類（Fast） | gemma3:4b（think: false） | `config/models/classifier-gemma3-4b.yaml` |
| 壓縮（Primary） | gemma3:4b（think: false） | `config/models/compressor-gemma3-4b.yaml` |
| 回應（Response） | qwen3:30b-a3b → shiba-block1 | `config/models/responder-qwen3-30b-a3b.yaml` |
| 重型 fallback | qwen3.6:35b-a3b-nvfp4 | `config/models/responder-qwen36-35b-a3b-nvfp4.yaml` |
| Judge（初裁） | Gemini 2.5 Flash（Paid Tier，RPM=500）| — |

> v1.5.0 起所有模型參數 yaml 化，前端 `PhaseRouter` 可即時切換；offline kill switch 由 `router_config.ollama_status` 控制。

### Teacher 評分池（當前 main，DB 實際狀態）

| 優先 | Teacher | model_id | RPM | 每日上限 | 狀態 |
|------|---------|----------|-----|---------|------|
| 0 | Gemini 2.5 Flash | gemini-2.5-flash | 500 | 250 | active |
| 0 | Qwen3.6 35B Local | qwen3.6:35b-a3b-nvfp4 | — | 500 | active |
| 1 | Claude Sonnet 4.6 | claude-sonnet-4-6 | 50 | 999999 | active（Anthropic 無 RPD）|
| 20 | Gemini 2.5 Flash-Lite | gemini-2.5-flash-lite | 2000 | 1000 | active |

> 2026-05-20 升 Gemini Paid Tier 後 RPM 已調整，daily_limit 規格上限為 Flash 5000 / Flash-Lite Unlimited（待 DB backfill）；切換 teacher = 改 DB `api_base + keychain_ref + priority`，零改 code。
>
> **歷史 / 可選 teacher**：早期版本（v0.7~v0.8）曾納入 Grok 3 Mini、GitHub GPT-4o-mini、Mistral 7B、Local Qwen 7B（最後備援）等池子；目前已從 DB 清出，未來可重新啟用。

## LoRA Adapter

| Adapter | 訓練事件類型 |
|---------|------------|
| block1 | git_ops, terminal_ops, code_gen |
| block2 | debugging, architecture, knowledge_qa, fine_tuning_ops |

觸發條件：各 block ≥ 30 approved 樣本，或 Ebbinghaus 間隔 / 採納退化 / 分布偏移任一信號。

## 快速啟動

### 標準啟動（docker-compose，v1.0.0）

```bash
# 1. 環境變數（Ollama 優化，host 需要設定）
export OLLAMA_FLASH_ATTENTION=1
export OLLAMA_MAX_LOADED_MODELS=1
export OLLAMA_KV_CACHE_TYPE=q8_0
export OLLAMA_KEEP_ALIVE=10m

# 2. Layer 1 hooks 安裝（Claude Code 在 host 執行，只需一次）
cd layer_1_memory && bash setup.sh

# 3. Teacher API Key 設定（首次）
python3 layer_2_chamber/scripts/setup_teachers.py --setup

# 4. 啟動前端 + 後端（docker-compose）
docker compose up -d

# 5. Layer 3 host 服務（MLX 需 MPS，不走 docker）
bash setup_layer3_launchd.sh

# 儀表板
open http://localhost:9590
```

### 開發模式（不用 docker）

```bash
# 後端（自專案根執行）
uvicorn layer_2_chamber.backend.main:app --reload --port 8000

# 前端
cd frontend-vue && npm run dev   # proxy → localhost:8000

# 系統診斷
python3 layer_2_chamber/scripts/brain_status.py

# 手動批次評分 pending 樣本
python3 layer_2_chamber/scripts/run_scorer.py

# SQLite 備份
bash scripts/db_backup.sh
```

## 資料庫

路徑：`./data/shiba-brain.db`（專案根相對，v0.9.0 搬遷）— Layer 1–3 共用，實際位置由 `config/shiba.yaml` 決定

> 所有路徑、port、URL 統一讀 `shiba_config.CONFIG`（來源 `config/shiba.yaml`），執行環境透過 `SHIBA_RUNTIME=host|docker` env 區分 Ollama / Layer 3 URL。

主要資料表：

| 表 | 說明 |
|----|------|
| `sessions` / `messages` / `branches` | 對話 session、訊息、分支（含 decay_score） |
| `exchanges` | 四步循環語意單元（v1.1.0，has_error / has_final_text） |
| `exchange_messages` | exchange ↔ message 橋接（role_in_exchange） |
| `sessions_fts` | FTS5 全文索引 |
| `exchange_embeddings` | 因果對向量（`nomic-embed-text` 768d） |
| `training_samples` | 訓練樣本（含 weight，source=layer1_bridge_v2） |
| `router_decisions` / `finetune_runs` | 路由採納率 / 訓練執行記錄 |
| `model_registry` / `router_config` | v1.4.0 模型 yaml 化雙表（版本歷史 + 選擇器）|
| `teachers` / `teacher_usage_logs` | Teacher 評分池 + 配額 log（v0.7~v1.5 累積，含 PR-A 的 rpm_limit/window 欄位）|
| `ai_api_call_logs` | 跨 vendor 統一 AI 呼叫稽核（v1.5.x 後）|
| `retrieval_golden_set` / `evaluation_results` / `evaluation_runs` | RAGAS Phase 0 schema（評估腳本在 `ragas-evaluation` branch）|
| `questions` / `question_sets` / `judge_agreement_logs` / `golden_samples` | Layer 2 評分相關（multi_judge / question pool）|
| `tool_executions` / `branch_messages` / `projects` / `lost_and_found` | 內部記錄表（tool 執行追蹤、孤兒資料回收等）|

## Feature Flags（PR-O 模組化開關）

PR-O 系列重構（2026-05-21~22）將「核心 4-layer 路徑」與「進階／實驗性能力」徹底解耦：
核心路徑（`layer_0_router/` / `layer_1_memory/` / `layer_2_chamber/` / `layer_3_pipeline/` + `config/db/schema_core.sql`）永遠可用且不掛任何 feature；進階能力一律收進 `modules/<name>/`，由 `config/shiba.yaml` 的 `features:` 區塊獨立開關，**全關時系統行為 = 純核心**。

### 啟用機制

1. **註冊**：每個模組在 `modules/<name>/__init__.py` 呼叫 `core.feature_registry.register(FeatureSpec(...))`，宣告 `flag` / `schema_files` / `depends_on` / `init_fn`。
2. **載入**：應用啟動時 `apply_features(conn, enabled_flags=CONFIG.features, ...)` 依拓樸序套用：
   - 跑 schema_files（idempotent `CREATE TABLE IF NOT EXISTS`，加模組前綴避免污染核心）
   - 跑 init_fn（一次性搬舊資料 + `register_hook(name, fn)` 註冊抽象介面）
3. **取用**：核心層只透過 `get_hook("gate" / "trigger" / "judge_score" / "paraphrase" / "compress_context")` 取 callable；hook 為 `None` 即走核心 fallback（無分支爆炸、無 `if CONFIG.features.x` 散落）。
4. **依賴**：`depends_on` 由 registry 強制 fail-fast（如 `ragas_eval` 必須與 `multi_judge_v2` 同開），違反即 `ValueError` 不靜默 skip。

### 7 個 feature 模組

| flag | 模組路徑 | off 行為（核心 fallback） | on 行為（feature on） |
|------|----------|--------------------------|----------------------|
| `shadow_gatekeeper` | `modules/gatekeeper/` | Layer 3 訓練前不做 A/B 守門 | 建 `gatekeeper_golden_samples` + 註冊 `gate` hook，4 條件守門（含 retention_score ≥ 0.85）|
| `golden_retention` | （同上，子能力）| — | `shadow_gatekeeper` 的依賴閘；registry 強制共開 |
| `ebbinghaus_trigger` | `modules/ebbinghaus_trigger/` | 固定 approved ≥ 30 即觸發訓練 | 註冊 `trigger` hook，疊加 Ebbinghaus 時間衰減 + drift signal A/B/C |
| `multi_judge_v2` | `modules/multi_judge_v2/` | v1 三方多數投票（不寫 log）| 建 `multi_judge_v2_agreement_logs` + 註冊 `judge_score` hook，強制 vendor 多樣性 ≥ 2 + 寫 Fleiss κ 紀錄 |
| `ragas_eval` | `modules/ragas/` | 不建 ragas_* 表、不跑 weekly CI | 建 `ragas_evaluation_results` / `ragas_retrieval_golden_set` + 啟用 launchd weekly CI；**depends_on=`multi_judge_v2`** |
| `paraphrase_service` | `modules/paraphrase/` | background `paraphrase` 排程 tick noop | 註冊 `paraphrase` hook，每 15 分鐘為變體不足的 instruction 補同義說法 |
| `advanced_compressor` | `modules/advanced_compressor/` | Layer 0 RAG context 直接截斷（前 300 字 + `...`）| 註冊 `compress_context` hook，呼叫 Gemma snapshot 壓 100 字摘要 |

### 兩段式驗收（每模組強制）

- **Stage A**（all-off）：`modules/<name>/tests/verify_isolation.py` 確認 schema_core 無 feature 表、hook 未註冊、核心路徑不變
- **Stage B**（only-this-on）：feature 表/hook 到位、依賴鏈正確
- **組合矩陣**：`tests/test_pr_o_10_combinatorial.py` 涵蓋 all-off / single-on×4 / dep-pair×2 / dep-violation×2 / all-on 共 10 case

### 開關範例

```yaml
# config/shiba.yaml
features:
  shadow_gatekeeper:   true    # 啟用 Layer 3 A/B 守門
  golden_retention:    true    # ↑ 必須同時開
  ebbinghaus_trigger:  false
  multi_judge_v2:      true    # ragas_eval 的前置
  ragas_eval:          true    # 啟用 RAGAS 評估（+ launchd weekly CI）
  paraphrase_service:  false
  advanced_compressor: false
```

## 文件結構

```
docs/
├── design/        # Layer 0/1/2/3 實裝規格（架構 + phase1 memory + layer 2/3 schema/pipeline）
├── references/
│   ├── papers/    # 學術論文（PAPERS_INDEX.md + 4 篇全文目錄）
│   ├── blogs/     # 第三方技術文章
│   └── git/       # 參考 open-source 專案（Claudest …）
└── archive/       # 一次性報告與過時 plan
    └── plans/     # 從 ~/.claude/plans/ 歸檔的歷史計畫
```

`AGENTS.md` 是對外 AI agent / coding 工具的公開規範入口；`CLAUDE.md` 為專案擁有者的個人補充（不入版控）。

## RAGAS 評估基線（2026-05-18）

> 實作位於 `ragas-evaluation` branch（`evaluation/` 目錄），預計 v1.6.0 隨此 branch merge 進 main。

採用 [RAGAS](https://docs.ragas.io)（Retrieval Augmented Generation Assessment）框架對 Layer 1 RAG 管道進行系統性評估，量化召回品質並建立持續追蹤基線。

### Layer 1 召回指標（UUID 型，@k=3，n=31 queries）

| 指標 | 說明 | 值 |
|------|------|----|
| Recall@3 | ground truth UUID 中被召回的比例（真正率） | **0.744** |
| Precision@3 | 召回 UUID 中屬 ground truth 的比例 | **0.613** |
| Hit@1 | top-1 是否命中任一 ground truth | **0.643** |
| MRR | Mean Reciprocal Rank（第一個命中的排名倒數均值） | **0.762** |

> ctx_relevance（LLM judge 語意相關性）待 Gemini Flash 配額恢復後補齊。

---

## 版本歷程

當前版本：**v1.7.0**（2026-05-22）

| 版本 | 日期 | 主要內容 |
|------|------|---------|
| v1.7.0 | 2026-05-22 | PR-O 系列核心瘦身 + 功能模組化重構（PR-O-1~10）：建 `core/feature_registry.py` + `register_hook/get_hook` 機制；7 個 feature 拆出至 `modules/{gatekeeper, ebbinghaus_trigger, multi_judge_v2, ragas, paraphrase, advanced_compressor}/`；feature 表全加模組前綴（`gatekeeper_*` / `multi_judge_v2_*` / `ragas_*`）；`config/shiba.yaml::features` 區塊統一開關；6 模組 Stage A/B 隔離驗證 + 10 case 組合矩陣全綠；全關 = 純核心 4-layer |
| v1.6.0 | 2026-05-20 | PR-I~N 系列：bge-m3 升級 + 2263 embedding backfill；OllamaClient + source_type；RAGAS Phase A/C 完成（Recall 0.744 / Precision 0.613，Claude 5.48）；PR-N golden set 16→65 + judge noise 治理（temperature=0、n_runs flag）|
| v1.5.0 | 2026-05-20 | 模型 yaml 化重構 Step 3-7 全部完成（Layer 0 三顆推論模型 + Layer 3 訓練 base 解硬寫 + 前端 PhaseRouter dropdown 即時切換 + online/offline kill switch）；SQLite hardening PR1+PR2 全部落地（`shiba_db.py` 統一連線 + PRAGMA 三層對齊 + APScheduler cron 錯開 + WAL→DELETE journal mode + stop_hook 4 段切分 + multi_judge 三欄共一事務） |
| v1.4.0 | 2026-05-07 | 模型 yaml 化重構 Step 1+2：5 份 `config/models/*.yaml` + 專案根 `models_loader.py`；DB 雙表機制（`model_registry` 版本歷史 + `router_config` 選擇器、lifespan idempotent sync）；`PhaseModels.vue` 唯讀頁 4 列 grid；師父 CRUD 8 endpoints + `PhaseTeachers` UI 重構；共用 UI 元件 `Modal`/`ConfirmDialog`/`FormField`/`Toast` + `stores/toast.ts`；`ollama_status` 改走 HTTP API（docker 友善）|
| v1.3.1 | 2026-05-06 | 文件目錄一次性整理（`docs/{design,references,archive}/`）+ `AGENTS.md` 對外規範對齊 v1.3.0 事實；純文件變更不動執行碼 |
| v1.3.0 | 2026-05-04 | Grok 外部審視回應：A（Judge 廠牌多樣性）、C（Retention/Golden Set 防遺忘）、D（首次訓練人工把關）、B（Drift 告警 + 儀表板）；shiba_alert.py 公用告警模組；gatekeeper 第 4 條件 retention_score ≥ 0.85；trigger_policy 首次訓練 requires_manual；routes_finetune manual approve endpoint；新建 10 tests |
| v1.2.0 | 2026-05-01 | A/B/C 三級架構檢視一輪：A3-A5 spec/code 對齊、B1-B7 靜默失效修補（finished_at ISO、threshold 拆耦、try-except 收緊、cold-compress 條件、SAVEPOINT、集中 alert）、C1-C6 效能與正確性（multi_judge early exit、Ebbinghaus 視窗、exchange-level dedup、多維採納啟發式、排程併發保護、keychain_ref nullable）|
| v1.1.2 | 2026-04-30 | A1：router_decisions/finetune_runs DDL 集中至 schema.sql；A2：signal C 分布偏移 embedding 讀取改 json.loads |
| v1.1.1 | 2026-04-29 | 架構 review 修正：migration CHECK bug、Ebbinghaus 時間戳、_has_error_tool 精確比對、router_decisions/finetune_runs init、raw 逾時監控、weight 回饋補齊 |
| v1.1.0 | 2026-04-29 | Layer 1 exchanges 語意層（17,790 筆）、Layer 2 Path A v2（直接讀 exchanges 取代 state machine）、A/B 對比腳本 |
| v1.0.0 | 2026-04-25 | Vue 3 + Vite 前端、docker-compose（nginx:9590 + FastAPI:8000）、Layer 3 launchd 獨立服務、端對端驗證全通過 |
| v0.9.0 | 2026-04-24 | 設定集中化（`config/shiba.yaml`）、DB 搬入 `./data/`、後端 docker 化、儀表板 API 完整 |
| v0.8.0 | 2026-04-21 | Teacher 擴充（6 個評分池）、Token 維度配額、LaunchD 常駐、冷啟動保護 |
| v0.7.0 | 2026-04-21 | Teacher 配額監控（每日重置排程）|
| v0.6.0 | 2026-04-20 | 自我監督閉環（P0-1 Telemetry / P0-2 Shadow Gate / P1-1 動態觸發 / P1-2 多 Judge / P1-3 weight）|
| v0.5.0 | 2026-04-19 | Layer 0 路由層（Gemma 分類 + 壓縮）|
| v0.4.0 | 2026-04-19 | Layer 3 Fine-tuning Pipeline（MLX LoRA → GGUF → Ollama）|
| v0.1.0 | 2026-04-17 | Layer 1 記憶層 + Layer 2 精神時光屋 基礎架構 |

詳見 [CHANGELOG.md](CHANGELOG.md)

---

## 參考來源

### 學術論文

| # | 論文 | arXiv | 對應設計 |
|---|------|-------|---------|
| 1 | **Self-Evolving LLMs via Continual Instruction Tuning** (MoE-CL) | [2509.18133](https://arxiv.org/html/2509.18133v4) | Layer 3 雙 LoRA expert（block1/block2）+ shared expert 架構；LoRA rank=8, lr=1e-4 |
| 2 | **SEAL: Self-Adapting Language Models** | [2506.10943](https://arxiv.org/html/2506.10943) | Layer 2 ReSTEM^EM 三方 Judge 投票；只保留高信心樣本的 SFT 策略 |
| 3 | **From RAG to Memory** (HippoRAG 2) | [2502.14802](https://arxiv.org/html/2502.14802v1) | Layer 1 RAG 升級路徑；FTS5 → embedding + 知識圖譜的演進方向 |
| 4 | **FOREVER: Forgetting Curve Memory Replay** | [2601.03938](https://arxiv.org/html/2601.03938v1) | Layer 3 Ebbinghaus 間隔 {1,2,4,7,15,30} 日觸發訓練；70/20/10 訓練比例；記憶緩衝區 2% 上限 |

### 開源專案

| 專案 | 作者 | 用途 |
|------|------|------|
| [Claudest](https://github.com/gupsammy/claudest) | @gupsammy | Layer 1 Stop Hook 架構參考（claude-memory plugin 設計靈感） |

### 技術文章

| 標題 | 來源 | 用途 |
|------|------|------|
| [How my $600 Mac Mini Runs a 35B AI Model](https://x.com/leopardracer/status/2043631410045452360) | @leopardracer | 本地 Mac 運行 35B 模型的環境配置參考（Ollama + llama.cpp 調優） |

### 外部資源

** 與國立中央大學資訊工程學系 人工智慧與知識系統實驗室 黃鈺晴（Anna Huang）博士後研究員 (e-mail：anna.yuqing@gmail.com)進行平台提升討論 **
- **2026-05-17**：討論平台改善空間，建議採用 [RAGAS](https://docs.ragas.io)（Retrieval Augmented Generation Assessment）——對 RAG 評估、測試和優化大型語言模型（LLM）中檢索增強生成（RAG）管道的開源框架，藉此降低 RAG 幻覺、提升 RAG 與 LLM 整體品質。

- **2026-05-18**：調整後完成 UUID 型基線評估。指標結果如下：

  | 指標 | 說明 | 值 |
  |------|------|----|
  | uuid_recall@k | ground truth UUID 中被召回的比例（真正率） | 0.744 |
  | uuid_precision@k | 召回 UUID 中屬 ground truth 的比例 | 0.613 |
  | hit@1 | top-1 是否命中任一 ground truth | 0.643 |
  | mrr | Mean Reciprocal Rank（第一個命中的排名倒數均值） | 0.762 |
  | ctx_relevance | LLM judge 評分：召回的文字片段對 query 的語意相關性 | 待補 |
