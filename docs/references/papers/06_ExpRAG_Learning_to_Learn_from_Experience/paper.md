# Retrieval-Augmented LLM Agents: Learning to Learn from Experience (ExpRAG)

> arXiv: https://arxiv.org/abs/2603.18272 ｜ html: https://arxiv.org/html/2603.18272
> 作者: Thomas Palmeira Ferraz, Romain Deffayet, Vassilina Nikoulina, Hervé Déjean, Stéphane Clinchant｜ 2026-03
> ⚠ 後截止日論文（2026-03，晚於 assistant 知識截止），本分析全程以 arxiv 全文實際內容為準、未用先驗知識補。

## 關鍵詞
experience retrieval, trajectory memory, retrieval-augmented agent, ExpRAG-LoRA, dynamic vs static retrieval, in-context trajectory, out-of-distribution generalization, ALFWorld, ScienceWorld

## 對應 Layer / Roadmap 階段
- **Roadmap 主線最直接學術對應** — 「agent 從過去經驗（軌跡）學習」整套 storage→query→trajectory 三決策拆解，幾乎是本專案「對話 →蒸餾驗證模式 → Pattern Library → Agentic 召回 → in-context 執行」的鏡像。
- **Roadmap P1（Pattern Library）** — storage 決策（存什麼軌跡、含不含失敗）直接指導 Library 該存原始軌跡還是蒸餾模式。
- **Roadmap P2（Agentic 召回 + in-context 執行）** — query 決策（static 起點查 vs dynamic 每步重查）+ memory block 注入 system prompt，等同本專案召回後 in-context 餵本地模型。
- **Layer 3（後期 P5）** — **ExpRAG-LoRA** 把召回管線一併帶進 fine-tune context，且實測 base model 就是本專案的 **Qwen 2.5-7B**。

---

## 核心結論（帶實證數字）

1. **檢索增強推論（不訓練）就有大幅增益，但天花板在涵蓋率**：
   - ALFWorld：zero-shot **29.9%** → ExpRAG inference-only（不 fine-tune）**64.18%**（all-task）。
   - Top-K 是主旋鈕：**K=1→K=4：41.04% → 64.18%**（ALFWorld all-task），檢索越多相關軌跡越好——直接呼應本專案「真瓶頸是召回涵蓋率非排序」（memory: pool recall top3=0.677→top20=0.964）。

2. **檢索增強 fine-tune（ExpRAG-LoRA）解掉標準 LoRA 的 OOD 崩潰**（Table 3，held-out hard 任務）：
   - **Qwen 2.5-7B：90.2%（ExpRAG-LoRA） vs 70.5%（純 LoRA）** — +19.7 pt。
   - Ministral 3-8B：88.5% vs 67.2%（+21.3 pt）。
   - 機制：訓練時把「同一套召回管線」拼進 training context，逼模型學「**利用召回脈絡**」而非「**背任務**」→ 對沒見過的 hard 任務不崩。

3. **dynamic 召回不是免費午餐（任務相依）**：每步重查 vs 起點查一次，ALFWorld **+7.1 pt**（K=4），但 ScienceWorld **−9.3 pt**。→ 「要不要每步重新召回」需依任務型態決定，非預設開啟。

4. **涵蓋率是硬約束（最重要的誠實 gate）**：空 index 時 **88.5% → 29.5%**（崩回近 zero-shot）。「當缺少任務相關軌跡，對 hard 任務的泛化會急遽退化」——**Library 沒覆蓋到的任務，召回幫不上忙**。

---

## 方法機制拆解

### Storage（儲存）
- index `I = {(τᵢ, eᵢ)}ᵢ₌₁ᴺ`：文字軌跡 τ + 其鍵嵌入 e（由 trajectory encoder φ(·) 算）。
- 軌跡「**以原始 chat 格式存、不再過濾或聚合**（stored as raw chat-formatted data without further filtering or aggregation）」。
- 決策軸：full trajectory vs summary、含不含 failure。

