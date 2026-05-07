# 模型 yaml 化 + 前端彈性切換

## Context

**問題**：當下載新 Ollama 模型想接入本專案時，目前需手動改 4 處 hardcode（`classifier.py:13`、`compressor.py:12`、`router.py:17`、`mlx_trainer.py:17-20` / `gguf_converter.py:10-13`），易遺漏且無前端可見性。training_samples schema 已驗證**完全解耦**（40 筆抽樣零 chat template 污染），代表「換 base model 不重收資料」這條路打通了，瓶頸只剩在「模型引用層」。

**目標**：把 Layer 0 三顆推論模型 + Layer 3 訓練 base 全部 yaml 化，並在前端做 dropdown 切換 + online/offline kill switch，讓「下載新模型 → 寫 yaml → 即可使用 / 訓練」變成標準流程。

**範圍決策**（已與使用者確認）：
- IN：Layer 0 classifier / compressor / responder（前端可切）+ Layer 3 訓練 base（yaml 化但前端不切）
- OUT：模式選擇器（記入未來工作）、Layer 1 embedder 切換（會讓 exchange_embeddings 失效）
- 切換生效：DB flag 即時生效（首次切換會 trigger Ollama swap ~30s）
- Offline 語意：停用 local，全走 Claude（kill switch）

## 執行偏離記錄

- **2026-05-07 Step 1**：loader 位置從 `config/models_loader.py` 改為專案根 `models_loader.py`。理由：與 `shiba_config.py` 並列（兩者皆為 yaml 載入器），保持 `config/` 純放 yaml 不混 .py；`from models_loader import MODELS` 與 `from shiba_config import CONFIG` 形成對稱。後續 Step 3-6 的 import 路徑全部以此為準。
- **2026-05-07 Step 1**：新增第 5 份 yaml `responder-qwen36-35b-a3b-nvfp4.yaml`（使用者要求接入 35B 模型，但採用機器既有的 `qwen3.6:35b-a3b-nvfp4` 而非新下載 Qwen3.5）。Smoke test 通過：Ollama 0.21.0 + 既有 MLX dylib 環境下 nvfp4 模型可正常推論。

## 既有可重用資產（Phase 1 探索結果）

| 檔案 | 用途 |
|---|---|
| `shiba_config.py:160` | `CONFIG: _Config = _load_config()` module-level singleton pattern，新 model loader 仿此寫 |
| `frontend-vue/src/api/client.ts` | API base 已封裝，新 `router.ts` 直接擴用 |
| `frontend-vue/src/stores/toast.ts` | pinia store 範本 |
| `components/shared/{Btn, Modal, Toast, FormField, ConfirmDialog}.vue` | UI 元件齊備（缺 Select） |
| `routes_router.py` 6 個既有端點 | `/status` 與 `/decisions` 結構成熟，新端點貼同 pattern |
| `dataset_formatter.py:84-90` | JSONL Alpaca 格式輸出，已驗證模型無關 |

## Step Plan

### Step 1：model yaml schema + loader

#### 設計原則
- **一份 yaml = 一個 model × 一個 role**：同一顆 `gemma3:4b` 同時服務 classifier 與 compressor 時，**寫兩份 yaml**（`classifier-gemma3-4b.yaml` 與 `compressor-gemma3-4b.yaml`），各自獨立調 `think / num_ctx / temperature / system prompt`。理由：兩個 role 的行為需求不同，硬綁同一份配置會逼 code 端寫 if-else override，違背 yaml 化初衷。
- **檔名 = role + tag**：`<role>-<ollama_tag_safe>.yaml`，slash 換 dash（`gemma3:4b` → `gemma3-4b`）。檔名 stem 就是 DB 存的識別字串。
- **role 是 enum 單值**，不是 array：`classifier | compressor | responder | training_base`（embedder 暫不納入但保留 enum 位）。

