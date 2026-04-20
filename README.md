# shiba-fine-tuning-project

本地 Ollama 模型自我監督進化系統。透過對話記憶累積、自動評分、閉環反饋，讓本地模型逐步接手 Claude 的重複性任務。

## 系統架構

```
┌─────────────────────────────────────────────────────────┐
│  Layer 0  路由層        Gemma 分類 → local / Claude      │
│  Layer 1  日常記憶層    Stop Hook → SQLite → FTS5 RAG    │
│  Layer 2  精神時光屋    問題集 × Judge → 訓練資料集       │
│  Layer 3  訓練管道      MLX LoRA → GGUF → Ollama         │
└─────────────────────────────────────────────────────────┘
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

- `extraction/pipeline.py`：Layer 1 橋接（自動抽取）+ error-repair 路徑
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
| Judge（初裁） | Gemini 2.5 Flash（免費 250 req/day） |

## LoRA Adapter

| Adapter | 訓練事件類型 |
|---------|------------|
| block1 | git_ops, terminal_ops, code_gen |
| block2 | debugging, architecture, knowledge_qa, fine_tuning_ops |

觸發條件：各 block ≥ 30 approved 樣本，或 Ebbinghaus 間隔 / 採納退化 / 分布偏移任一信號。

## 快速啟動

```bash
# 環境變數（Ollama 優化）
export OLLAMA_FLASH_ATTENTION=1
export OLLAMA_MAX_LOADED_MODELS=1
export OLLAMA_KV_CACHE_TYPE=q8_0
export OLLAMA_KEEP_ALIVE=10m

# Layer 1 hooks 安裝
cd layer_1_memory && bash setup.sh

# Layer 2 背景服務
cd layer_2_chamber/backend
uvicorn main:app --reload --port 8000

# 手動觸發評分
python3 -m layer_2_chamber.backend.core.background score_pending

# 手動觸發訓練（block 1）
python3 -m layer_3_pipeline.runner --block 1 --force
```

## 資料庫

路徑：`~/.local-brain/shiba-brain.db`（Layer 1–3 共用）

主要資料表：

| 表 | 說明 |
|----|------|
| `sessions` | 對話 session 統計 |
| `messages` | 所有訊息 |
| `sessions_fts` | FTS5 全文索引 |
| `exchange_embeddings` | 因果對向量（BGE-M3） |
| `training_samples` | 訓練樣本（含 weight） |
| `router_decisions` | 路由決策與採納率 |
| `finetune_runs` | 訓練執行記錄 |

## 版本

當前版本：**v0.6.0**（2026-04-20）

詳見 [CHANGELOG.md](CHANGELOG.md)