### Query（查詢）
- 每個決策步從當前 agent context 建文字查詢 `qₜ`，用 dot-product 取 top-K 最近鄰。
- **static**：episode 起點查一次（只用任務描述）。**dynamic**：每步用「部分互動歷史」重查。

### Trajectory representation（軌跡表徵）
- 用 base model 的原生 chat template 編成多輪對話 `chat(τ)`：**observation → user turn、action → assistant turn**。

### Experience-conditioned generation（注入）
- 召回的軌跡組成 memory block `mₜ = system(τ¹,…,τᴷ)`，**插進 system prompt**，並區分成功/失敗軌跡。

### ExpRAG-LoRA（訓練整合）
- fine-tune 時「用與推論**同一條召回管線**」把 memory block 加進每筆 training context → 學會用召回脈絡，而非記憶答案。

---

## 速查（綁本專案具體設計決策）

| ExpRAG 機制 | 本專案落地 |
|---|---|
| **storage：raw chat vs summary、含不含 failure** | Library 的 storage 決策直接照搬此軸。⚠ ExpRAG 存 raw chat 不過濾；本專案因 [[project-exchange-embeddings-ingestion-noise]] 已知 raw 含雜訊，傾向「蒸餾模式 + 參數化」（與 AWM 一致，見 [[paper-05]]），與 ExpRAG 分歧——但 ExpRAG 證明「含失敗軌跡」有資訊價值，呼應本專案 [[project-rejected-samples-reuse]] 待決。 |
| **query：static vs dynamic（任務相依、+7.1/−9.3）** | 本專案 UserPromptSubmit hook 目前是 static（prompt 進來召回一次）。dynamic（agent 執行中每步重召回）是 P2 可選增益，但**不預設開**——ScienceWorld −9.3 證明會傷。 |
| **top-K 是主旋鈕（K=1→4：41%→64%）** | 召回 top-k 拉大確實漲，但本專案受 **13% 採納天花板 + LLM context 上限**雙重夾擊（memory: 擴 top-k 爆 context）。→ K 不能無腦放大，靠 selective injection（見 AWM）+ Verifier 過濾。 |
| **空 index → 88.5% 崩 29.5%** | **P1 最硬的 EV gate**：Pattern Library 對沒覆蓋的任務零幫助。本專案「先量指令任務重複頻率」正是在量這個涵蓋率前提——重複率不夠高、Library 就是空 index。 |
| **ExpRAG-LoRA 把召回管線帶進 fine-tune（Qwen2.5-7B +19.7pt）** | **P5（fine-tune 後期）的具體配方**：若日後壓權重，不要裸 LoRA（OOD 崩），要 retrieval-augmented LoRA，且 base 正是本專案的 Qwen2.5-7B。 |
| **read-only fixed memory（作者列為侷限）** | 本專案 **manual-accept 飛輪正是 ExpRAG 缺的那塊**：Shiba 刻意採納 → 動態寫回 Library，是 evolving memory，補 ExpRAG「fixed read-only」侷限。 |

---

## 侷限 / 與本專案差異
1. **index 來自環境腳本專家軌跡**：ExpRAG 的軌跡是 env policy 生成的乾淨專家軌跡，其 failure「不反映 LLM agent 真實錯誤模式」。本專案軌跡來自真實 Claude Code 對話——更貼近真實錯誤，但雜訊更多（需蒸餾）。
2. **fixed read-only memory**：作者自承限制線上適應。本專案 manual-accept 飛輪天然解此點。
3. **domain 差異**：ALFWorld/ScienceWorld 是文字 embodied 環境（具體動作空間小）；本專案是 CLI/code agent（動作 = bash/git/工具呼叫，空間開放）→ 軌跡表徵的 observation/action 映射需重設計。
4. **涵蓋率天花板**：與本專案結論一致——召回是「把已覆蓋任務做穩」，非「讓沒覆蓋的任務變會」。這是 P1 EV gate 的理論背書。