#### Layer 0 推論型 schema（範本）
```yaml
# config/models/classifier-gemma3-4b.yaml
# ─── 識別 ───
display_name: Gemma 3 4B (Classifier)
role: classifier                   # 單一角色 enum
ollama_tag: gemma3:4b              # 必填（Layer 0/1 推論用）
description: 規則型事件分類，極輕極快

# ─── 推論參數（呼叫 Ollama /api/chat 時帶入）───
inference:
  think: false                     # think mode 開關
  num_ctx: 4096                    # 上下文窗
  temperature: 0.0
  top_p: 1.0
  top_k: 40
  repeat_penalty: 1.0
  num_predict: 256                 # 此 role 預期最大輸出 token
  stop: []                         # 額外停止字串
  keep_alive: 10m                  # 覆寫 OLLAMA_KEEP_ALIVE（per-model）
  timeout_seconds: 30              # HTTP 呼叫 timeout（涵蓋首次 model swap）

# ─── Prompt 配置 ───
prompt:
  system: |
    你是嚴格的事件分類器，只回傳 JSON。
  user_template: null              # null = 由呼叫端組裝；非 null = 用此 template 套參數

# ─── 模型元資料（顯示 + 硬體適配檢查）───
meta:
  family: gemma                    # qwen | gemma | llama | mistral —— 影響 chat template
  quantization: q4_K_M
  size_gb: 3.4
  min_ram_gb: 8
  supports_thinking: true
  supports_vision: false
  supports_audio: false

# ─── 維護 ───
maintenance:
  yaml_version: 1
  added_at: "2026-05-07"
  notes: |
    Layer 0 classifier 專用。compressor 另見 compressor-gemma3-4b.yaml。
```

#### Layer 3 訓練型 schema（範本）
```yaml
# config/models/training_base-qwen25-7b-instruct-mlx-4bit.yaml
display_name: Qwen2.5 7B Instruct (MLX 4bit)
role: training_base
hf_repo: mlx-community/Qwen2.5-7B-Instruct-4bit   # 必填（取代 ollama_tag）
description: Layer 3 LoRA 訓練 base（block1 + block2 共用）

# ─── 訓練參數 ───
training:
  blocks: [1, 2]                   # 此 base 適用哪些 LoRA block
  num_layers: 16
  learning_rate: 1.0e-4
  batch_size: 4
  iters: 600
  lora_rank_cold: 8                # approved < 50（F2 冷啟動保護）
  lora_rank_warm: 16               # approved >= 50
  chat_template: qwen2_5           # 訓練時應用的 chat template 識別

# ─── 元資料 ───
meta:
  family: qwen
  parameters_b: 7
  quantization: 4bit
  format: mlx
  size_gb: 4.5
  min_ram_gb: 16

maintenance:
  yaml_version: 1
  added_at: "2026-05-07"
  notes: F2 冷啟動由 lora_rank_cold/warm 控制
```

#### Loader 設計
- 新增 `config/models_loader.py`，仿 `shiba_config.py:160` 的 module-level singleton：
  - `MODELS.list_all() -> list[ModelConfig]`
  - `MODELS.by_role(role: str) -> list[ModelConfig]`（dropdown 用）
  - `MODELS.get_by_stem(stem: str) -> ModelConfig`（DB 存 stem，code 反查）
  - `MODELS.reload()`（檔案系統變動時呼叫）
- 載入時驗 schema：role enum 合法、必填欄位齊全、ollama_tag 與 hf_repo 至少一個有值（依 role 決定）

#### 預先要寫的 yaml（4 份）
- `classifier-gemma3-4b.yaml`
- `compressor-gemma3-4b.yaml`（與 classifier 同 model，但獨立調 prompt/temperature）
- `responder-qwen3-30b-a3b.yaml`（Layer 0 主力）
- `training_base-qwen25-7b-instruct-mlx-4bit.yaml`（Layer 3）

**/model: Opus, /effort: high**（schema 是長期合約，定錯之後重整成本高 — 升 model + effort）

---

### Step 2：DB 加 router_config 表（含 yaml snapshot）

