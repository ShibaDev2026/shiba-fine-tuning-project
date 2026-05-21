# Retrospective：Conditional Expansion — 已棄計畫

**狀態**：棄置（2026-05-21）。Phase 1-5 全部執行完畢，最終決定不進入生產。
**前置依據**：[2026-05-21-rag-cross-exchange-context.md](2026-05-21-rag-cross-exchange-context.md)（PR-M Phase 4 無條件 ±K 擴展失敗）

---

## 假設

PR-M 的 K=2 全題擴展失敗（Δ=−0.76，6 題退步），但 qid=2 短句題受益 +3。
推論：query 「語意完整度」差異大 → **只對 needs-context query 擴展**可能保住 baseline 並救短句題。

## 執行步驟（已全部驗證）

1. **Phase 1 — Ground truth 標籤**：retrieval_golden_set 加 `needs_context_label` 欄位，21 題標 1/0（active 6 vs 10，holdout 2 vs 3）
2. **Phase 2 — 規則分類器**：`query_classifier.needs_context()` 4 條 regex（代號 R1 / 指代詞 R2 / CLI R3 / 疑問詞 R4），confusion matrix：precision=1.0、recall=0.875、F1=0.933（僅 qid=2 漏判）
3. **Phase 3 — 條件擴展 API**：`retrieve_for_eval_conditional(query, top_n, window_k)`，分類器=True 時走 with_context、否則走 baseline
4. **Phase 4 — CLI 整合**：`c2_e2e_evaluation.py --rag-window auto:K` 模式
5. **Phase 5 — A/B 實測**：auto:2 vs K=0 baseline

## 驗證結果

| Run | rag_window | mean | Δ vs K=0 |
|-----|------|------|------|
| `e2e-claude-20260520T231910` | 0 | 7.1333 | baseline |
| `e2e-claude-20260520T232508` | 2（無條件） | 6.375 | −0.76 |
| `e2e-claude-20260521T031519` | **auto:2** | **6.6875** | **−0.4458** |

落在原計畫決策矩陣 `< -0.1`（棄計畫）區段。

## 問題分析（為何 precision=1.0 仍輸 baseline）

**Per-query 拆解**（auto:2 vs baseline）：

| qid | nc | baseline | auto:2 | Δ | 分類器是否觸發 | 觀察 |
|-----|----|----------|--------|---|----------------|------|
| 2 | 1 | 4 | 4 | 0 | ❌（FN） | 真正受益題（K=2 +3）但規則沒命中 |
| 14 | 1 | 7 | 4 | **−3** | ✅ | 規則命中但擴展反而拖累 |
| 5/18/20/26 | 1 | — | — | 0 | ✅ | 命中但無差 |
| 13/19/24/31 | 0 | — | — | −1~−2 | ❌（不擴展） | 純 LLM judge noise（同 retrieval） |

**淨拆解**：Δ=−0.44 ≈ qid=14 拖累 −0.19 + LLM judge noise −0.25。**訊號約等於零**。

## 三條獨立證據（為何棄計畫）

1. **macro-exchange 在 RAGAS Claude judge 下整體無效** — PR-M K=0~3 全敗
2. **分類器命中的 needs-context 題不受益** — auto:2 命中 7 題，6 題 0 差、1 題退步
3. **唯一受益題（qid=2）規則永遠抓不到** — 短句、無代號/指代詞 → 改 LLM classifier 預期天花板也在 −0.3~+0.3 區間，token 不划算

## Cleanup（2026-05-21）

| 項目 | 處理 |
|------|------|
| DB：`retrieval_golden_set.needs_context_label` 欄位 + 21 筆標籤 | DROP COLUMN |
| `layer_1_memory/lib/query_classifier.py` | 刪除 |
| `evaluation/query_classifier_eval.py` | 刪除 |
| `evaluation/migration_needs_context_label.py` | 刪除 |
| `evaluation/migration_evaluation.sql` 的 needs_context_label DDL | revert |
| `layer_1_memory/lib/rag.py::retrieve_for_eval_conditional` | revert |
| `evaluation/c2_e2e_evaluation.py` 的 `auto:K` parsing | revert |

**保留**：PR-M Phase 1-4 infra（schema/`retrieve_for_eval_with_context`/`--rag-window int` CLI）— 整數模式無條件擴展仍可用，供未來實驗。

## 學習

- **「分類器 precision 高」≠「條件擴展有效」**：分類正確不等於分類所代表的處置正確。本案精確識別「需要上下文的 query」但實際擴展不帶來分數增益。
- **RAGAS Claude judge 對 retrieval 變動敏感度低**：同一條件重跑 mean 漂移 0.2-0.3，小規模 A/B（n=16）很難分離訊號。
- **macro-exchange 對「自包含 query」是負面噪音**：鄰居 exchange 引入無關內容，judge 反而扣分。
