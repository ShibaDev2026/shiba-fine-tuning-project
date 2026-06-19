# 2026-05-23 — Local Qwen 能力上限驗證 + Prompt Caching + /cost 驗證

> 本 plan 起因於 2026-05-23 brainstorm session，**核心目的：在繼續任何 Layer 3 Fine-tuning 擴張（P0/P1/P2）之前，誠實驗證「Local Qwen 接手 Claude Sonnet 4.6 的重複任務」這個 base assumption 是否成立**。
>
> 執行順序：①Prompt Caching → ③能力上限驗證 → ②`/cost`

---

## 一、批判點 Record（為什麼要先做這個驗證）

### 1. 核心 base assumption 從未被驗證
- Layer 3 Pipeline 已建（mlx_trainer / gguf_converter / ollama_updater / server / db），feature_registry / multi_judge_v2 都模組化了
- **但從未產出一個「Local Qwen 真的接手成功、user_accepted=1」的端對端案例**
- 這是 over-engineering 的典型反模式：基礎建設先於需求驗證

### 2. 能力差距是數量級的
- Qwen 7B（甚至 30B-a3b）vs Claude Sonnet 4.6 在 MMLU / HumanEval / 中文長文推理差距巨大
- LoRA fine-tune **主要學格式與風格，不會憑空增加 capability**
- 學生上限 = 當前老師。訓練資料一旦累積，模型凍結在當時 Claude 行為；Claude 升級後 Local 越落後

### 3. 「重複性任務」定義含糊
- 真正字面重複的：zsh + atuin 已解掉
- 語意相近但帶上下文（哪個專案、什麼狀態、最近改了什麼）：正是 LoRA 不會自動學到的（已是發散點 2）

### 4. 架構複雜度超出個人專案合理規模
- Layer 0/1/2/3 + RAGAS + multi-judge + feature_registry + 7 modules + Teacher 配額治理 + dual baseline + golden set + SQLite race hardening
- 5-10 人團隊架構規模，一人維護
- 訊號：必須拆 PR-O 10 個 sub-PR、最近才加 `/resume` skill 重載結構

### 5. 純成本/效益不划算
| 項目 | 量 |
|---|---|
| Token 省下上限（block1 全替換樂觀估） | $90-365/年 |
| 已投入個人工程時間 | 200+h（年薪換算機會成本 >> 年省金額 10-100×） |
| **Prompt Caching 還沒啟用** | 零開發成本，可直接省 30-50% 「重複 system prompt + context 注入」token |

### 6. 對話品質被「訓練資料品質要求」反向綁架
知道每次對話會變訓練資料 → 傾向問規範化問題、減少天馬行空探索、對話被自建系統倒過來限制

### 7. 「學習 fine-tune」目標不需要這個架構
一個 Jupyter notebook + 200 筆樣本，一週可學完 MLX LoRA。把學習綁在 4 層架構上是用學習當藉口繼續維護過度設計

---

## 二、執行順序 1 → 3 → 2

### ① Prompt Caching（最高 ROI、最低風險，先做）
**目標**：對 Claude API 呼叫加 `cache_control` 標記，讓重複的 system prompt / `CLAUDE.md` / `MEMORY.md` / RAG 注入 context 進入 5-min cache，命中可省 9 折以上 token。

**待做**：
- [ ] 盤點 Claude API 呼叫位置（grep `anthropic` / `claude-sonnet` / `claude-opus`）
- [ ] 對 system prompt + 長 context 加 `cache_control: {type: "ephemeral"}` 標記
- [ ] 確認 4 個 cache breakpoint 上限不超過
- [ ] 跑一次測試，看 response `usage.cache_creation_input_tokens` / `cache_read_input_tokens` 確實有值

**Anthropic 官方參考**（下次 session 再驗證版本）：
- https://docs.anthropic.com/en/docs/build-with-claude/prompt-caching
- TTL 預設 5 分鐘，可設 1 小時（beta header）

**預估時間**：2-3h

### ③ 能力上限驗證實驗（決定 Layer 3 命運的閘門）

**核心假設**：若 Qwen 30B-a3b（你最大本地模型）+ 完整 RAG context、**不 fine-tune**，已能在 git push 任務上達 80%+ 採納率，則 Layer 3 fine-tune 多餘；若 < 70%，base 能力差距 fine-tune 也救不了，Layer 3 應砍。

**實驗範圍**：
- **任務類型**：git push（block1 中 output 結構最固定、變數最少、評估最容易；P0 試金石原本就鎖定它）
- **樣本來源**：`exchanges` 表 final_text_preview 含 `git push` 的 178 筆中隨機抽 30 筆
- **模型**：`qwen3:30b-a3b`（不走 fine-tune，純 prompt + RAG）

**實驗步驟**：
1. **抽樣腳本**：`experiments/2026-05-23_capability_validation/sample.py`
   - 從 `exchanges` 表抽 30 筆 git push 樣本
   - 欄位：`sample_id, session_id, user_text_preview, final_text_preview, started_at`
   - 輸出：`experiments/2026-05-23_capability_validation/samples.csv`

2. **RAG 召回**：對每筆 user_text_preview，呼叫 Layer 1 的 `rag.retrieve_for_eval(query, k=3)` 取 context
   - 注意：被抽出來的樣本要從 RAG 庫排除（避免自己召回自己造假）

