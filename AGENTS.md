# shiba-fine-tuning-project — 專案規範（外部 AI 助手讀本）

> 本檔為對外 agent / coding 工具的規範入口。專案擁有者（Shiba）的 Claude Code 個人補充見 `CLAUDE.md`（不在版控內）。事實內容與 `CLAUDE.md` 同步。

## 專案目的
主線（2026-06-21 重定向）：從與 AI 助手對話累積「**驗證過的指令模式**」→ RAG/Agentic 召回 → 本地模型 in-context 代理執行（依擁有者使用習慣）。**fine-tuning 退為後期選項**（Pattern Library 夠大 + 確認高頻重複模式，才壓進權重）。
> 重定向依據：fine-tune 訓練資料 harvest 撞牆（5 條路在現有資料全證不通——真實 output 非答案形狀、採納訊號是 auto 啟發式非人工 gold、語料被 branch over-merge 灌水 ~6.8×）；RAG 召回是唯一實證可行資產。從「累積資料→訓練模型」改為「累積驗證模式→召回+in-context 執行」。詳見 `docs/roadmap/2026-06-21-rag-augmented-execution.md`。

## 運作宗旨：Harness Engineering 自主開發迴圈
全自主、無沙盒、證據驅動、自我進化，持續推進 roadmap 直到達標：
- **base-assumption-first**：建任何基礎建設前，先用最小本地實驗（~$0）證偽/證實前提；gate 不過就停、不建。
- **校準**：重大決策點與宣告完成前，找更強的 reviewer 校準（擋過度宣稱／錯誤母體／錯誤前提）。
- **證據留痕**：`experiments/<date>_<slug>/RESULT.md`；負結果照實寫、不裝飾。
- **階段帶 gate**：過了才進下一階段；不在失敗 gate 上加碼。
- **自我進化迴圈**：每次工作推進 roadmap 一格 → 更新進度記錄 → 設好下一個 gate；持續循環逼近目標。
- **危險操作**仍守確認規則（見「shiba-brain-ft 安全機制」）。

## 系統架構（四層）

| Layer | 名稱 | 功能 |
|-------|------|------|
| 0 | 路由層 | Gemma 分類 → 決定走本地或外部 AI 助手，壓縮 context |
| 1 | 日常記憶層 | 對話結束 hook 捕捉訊息 → SQLite → FTS5 RAG 注入 |
| 2 | 精神時光屋 | 問題集 × AI 師父 → 自動評分 → 訓練資料集 |
| 3 | Fine-tuning Pipeline | MLX LoRA → GGUF → Ollama 更新 |

**Layer 新角色（2026-06-21 重定）**：L0 路由 ✅ 保留；L1 記憶 RAG ✅ **升級主引擎**（Agentic RAG 召回模式給模型執行）；L2 chamber ♻️ **轉 Verifier**（執行前安全閘）；L3 fine-tune ⬇️ **降後期**（壓高頻模式進權重）。

## Roadmap：RAG-augmented 代理執行（主線）

執行迴圈：對話 →[蒸餾] **Pattern Library**（RAG 索引）←[飛輪] 擁有者刻意採納 +1 gold；任務 →[L0 路由本地]→[Agentic RAG 召回模式]→[本地 in-context 提案]→[Verifier 閘]→ 執行 → 回饋飛輪。

| 階段 | 內容 | Gate |
|------|------|------|
| P1 | Pattern Library + manual-accept 飛輪 | 先量指令重複頻率(EV) + 採納摩擦夠低 |
| P2 | Agentic 召回 + in-context 執行 | 召回模式能讓本地正確執行 |
| P3 | Verifier(propose-check-execute) | 擋危險/錯誤、不過度阻擋 |
| P4 | D4 修復 + 歷史回填(按需) | 6.8× 灌水去重後回填 |
| P5 | fine-tune(後期選配) | Library 大 + 高頻模式穩定才壓權重 |

設計約束：**13% 採納天花板** → 本地只接手高信心模式、其餘優雅回退外部 AI 助手。詳見 `docs/roadmap/2026-06-21-rag-augmented-execution.md`。

## 統一 DB
路徑：`./data/shiba-brain.db`（Layer 1 + 2 + 3 共用，v1.0.0 起從 `~/.local-brain/` 移入專案 `data/`，由 docker-compose 掛載）

## Ollama 環境變數（必要）
```bash
export OLLAMA_FLASH_ATTENTION=1
export OLLAMA_MAX_LOADED_MODELS=1
export OLLAMA_KV_CACHE_TYPE=q8_0
export OLLAMA_KEEP_ALIVE=10m
```

## 技術選型（模型決策）

| 層 | 模型 | 備註 |
|----|------|------|
| Fast（分類） | gemma3:4b | think: false 必須關閉 |
| Primary（壓縮） | Gemma E4B | think: false |
| Response（中文回應） | Qwen2.5 7B ft → 升 32B | — |
| Heavy（fallback） | Qwen 35B | llama.cpp，64GB |
| Judge 初裁 | Gemini 2.5 Flash | 免費，無循環依賴 |