#### 設計原則（與使用者確認）
- DB 是執行階段唯一資料源 — Layer 0 / Layer 3 只讀 DB 不讀 yaml
- yaml 是 source of truth，但**只在「切換」或「reload」時被讀取**並把關鍵欄位快照進 DB
- yaml 被刪除 / 改名 不會炸 production；yaml 被修改需手動觸發 reload 才生效（取捨：杜絕「改完忘了 reload 神不知鬼不覺生效」的混亂）

#### Schema
```sql
CREATE TABLE router_config (
  key          TEXT PRIMARY KEY,            -- e.g. classifier_model_yaml / local_enabled
  value        TEXT NOT NULL,               -- stem（純識別字串，e.g. classifier-gemma3-4b）
  snapshot     TEXT,                        -- JSON：yaml 解析後的關鍵欄位（boolean key 此欄為 NULL）
  snapshot_at  TIMESTAMP,                   -- snapshot 寫入時間
  updated_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

#### Snapshot JSON schema（per role）
**Layer 0 推論型**（classifier / compressor / responder）：
```json
{
  "yaml_stem": "classifier-gemma3-4b",
  "ollama_tag": "gemma3:4b",
  "display_name": "Gemma 3 4B (Classifier)",
  "inference": {
    "think": false, "num_ctx": 4096, "temperature": 0.0,
    "top_p": 1.0, "top_k": 40, "repeat_penalty": 1.0,
    "num_predict": 256, "stop": [], "keep_alive": "10m",
    "timeout_seconds": 30
  },
  "prompt": { "system": "你是嚴格的事件分類器…", "user_template": null },
  "meta": { "family": "gemma", "supports_thinking": true }
}
```

**Layer 3 訓練型**：
```json
{
  "yaml_stem": "training_base-qwen25-7b-instruct-mlx-4bit",
  "hf_repo": "mlx-community/Qwen2.5-7B-Instruct-4bit",
  "training": { "num_layers": 16, "learning_rate": 1.0e-4, "batch_size": 4,
                "iters": 600, "lora_rank_cold": 8, "lora_rank_warm": 16,
                "chat_template": "qwen2_5" },
  "meta": { "family": "qwen", "format": "mlx" }
}
```

#### 預設資料
```sql
-- 切換型（含 snapshot）
INSERT INTO router_config(key, value, snapshot, snapshot_at) VALUES
  ('classifier_model_yaml', 'classifier-gemma3-4b', '<JSON>', CURRENT_TIMESTAMP),
  ('compressor_model_yaml', 'compressor-gemma3-4b', '<JSON>', CURRENT_TIMESTAMP),
  ('responder_model_yaml',  'responder-qwen3-30b-a3b', '<JSON>', CURRENT_TIMESTAMP),
  ('training_base_block1_yaml', 'training_base-qwen25-7b-instruct-mlx-4bit', '<JSON>', CURRENT_TIMESTAMP),
  ('training_base_block2_yaml', 'training_base-qwen25-7b-instruct-mlx-4bit', '<JSON>', CURRENT_TIMESTAMP);

-- 純 boolean / 數字型（snapshot 留 NULL）
INSERT INTO router_config(key, value) VALUES
  ('local_enabled', '1');
