# 瓶頸對症解法 Plan（2026-05-29）

> 來源：能力驗證結論（乾淨 n=30 採納 13%、grounding 淨負、成功多為 RAG 逐字複製）+ 網路文獻對照。
> 本檔只記錄**待做決策與待驗證步驟**，不複述已完成細節。完成驗證後刪除。

## 核心判讀（待 Shiba 拍板）

四篇主軸文獻收斂到同一方向，且印證既有「砍 Layer 0/2/3 生成式接管、留 Layer 1」結論：

> **停止往「生成 + fine-tune」投資；把 Layer 1 從 always-retrieve RAG 升級成「gated retrieval + case/plan replay」，judge 改為被人工錨點校準的閾值器。**

**Decision Gate 0（前置，阻擋一切）**：覆核能力驗證邊界 **#7 / #3**，確認 13% 數字站得住。數字若大幅變動 → 本 plan 全部重評。

---

## 待決策清單

### D1 — 範式轉向：放棄生成式接管？
- 選項 A：接受結論，凍結 Layer 0/2/3 生成接管，資源全投 Layer 1 檢索/重用。
- 選項 B：保留一條最小 fine-tune 驗證（需先解 D4 資料污染）。
- **預設傾向 A**；B 僅在 Gate 0 數字翻盤時考慮。

### D2 — retrieval 閾值校準（現狀已查明 2026-05-29，ready to execute）
- **現狀**：L1 已有 gate＝`_vector_search` rag.py:400 `score>0.35`（硬編碼，註釋自承「降門檻提召回」拍腦袋，**全專案僅此一處**）；非真 always-retrieve。grounding poison 實證它沒擋住無關召回（能力驗證 #7 無關 query「你有閱讀那四份論文嗎」仍召回注入）。
- **執行序列**：① 獨立掃描腳本（放 experiments/，不碰 production）用 `ragas_retrieval_golden_set` 掃 threshold 0.35→0.7 量 uuid_recall/precision/hit@1/mrr ② 選最優 ③ 單次異動改 rag.py:400 並參數化 ④ pytest tests/memory 驗證。
- **環境**：ollama UP ✓、`.venv` ✓（用 `.venv/bin/python`；shell 未激活故 pytest 需全路徑）。
- **工具**：`modules/ragas/ragas_runner.py`（`run_layer1_evaluation` 從 `ragas_retrieval_golden_set` 讀 GT → `retrieve_for_eval` → `_compute_uuid_metrics`）。**RAGAS 實際在 `modules/ragas/`，非 memory 舊記的 `evaluation/`**。
- **隱患**：golden set 的 GT uuid 若建在 over-merge 髒資料上會影響校準可信度（牽連 D4）。
- **執行結果（2026-05-29，experiments/2026-05-29_d2_threshold_calibration/scan.py）**：65 golden query 掃 0.30–0.70。① 0.35→0.55 指標全同 → 0.35 對相關 query **零過濾作用**；調 0.70 precision 僅 +3%（0.841→0.872）。② **決定性**：hit/miss score 分離度僅 **+0.054**（hit avg 0.915 vs miss avg 0.861，miss max=1.0）→ 誤召回 score 與正召回一樣高，**閾值無法區分**。
- **結論**：調閾值是錯藥方（改 0.35 無用，0.35 維持不動避免無效異動）。真瓶頸＝召回排序品質 → **D2 重新定向為 reranker（cross-encoder 重排 top-k）**；memory 中「暫緩的 reranker」其實是正解，不該暫緩。
- **附帶發現**：(a) `ragas_runner` 讀 `ragas_retrieval_golden_set` 但實際表名 `retrieval_golden_set`（改名 migration 未跑，runner 現坏）；(b) `_compute_uuid_metrics` recall 對重複 uuid over-count（>1）。兩者待修。

### D3 — Judge 校準
- 現況：multi_judge 三方投票，auto adoption 92% vs 真實 13%（agreeableness/self-preference bias）。
- 待決：是否改用既有 90-sample 人工標註做 HITL 校準錨點，回歸校正閾值；是否引入異源 judge 降 self-preference。

### D4 — 資料污染（branch_messages.seq 退化，gated）
- 與本 plan 強耦合：D1-B 與任何 fine-tune 前提都需先修。
- 待決：是否啟動 Phase B（修 seq parser 恢復 39.7 萬訊息），或僅用 clean subset 繼續。

