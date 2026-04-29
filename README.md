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

- `classifier.py`：Gemma E2B（gemma3:2b）任務分類
- `compressor.py`：Gemma E4B（gemma3:4b）壓縮 RAG context
- `router.py`：主協調器，local → 壓縮 → Qwen 推論 → 注入建議
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
| 分類（Fast） | gemma3:2b（think: false） |
| 壓縮（Primary） | gemma3:4b（think: false） |
| 回應（Response） | qwen3:30b-a3b → shiba-block1 |
| Judge（初裁） | Gemini 2.5 Flash（250 req/day）|

### Teacher 評分池（v0.8.0，priority 順序）

| 優先 | Teacher | 模型 | 每日上限 |
|------|---------|------|---------|
| 0 | Gemini 2.5 Flash | gemini-2.5-flash | 250 req |
| 1 | Gemini 2.5 Flash-Lite | gemini-2.5-flash-lite | 1,000 req |
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

## 版本歷程

當前版本：**v1.1.1**（2026-04-29）

| 版本 | 日期 | 主要內容 |
|------|------|---------|
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