## shiba-brain-ft 安全機制
以下操作強制回呼叫者（用戶或上層 AI 助手）確認，不得自行執行：
- 檔案系統：`rm / rmdir / mv / chmod +x / chown`
- Git：`reset --hard / clean -f / rebase`（branch/tag 操作允許）
- Docker：`rm / system prune / volume rm`
- 覆蓋已存在的非暫存檔案

## Fine-tuning 規範
> ⬇️ **2026-06-21 降為 Roadmap P5 後期選配**：30/block harvest 已證撞牆（見 `docs/roadmap/2026-06-21-rag-augmented-execution.md`）。下列為 P5 真要壓權重時的設定，非當前主線目標。

### 兩個 LoRA Adapter
| Adapter | event_type | 目標 |
|---------|-----------|------|
| block1 | git_ops + terminal_ops + code_gen | bash/tools 執行 |
| block2 | debugging + architecture + knowledge_qa + fine_tuning_ops | 中文回應 |

觸發條件：各 Block ≥ 30 approved 樣本，各自獨立觸發。

### 訓練資料比例
- 70%：當次新 approved 樣本
- 20%：歷史 score ≥ 8.5 且 > 30 天的穩定老樣本
- 10%：通用指令集（Qwen 原始 Alpaca + 通用開發 QA）

### 基底模型升級路徑
Phase 1：Qwen2.5 7B → Phase 2：Qwen2.5 32B（7B 滿足需求後升級）

## Layer 2 評分流程
multi_judge 三方投票（A4 對齊 spec）— 對應 `services/multi_judge.py::multi_judge_score`：
- 每位 judge 給分 score ∈ [0,10]，score ≥ 8 算一票 approved
- 3/3 approved → status='approved'，weight=1.0
- 2/3 approved → status='approved'，weight=0.5（soft label）
- ≤1/3 approved → status='rejected'
- 隱性高信心：`router_decisions.user_accepted=1` → 強制 approved（覆蓋 judge 結果，weight 由 stop hook P1-3 sync_sample_weights 另行覆寫）
- Judge 配額耗盡或全失敗 → status='pending'，下輪重試

## Layer 1 → Layer 2 自動橋接條件
v2 實作（A3 對齊 spec）— 對應 `pipeline.py::_extract_path_a_v2`：
- `event_type ∈ {git_ops, terminal_ops, code_gen, debugging, architecture, knowledge_qa, fine_tuning_ops}`（block1 + block2 全橋；block2 不開橋會永遠湊不到 30 樣本）
- `exchanges.status='completed' AND has_final_text=1 AND has_error=0`（取代過時的 `has_tool_use=true`，標記更精準）
- `branches.is_active=1 AND decay_score ≥ 0.3`（FOREVER 加權）
- 同 session 內合格 exchanges ≥ 2（取代 sessions.exchange_count，僅計乾淨 exchange）

## 事件分類（event_type）
`debugging` / `architecture` / `git_ops` / `terminal_ops` / `code_gen` / `knowledge_qa` / `fine_tuning_ops`

## 免費師父清單（2026）
| 師父 | 模型 | 免費額度 |
|------|------|---------|
| Gemini 2.5 Flash | gemini-2.5-flash | 250 req/day |
| Gemini 2.5 Flash-Lite | gemini-2.5-flash-lite | 1,000 req/day |
| Mistral 7B | open-mistral-7b | 1B token/月 |

## 安全規範
- API Key 存於 macOS Keychain，DB 只存 keychain_ref
- Teacher 切換 = 改 DB 的 `api_base` + `keychain_ref`，零改 code

## 開發規範
- 程式碼附中文註解
- 有意義異動同步更新 CHANGELOG.md

## 運維速查
- stop hook：settings.json 直接指向專案目錄，改動立即生效，不需 plugin 同步
- 手動批次評分：呼叫 `layer_2_chamber.backend.core.background.score_pending_samples(conn_factory)`
- Gemini 評分無獨立 REST endpoint
- Gemini Flash 配額 250 req/day，UTC 午夜重置；429 = 等配額

## 文件導覽
- 設計規格：`docs/design/`（Layer 0/1/2/3 實裝計畫）
- 第三方參考：`docs/references/{papers,blogs,git}/`
- 歷史一次性報告與過時 plan：`docs/archive/`

## 學術參考
- [Self-Evolving LLMs via Continual Instruction Tuning](https://arxiv.org/abs/2509.18133)
- [SEAL: Self-Adapting Language Models](https://arxiv.org/abs/2506.10943)
- [From RAG to Memory](https://arxiv.org/html/2502.14802v1)
- [FOREVER: Forgetting Curve Memory Replay](https://arxiv.org/html/2601.03938v1)