```

> migration 腳本要在執行時即時讀 yaml 解析後寫入 snapshot — 避免硬寫過期 JSON。

#### Helper 設計（`layer_0_router/_config.py`）
- `load_active_snapshot(role: str) -> dict`：讀 `router_config.<role>_model_yaml.snapshot` 解析 JSON 回傳，含 50ms in-process cache
- `is_local_enabled() -> bool`：讀 `router_config.local_enabled`
- `set_active_model(role: str, stem: str) -> None`：
  1. 驗 stem 對應 yaml 存在 + role 匹配
  2. 解析 yaml → 產生 snapshot JSON
  3. atomic transaction 寫 value + snapshot + snapshot_at
  4. invalidate cache

**/model: Opus, /effort: medium**（含 snapshot 序列化邏輯，定錯影響後續所有 request）

---

### Step 3：Layer 0 三檔改寫
- `layer_0_router/classifier.py:13`：`CLASSIFIER_MODEL = "gemma3:4b"` → `snap = load_active_snapshot("classifier")`，由 snap 取 `ollama_tag` + `inference.*` + `prompt.system`
- `layer_0_router/compressor.py:12`：同上
- `layer_0_router/router.py:17`：同上 + 前置 `is_local_enabled()` 檢查（False → 直接 return None 走 Claude）
- 三處**只讀 DB snapshot 不讀 yaml**（執行階段絕緣）
- helper `layer_0_router/_config.py` 已於 Step 2 設計
- **TDD**：先寫測試假設 hardcode 環境，再改成讀 snapshot，確保既有行為不破壞 — **強制啟用 `superpowers:test-driven-development` skill**

**/model: Opus, /effort: medium**（生產路徑 hot path，要驗證 fallback）

---

### Step 4：Backend API（routes_router.py 擴充）
- `GET /router/models/installed`：proxy Ollama `/api/tags`，與所有 `config/models/*.yaml` 比對：
  - `yaml_configured`：yaml `ollama_tag` 對應的 model 在 Ollama 已安裝
  - `yaml_orphan`：yaml 有，Ollama 沒下載 → dropdown 灰選 + tooltip「未下載」
  - `installed_no_yaml`：Ollama 有但無對應 yaml → dropdown 灰選 + tooltip「需建 yaml」
- `GET /router/models/by-role?role=classifier`：回該 role 所有 yaml 清單，每筆含 `{stem, display_name, ollama_tag, status}`（給 dropdown 直接渲染用）
- `PUT /router/config`：body `{key, value}`：
  1. 驗 stem 對應 yaml 存在
  2. 解析 yaml 生成 snapshot JSON
  3. atomic 寫 value + snapshot + snapshot_at + updated_at
  4. invalidate in-process cache
- `POST /router/config/reload`：body `{key}` 重新讀 yaml 寫 snapshot（不換 stem）— 給「改完 yaml 想立即生效」用
- 改 `GET /router/status`：回傳每個 role 的當前 stem + snapshot.display_name + snapshot_at + yaml 檔現存狀態（讓前端顯示「⚠️ yaml 已修改但未 reload」徽章；比對方式：yaml 檔 mtime > snapshot_at）

**/model: Sonnet, /effort: medium**

---

### Step 5：前端 UI（PhaseRouter.vue + 新增 store/api）
- 新元件 `components/shared/Select.vue`（共用 dropdown，支援 disabled options + tooltip）
- 新檔 `frontend-vue/src/api/router.ts`：封裝 4 個 router 端點
- 新檔 `frontend-vue/src/stores/router.ts`：當前選擇、可選清單、loading 狀態
- 改 `frontend-vue/src/views/PhaseRouter.vue` 的系統狀態列（現 L223-259）：
  - `Ollama online/offline` → ToggleSwitch（綁 `local_enabled`）
  - `classifier_model` 顯示 → 改 Select dropdown
  - `local_model` 同上
  - 補上 `compressor_model` Select（目前 UI 沒顯示）
  - 每個 dropdown 旁顯示「⚠️ yaml 已修改」徽章（當 yaml mtime > snapshot_at），帶 [Reload] 按鈕觸發 `POST /router/config/reload`
  - 切換時 toast「載入中（首次切換需等 Ollama swap，~30s）」

**/model: Sonnet, /effort: medium**

---

### Step 6：Layer 3 base yaml 化
- 改 `layer_3_pipeline/mlx_trainer.py:17-20` 的 `BASE_MODELS` dict → 改讀 `router_config.training_base_blockN` → 查 yaml `hf_repo`
- 改 `layer_3_pipeline/gguf_converter.py:10-13` 同上
- 不做前端 UI（範圍外），純 yaml + DB 切換

**/model: Sonnet, /effort: low**（hardcode → yaml 字串替換）

---

