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
- `hooks/stop_hook.py`：解析對話 → SQLite（sessions / messages / FTS5）+ 採納判定
- `lib/rag.py`：FTS5 全文搜尋 + 向量語意搜尋（BGE-M3，cosine ≥ 0.35）

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

## 自我進化閉環（v0.6.0）

```
對話 → router_decisions（採納率）
     → stop_hook 採納判定 → training_samples.weight 更新（P1-3）
     → multi_judge 三方評分 → approved / soft 0.5 / rejected
     → trigger_policy 動態觸發訓練
     → shadow gate 把關 → ollama 部署
     → 下次對話採納率回饋 → ...
```

## 模型設定

| 用途 | 模型 |
|------|------|
| 分類（Fast） | gemma3:4b（think: false） |
| 壓縮（Primary） | gemma3:4b（think: false） |
| 回應（Response） | qwen3:30b-a3b → shiba-block1 |
| Judge（初裁） | Gemini 2.5 Flash（250 req/day）|

### Teacher 評分池（v0.8.0，priority 順序）

| 優先 | Teacher | 模型 | 每日上限 |
|------|---------|------|---------|
| 0 | Gemini 2.5 Flash | gemini-2.5-flash | 20 req（5 RPM）|
| 1 | Gemini 2.5 Flash-Lite | gemini-2.5-flash-lite | 20 req（10 RPM）|
| 2 | Grok 3 Mini | grok-3-mini | 25 req / 128k token |
| 3 | GitHub GPT-4o-mini | gpt-4o-mini | 150 req / 1.2M token |
| 4 | Mistral 7B | open-mistral-7b | 33M token |
| 5 | Local Qwen 7B | qwen2.5:7b | 無限（最後備援）|

> Local Qwen 7B 設為 priority=5 最後備援，避免模型自評導致的循環依賴。

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
| `sessions` | 對話 session 統計 |
| `messages` | 所有訊息 |
| `branches` | 對話分支（含 decay_score） |
| `exchanges` | 四步循環語意單元（v1.1.0，has_error / has_final_text） |
| `exchange_messages` | exchange ↔ message 橋接（role_in_exchange） |
| `sessions_fts` | FTS5 全文索引 |
| `exchange_embeddings` | 因果對向量（BGE-M3） |
| `training_samples` | 訓練樣本（含 weight，source=layer1_bridge_v2） |
| `router_decisions` | 路由決策與採納率 |
| `finetune_runs` | 訓練執行記錄 |

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

當前版本：**v1.5.0**（2026-05-18）

| 版本 | 日期 | 主要內容 |
|------|------|---------|
| v1.5.0 | 2026-05-18 | SQLite 競態強化（PR1: WAL→DELETE journal, PR2: stop_hook/multi_judge 4段 SAVEPOINT 原子事務）；RAGAS 評估框架（Phase A 完成：golden set 31 筆、UUID 召回基線）；Teacher RPM 速率管理（PR-A/B/C：schema migration、429 分流、排程時程修正至 PT 午夜）|
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
