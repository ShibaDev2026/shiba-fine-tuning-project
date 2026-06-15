# 設計：付費 Teacher API → 本地 LM Studio 裁判切換

> 日期：2026-06-16
> 狀態：設計定稿，待寫實作計畫
> 範圍：Layer 2 精神時光屋的 Teacher（評分裁判）provider 切換

---

## 1. 背景與目標

### 1.1 目標
**主要驅動：自主性／去外部依賴。** 讓 Layer 2 的評分裁判不再依賴外部付費 API（Gemini Paid、Claude Sonnet 等），改由本地模型透過 **LM Studio 的 OpenAI 相容 server** 擔任裁判。可接受裁判品質些微下降，換取完全本地化。

### 1.2 前提脈絡（為何可硬切換）
- D1 決策已將 Layer 0/2/3 降為**學習／實驗平台（非投產）**。訓練資料不會直接進產線（L3 為 gated 實驗）。
- 因此本切換**不套產線級嚴謹度**：硬切換、不保留付費裁判作即時校準錨。
- 既有架構 `teacher_service.py` 已支援本地 teacher（`keychain_ref=NULL` 跳過 Keychain、`api_base` 路由到 `OpenAICompatClient`），切換主要是設定與選型，搭配一處小幅 code 改動。

### 1.3 關鍵風險（已知並接受）
- 裁判是**評分閘門**（score 0-10，≥8 算一票 approved；3/3→weight1.0、2/3→0.5、≤1/3→rejected）。本地裁判寬嚴校準若偏移，approved/rejected 邊界隨之偏移。
- 無付費裁判即時對照 → 品質下降幅度無法即時量測，僅能事後從 log 回溯。
- 此風險因 L2 屬實驗平台而被接受。

---

## 2. 架構設計

### 2.1 雙本地 provider 對等
| Provider | api_base | 取得模型 | vendor 標記 | 用途 |
|----------|----------|---------|------------|------|
| Ollama | `http://localhost:11434/v1` | `ollama pull` | `local-ollama` | responder / embedding（維持現狀）|
| **LM Studio** | `http://localhost:1234/v1` | `lms get <hf-repo>` | `local-lmstudio` | **本切換新增：teacher 裁判單一閘道** |

- backend 若在 docker 內，api_base 用 `http://host.docker.internal:1234/v1`（已在 `OpenAICompatClient._LOCAL_HOST_RE` 的 local pattern 內，會正確判定 `source_type=local`）。
- 所有 teacher 呼叫共用既有 `OpenAICompatClient`，差別僅 port 與 `vendor` 標記。
- **Runtime 策略：LM Studio 單一閘道**——三個 active 裁判全走 :1234，由 LM Studio 統一載入/常駐。Ollama 不再承載 teacher。

### 2.2 硬體與常駐
- 硬體：Apple M1 Max / 64GB unified memory。
- 裁判循序投票（`multi_judge._collect_votes` 逐 teacher 取票），峰值記憶體 = 單一最大裁判，64GB 充裕。
- 為避免逐筆樣本 JIT 載入拖慢批次評分，**三個 active 裁判同時常駐 LM Studio**（≈25GB，64GB 容得下）。

---

## 3. 裁判編組（5 模型，三方投票）

### 3.1 選型硬過濾條件
中文強 ∧ 可關 thinking（穩定吐 JSON）∧ 可取得 GGUF ∧ 適配 64GB ∧ 家族多樣性。

> **關鍵洞見**：裁判任務僅需輸出 `{"score":N,"reason":"..."}`。新世代模型多帶 thinking，會吃 `num_predict`、拖慢、並可能污染 JSON 解析。故「能否乾淨關 thinking」是比模型聰明度更優先的硬過濾條件。LM Studio 對 reasoning 模型會把思考放 `reasoning_content`、最終答案放 `content`，需於驗證階段確認 `content` 為乾淨 JSON。

### 3.2 編組
| # | 模型 | 家族 | 中文 | 編組 | 備註 |
|---|------|------|------|------|------|
| 1 | Qwen3.5-27B-GGUF | Qwen | ★★★ | **active** | 主裁判，中文最強 |
| 2 | GLM-4.7-Flash-GGUF | 智譜 GLM | ★★★ | **active** | 真異質家族（LM Studio 解鎖，Ollama 無乾淨小版本）|
| 3 | gemma（gemma3:12b 或已裝 gemma-4-e4b）| Google | ★★ | **active** | 第三家族，抗 Qwen/GLM 相關偏見 |
| 4 | Qwen3.5-9B-GGUF | Qwen 輕量 | ★★★ | bench（`is_active=0`）| 快速替補 |
| 5 | GLM-4.5-GGUF | GLM 備援 | ★★★ | bench（`is_active=0`）| GLM 備援 |