### D5 — Case/Plan Replay 取代生成（git/bash 重複任務）
- 候選（文獻）：Memento（case bank 重用，不改權重）/ Agentic Plan Caching（plan template 重用）/ ProcMEM（情境→動作 procedural memory）。
- 待驗證：對 git/bash 重複指令，replay 命中率與正確率 vs 現行生成。

**本專案具體落地方案（由 exchange-distillation spec 收編，2026-05-29）**

> 收編註記：原 exchange-distillation 的「13% 是無效量測 / 需乾淨樣本來源」兩個動機**已被 clean n=30 重跑推翻**（篩過真指令仍 13%），故只保留下方「RAG 索引結構重構」這條——它本質就是 D5 的 procedural memory（intent→指令映射）。

- **核心問題**：現況 embed「問句原文」→ query 命中「語氣像」而非「該跑什麼」；exchange 把 user 問句直接配 tool result、跳過中間決策解讀。
- **解法**：獨立排程蒸餾 job 把整段 exchange 蒸餾成 `(intent → command_template)`，**embed intent 取代問句**。
- **設計原則（Shiba 已拍板，不得違反）**：
  1. 保留 raw 結構（`exchanges`/`exchange_messages`/`tool_executions`）原封不動當權威來源
  2. 獨立排程、不綁 Stop Hook（SRP；gemma 掛了照樣收對話）
  3. 衍生層可重建（extractor 改良就砍掉重跑/backfill，零資料損失）
- **新增衍生表** `exchange_distillations`（additive，只加不改 raw）：`exchange_id` FK（唯一→冪等）/ `intent`（embed 這個）/ `command_template`（變數抽象化）/ `is_command_request` 0/1（乾淨樣本 filter 這欄）/ `request_type`（command/conceptual/planning/noise）/ `outcome`（取 tool_executions.is_error）/ `embedding` / `extractor_model` / `distilled_at`。
- **複用資產**：排程框架 `setup_scheduler`（background.py:94）、feature-gated noop 範式 `_run_paraphrase_job`、兄弟 job `paraphrase_sparse_instructions`（modules/paraphrase/service.py:76）、`get_embedding`（embedder.py）、ablation `fetch_candidates` JOIN SQL。
- **階段切分**：retrieval 改吃本表是**第二階段**，本方案先只做「蒸餾 + 寫衍生表」，不動 `exchange_embeddings`。
- **待驗證**：蒸餾後 intent-based 召回 vs 現行問句召回的 grounding 淨值差（與 D2 retrieval gating 一起量）。

---

## 建議執行順序 + model/effort

| 步驟 | 內容 | model / effort |
|------|------|----------------|
| S0 | Gate 0：覆核邊界 #7/#3，鎖定 13% | Opus high（判讀邊界） |
| S1 | D2 細讀 TARG，評估接 Layer 1 的最小改法（不確定度 gate 接在 get_rag_context 前） | Opus high |
| S2 | D2 落地 retrieval gating PoC，跑 clean subset 量 grounding 淨值 | Sonnet medium |
| S3 | D3 用 90-sample 標註回歸校正 judge 閾值 | Sonnet medium |
| S4 | D5 case/plan replay PoC（git/bash 子集），量命中率 | Opus high（設計）→ Sonnet medium（實作） |
| S5 | 彙整 PoC 數字，回填 D1 拍板 | Haiku low（彙整）→ Opus（決策） |

---

## 文獻錨點（arxiv 預印本，方法可信、數字勿照抄）

- 範式 B / case replay：Memento — Fine-tuning LLM Agents without Fine-tuning LLMs（arxiv 2508.16153）
- Retrieval gating：TARG（arxiv 2511.09803）/ Astute RAG（arxiv 2410.07176）
- Judge bias：Scoring Bias in LLM-as-a-Judge（arxiv 2506.22316）/ Self-Preference Bias（arxiv 2410.21819）
- Plan/procedural replay：Agentic Plan Caching（arxiv 2506.14852）/ ProcMEM（arxiv 2602.01869）
- 反例（不對症）：Small LM Targeted Fine-tuning（arxiv 2512.15943）— 需乾淨大量監督軌跡，前提不滿足