3. **Qwen 推論**：
   - prompt 結構：`system + RAG context + user query`
   - system prompt 用你日常會給 Claude 的（含 cwd / git remote / branch 環境資訊）→ 模擬你方向 1 + 方向 3 的真實使用情境
   - 呼叫 ollama `qwen3:30b-a3b`
   - 輸出存 `experiments/2026-05-23_capability_validation/qwen_outputs.csv`

4. **人工評估**：30 筆 × 5 min = ~2.5h
   - 每筆人工標 `user_accepted ∈ {0, 1}` + `reason`（為什麼接受 / 拒絕）
   - 判準：「如果這次是 Qwen 直接給我這個答案、我會不會直接執行」（不是「答案完美」而是「我會接受」）
   - 額外標 `failure_mode ∈ {wrong_remote, wrong_branch, hallucination, format_error, ok}`，協助歸因

5. **結果分析**：
   - 採納率 = 接受筆數 / 30
   - failure_mode 分佈：是「變數錯」（發散點 2，可解）還是「整體 hallucination」（base 能力，不可解）
   - 輸出：`experiments/2026-05-23_capability_validation/RESULT.md`

**退出條件 / 決策樹**：
| 結果 | 決策 |
|---|---|
| 採納率 ≥ 80% | **不需要 Layer 3 fine-tune**。純 RAG + 大模型 inference 已夠。砍 Layer 3，留 Layer 0+1+RAGAS |
| 70% ≤ 採納率 < 80% | 邊界灰色。看 failure_mode 分佈：若以「變數錯」為主 → 可考慮輕量解（方向 1 prompt 注入），不需 fine-tune；若以「hallucination」為主 → 同 < 70% 處理 |
| 採納率 < 70% | **fine-tune 救不了 base 能力差距，砍 Layer 3 計畫**。砍 Layer 0/2/3，留 Layer 1 + RAGAS |

**預估時間**：
- 腳本：2-3h
- 30 筆 Qwen 推論（30B 不快，~30s/筆）：~15 min
- 人工標註：2.5h
- 分析 + 寫 RESULT.md：1h
- **合計 ~6-7h**（兩週內輕鬆完成）

**重要約束**：
- 實驗腳本放 `experiments/` 目錄（新建），**不入 Layer 架構**
- 純讀 DB、純呼叫 Ollama，**不汙染任何 production code**
- 不修 layer_0/1/2/3 任何檔案，不動 schema

### ② 跑 `/cost`（驗證 ① 生效）
**目標**：跑 Claude Code 的 `/cost`，看：
- Prompt Caching 啟用後實際命中率
- token 真正花在哪（重複 system prompt？長對話？大檔案讀取？複雜推理？）
- 若 cache hit 不如預期，回頭調 `cache_control` 位置

**預估時間**：10 min

---

## 三、決策閘門總表

```
[啟用 Prompt Caching] ─→ [能力上限驗證 30 筆]
                                 │
                  ┌──────────────┼──────────────┐
                  ▼              ▼              ▼
              ≥80% 採納       70-80%         <70%
                  │              │              │
                  ▼              ▼              ▼
            砍 Layer 3    看 failure_mode    砍 Layer 0/2/3
            純 RAG+大模型   決定輕量解         留 Layer 1+RAGAS
            inference 即可   或 fine-tune       
                  │              │              │
                  └──────────────┴──────────────┘
                                 │
                                 ▼
                            跑 /cost 驗證
```

---

## 四、本 plan 不會做的事（明確排除）

- ❌ 不擴張 P0 試金石（原本的「方向 3 兩者結合 + git push 模板化」計畫**暫停**，等驗證結果再說）
- ❌ 不寫任何 Layer 0/2/3 production code
- ❌ 不加新 modules、不動 schema、不開 PR-P 之類擴張
- ❌ 不為了「累積樣本」而做任何加法

---

## 五、下次 session 開場 SOP

1. `/resume` 看 MEMORY → 看到本 plan 連結
2. 讀本 plan 一遍，確認上次決策仍然成立
3. 從 ① Prompt Caching 開始（最高 ROI、最低風險）
4. 完成 ① 後跑 quick test 看 cache_read tokens
5. 進 ③ 能力上限驗證（建 `experiments/2026-05-23_capability_validation/` 目錄、抽樣腳本、推論、人工標、寫 RESULT.md）
6. ③ 完成寫 RESULT.md 後依決策樹決定 Layer 0/2/3 命運
7. 跑 ② `/cost` 收尾
8. 本 plan 完成後**刪除**（CLAUDE.md 規範：plan 檔完成驗證後立即刪除）

---

## 附錄：本次 brainstorm 收斂路徑（紀錄用）

| 釐清題 | Shiba 選 | 收斂出 |
|---|---|---|
| 期望最終執行者是誰？ | C（混合） | Layer 0 Router 分流的合理性 |
| 「動態變數」處理方向？ | 方向 3（兩者結合） | 但成本承擔需明確 |
| P0 試金石優先目標？ | 目標 1（驗證 pipeline 跑得通） | 不追樣本累積速度 |
| P0 範圍邊界？ | A（只 git push） | 178 樣本，變數最少最固定 |
| **跳開：是否有現成替代方案？** | **質疑 base assumption** | **回頭做能力上限驗證才是先決條件** |
| 願不願意做兩週驗證？ | A（願意） | 即本 plan |

Brainstorm 在「P0 範圍 = A（只 git push）」收斂完即將進入設計呈現階段，Shiba 主動跳開問替代方案 → 觸發批判性檢視 → 改路為先做能力上限驗證。