- 來源全部 `lms get` 下載的 HF GGUF；實際 `teacher.model_id` 以 LM Studio `/v1/models` 暴露的識別字為準（實作時查證填入）。
- 5→3 active + 2 bench：bench 列入 DB 但停用，供日後熱替補（呼應「自我改善」可換裁判）。
- **誠實取捨記錄**：LM Studio 解鎖 GLM 後，active 三裁判得以三家族異質（Qwen + GLM + gemma），解決原本 Ollama-only 時被迫塞兩個 Qwen 的多樣性妥協。gemma 中文偏弱，可能與 Qwen/GLM 投票分歧，使 soft-label（2/3）比例上升——可接受。

---

## 4. 停用付費 API（硬切換）

- 在 `setup_teachers.py` 將下列 teacher 設 `is_active=0`，**保留 row 不刪除**（可一鍵回滾、保留歷史 log 供回溯）：
  - Gemini 2.5 Flash、Gemini 2.5 Flash-Lite、Claude Sonnet 4.6、Grok 3 Mini、GitHub Models GPT-4o-mini、Mistral 7B。
- 新增 5 個本地裁判 teacher row（3 active + 2 bench），`keychain_ref=NULL`、`api_base=LM Studio`、`vendor='local-lmstudio'`。
- 切換為設定層異動，無需改 `multi_judge` 投票邏輯（仍取 active teacher 投票）。

---

## 5. 必補的 code 改動（localized）

### 5.1 thinking 控制
- 現況：`OpenAICompatClient.generate()` 送純 OpenAI 請求（`model/messages/max_tokens/temperature`），**未真正關 thinking**；`disable_thinking` 目前只接到 Gemini 路徑。本地 qwen 僅靠 `max_tokens` headroom 硬扛。
- 改動：`OpenAICompatClient.generate()` 新增 `disable_thinking: bool` 參數。
  - Qwen 系：prompt 注入 `/no_think` 軟開關。
  - GLM 系：依其 chat template 的 thinking flag 關閉（實作時查證；LM Studio 可能透過 `reasoning_content` 分流，屆時確認 `content` 乾淨即可）。
  - gemma：無強制 thinking，免處理。
- `teacher_service._call_openai_compat` 對本地裁判帶入 `disable_thinking=True`。
- 範圍：`clients/openai_compat/client.py` + `teacher_service._call_openai_compat`，單一行為、localized。

### 5.2 不變動
- `multi_judge` 投票邏輯、weight 計算、`teacher_usage_logs` schema 皆不動。
- 切換後本地裁判評分照常寫入 `teacher_usage_logs` / `ai_api_call_logs`，作為日後回溯比對的證據（取代 live A/B）。

---

## 6. 運維

- 評分前需 LM Studio server 在線：`lms server start`。
- 三個 active 裁判預先常駐（`lms load` 或 JIT 後保持），避免逐筆 JIT 載入拖慢批次。
- setup / 啟動流程需確保 server 在線（前置檢查 `/v1/models` 可達；不可達時 fail fast 並提示 `lms server start`）。

---

## 7. 交付物

1. `setup_teachers.py` 擴充：新增 5 本地裁判種子 + 停用 6 個付費 teacher（`is_active=0`）。
2. `clients/openai_compat/client.py` + `teacher_service`：thinking 控制小改動。
3. 評估文件：記錄 5 模型過濾評分、thinking/JSON 驗證結果、回滾方式（將付費 teacher `is_active=1` 即復原）。
4. **不做 live A/B**（已選硬切換）。

---

## 8. 副作用清單

- 訓練品質閘門全交本地裁判，無即時付費對照（已接受，因 L2 屬實驗平台）。
- gemma 中文偏弱 → 可能升高 soft-label（2/3）比例。
- LM Studio server 須維持在線 → 多一個運維點；server 未開時評分整批失效（需前置檢查 fail fast）。
- 本地裁判校準未經 golden judge set 驗證（硬切換省略）；若日後發現閘門明顯偏移，回滾路徑為重新啟用付費 teacher。

---

## 9. 驗證標準（Definition of Done）

- `pytest tests/layer2/ -q` 綠（投票邏輯回歸）。
- LM Studio server 在線時，`setup_teachers.py --verify` 對 3 active 裁判各送一筆測試評分，回傳乾淨 JSON `{score, reason}`（驗證 thinking 已關、JSON 可解析）。
- DB 確認：6 付費 teacher `is_active=0`、5 本地裁判存在（3 active + 2 bench）。
- 跑一小批 pending 樣本評分，確認 `teacher_usage_logs` 有本地裁判記錄、`vendor='local-lmstudio'`。
