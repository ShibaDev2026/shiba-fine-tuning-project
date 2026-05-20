# config/models — 模型 yaml 設定目錄

每個 yaml 描述**一顆模型 × 一個 role**的完整設定。
Layer 0 推論層與 Layer 3 訓練層在執行期只讀 DB，yaml 是 source of truth，切換或 reload 時才被讀取並寫入 `model_registry` snapshot。

## 現有 yaml 清單

| 檔名 | role | Ollama tag / HF repo |
|---|---|---|
| `classifier-gemma3-4b.yaml` | classifier | `gemma3:4b` |
| `compressor-gemma3-4b.yaml` | compressor | `gemma3:4b` |
| `responder-qwen3-30b-a3b.yaml` | responder | `qwen3:30b-a3b` |
| `responder-qwen36-35b-a3b-nvfp4.yaml` | responder | `qwen3.6:35b-a3b-nvfp4` |
| `training_base-qwen25-7b-instruct-mlx-4bit.yaml` | training_base | `mlx-community/Qwen2.5-7B-Instruct-4bit` |

## 新增模型三步驟

```bash
# 1. 下載模型（推論型）
ollama pull <new-model-tag>

# 2. 寫 yaml（複製最相近的 yaml 修改）
cp config/models/classifier-gemma3-4b.yaml config/models/classifier-<new-tag>.yaml
# 編輯 ollama_tag、display_name、inference 參數、prompt.system

# 3. 切換到新模型（前端 PhaseRouter dropdown，或直接打 API）
curl -X PUT http://localhost:9590/api/v1/router/config \
  -H "Content-Type: application/json" \
  -d '{"key": "classifier_model_yaml", "value": "classifier-<new-tag>"}'
```

訓練型（`training_base`）改用 `hf_repo` 取代 `ollama_tag`，切換後下次訓練觸發即生效。

## yaml schema

### 推論型（classifier / compressor / responder）

```yaml
display_name: 人類可讀名稱
role: classifier           # classifier | compressor | responder
ollama_tag: gemma3:4b      # Ollama 模型 tag（必填）
description: 用途說明

inference:
  think: false             # Ollama 0.9+ think 模式（頂層欄位，非 options 內）
  num_ctx: 4096
  temperature: 0.0
  top_p: 1.0
  top_k: 40
  repeat_penalty: 1.0
  num_predict: 256
  stop: []
  keep_alive: 10m          # 覆寫 OLLAMA_KEEP_ALIVE
  timeout_seconds: 30      # HTTP 呼叫 timeout

prompt:
  system: |
    系統提示詞
  user_template: null      # null = 呼叫端自組；非 null = 用此 template

meta:
  family: gemma            # qwen | gemma | llama | mistral
  quantization: q4_K_M
  size_gb: 3.4
  min_ram_gb: 8
  supports_thinking: true

maintenance:
  yaml_version: 1
  added_at: "YYYY-MM-DD"
  notes: |
    補充說明
```

### 訓練型（training_base）

```yaml
display_name: 人類可讀名稱
role: training_base
hf_repo: mlx-community/Qwen2.5-7B-Instruct-4bit   # HuggingFace repo（必填）
description: 用途說明

training:
  blocks: [1, 2]           # 適用哪些 LoRA block
  num_layers: 16
  learning_rate: 1.0e-4
  batch_size: 4
  iters: 600
  lora_rank_cold: 8        # approved < 50（冷啟動保護）
  lora_rank_warm: 16       # approved >= 50
  chat_template: qwen2_5

meta:
  family: qwen
  parameters_b: 7
  quantization: 4bit
  format: mlx

maintenance:
  yaml_version: 1
  added_at: "YYYY-MM-DD"
```

## 注意事項

- **一份 yaml = 一個 role**：同 model tag 服務多個 role 時，分開寫 yaml 各自調參
- **`think` 放 inference 頂層**，不能放進 options 內（Ollama 0.9+ 規格；放錯 Ollama 忽略，thinking-only 模型會回空 content）
- **yaml 改動不自動生效**，需在前端按「Reload」或呼叫 `POST /api/v1/router/config/reload`
- **DB 是執行時唯一資料源**，yaml 被刪除不炸 production，但無法再切回該 model