### Step 7：文件 + CHANGELOG
- 新增 `config/models/README.md`：說明 yaml schema + 「新增 model 三步驟」（pull → 寫 yaml → DB set）
- 更新 `CLAUDE.md` 技術選型表，每 model 標註對應 yaml 路徑
- `CHANGELOG.md` 加 v1.4.0 entry（SemVer minor，新功能）

**/model: Haiku, /effort: low**

---

## 驗證計畫（每 step 完成後執行）

| Step | 驗證手段 |
|---|---|
| 1 | `python -c "from config.models_loader import MODELS; print(MODELS.list_all())"` 列出 4 顆 |
| 2 | `verify-shiba-db` skill 驗 router_config 6 row + 每 row snapshot JSON 可解析、ollama_tag 與 yaml 一致 |
| 3 | `pytest layer_0_router/tests/`（既有測試需 100% 通過）+ 手動發 1 個 request 驗 DB classifier_model_used 欄位 |
| 4 | `curl /api/v1/router/models/installed` 比對 `ollama list` 結果一致 |
| 5 | 開 `/router` 頁切換 classifier，驗 30s 內生效 + DB snapshot 即時更新 + 下個 decision 用新 model；手動改一個 yaml 檔，驗前端出現「yaml 已修改」徽章；按 Reload 後徽章消失；切 offline 驗 router 直接回 Claude（不寫 local 決策） |
| 6 | 跑 mock 訓練 dry-run，確認 base model 從 yaml 取（log 印 `mlx-community/Qwen2.5-7B-Instruct-4bit`） |
| 7 | `git diff CLAUDE.md` 與 README.md 內容檢視 |

驗證收尾統一派 **Explore agent** 對照 plan 各 step 是否落實（讀 DB + 讀檔即可）。

---

## 未來工作（本次不做，記錄）

1. **模式選擇器**：建議注入（現行）/ Shadow mode / Pre-classification / 直接回應 / 依 event_type 分流 — UI 需多一個 dropdown，後端 router 邏輯重構
2. **Layer 1 embedder yaml 化**：須配套 exchange_embeddings 重建 + 維度檢查
3. **Resilience chain**：Claude 掛 → local fallback（leopardracer 路線）
4. **shiba-block* 自動 yaml 寫入**：Layer 3 ollama_updater 訓完模型後自動產生對應 yaml + DB 升級新版本

---

## 全程使用 plugin / skill

| Skill | 用途 |
|---|---|
| `shiba-dev-cycle` | 每進入新 Step 前先 invoke（plan→discuss→agree→implement→verify→continue） |
| `verify-shiba-db` | Step 2 / 3 / 5 後驗 DB 狀態 |
| `superpowers:test-driven-development` | Step 3 強制走 TDD（生產 hot path） |
| `superpowers:verification-before-completion` | 每 step claim 完成前驗證 |

---

## Critical Files

**新增**：
- `config/models/classifier-gemma3-4b.yaml`
- `config/models/compressor-gemma3-4b.yaml`
- `config/models/responder-qwen3-30b-a3b.yaml`
- `config/models/training_base-qwen25-7b-instruct-mlx-4bit.yaml`
- `config/models/README.md`
- `config/models_loader.py`
- `data/migrations/202605xx_router_config.sql`
- `layer_0_router/_config.py`
- `frontend-vue/src/components/shared/Select.vue`
- `frontend-vue/src/api/router.ts`
- `frontend-vue/src/stores/router.ts`

**修改**：
- `layer_0_router/{classifier, compressor, router}.py`（解硬寫）
- `layer_2_chamber/backend/api/routes_router.py`（+3 端點，改 1 端點）
- `layer_3_pipeline/{mlx_trainer, gguf_converter}.py`（讀 yaml）
- `frontend-vue/src/views/PhaseRouter.vue`（系統狀態列改造）
- `CLAUDE.md` / `CHANGELOG.md`

**禁動**：
- `layer_1_memory/lib/embedder.py`（embedder 範圍外）
- training_samples 表（已驗證解耦，不需改）
- `shiba_config.py`（既有 CONFIG 不擴充，新 MODELS 獨立 singleton）
