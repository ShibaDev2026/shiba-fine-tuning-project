# Reranker PoC — eval 對 reranker 無效（golden set gt cosine-bound）（2026-06-19）

## 目的
驗證 D2 期待的 cross-encoder reranker 能否提升 Layer 1 召回品質（hit@1/recall）。

## 設置
- reranker：`llama-server --reranking`（bge-reranker-v2-m3 GGUF，:8088），cross-encoder
- PoC（`experiments/2026-06-19_reranker_poc/poc.py`，**不碰 production hot path**）：對 65 題 golden，`_vector_search` 取候選池 top-K → reranker 重排 → session 層級 max 聚合取 top-3 → 對照 cosine top-3。
- 前置：Ollama（bge-m3 embedding）+ llama-server rerank 皆在跑。

## 結果（reranker ≤ cosine）
| 候選池 | baseline(cosine) recall | reranker recall | hit@1 Δ | 救回 |
|--------|------|------|------|------|
| top-10 | 0.839 | 0.854 | +0.000 | 0 |
| top-20 | 0.869 | 0.854 | +0.000 | 0 |

reranker 在 top-20 候選池**比 cosine 還差**（−0.015），hit@1 始終零增益、0 題救回。

## ⚠ 但這個 eval 對 reranker 無效（核心發現）
**golden set 的 ground truth 候選抽自 bi-encoder + FTS5 召回**：`golden_set_builder.build_candidates(query, vector_n=15, fts_n=5)` = `_vector_search`（cosine）+ `retrieve_relevant_sessions`（FTS5），Claude 只在這些候選內標 relevance。

→ **gt ⊆ {cosine top-15 ∪ fts5 top-5}**，gt 結構上被 bi-encoder 召回 bound 住。reranker 無法在 recall 上贏——它被 cosine-defined truth 評判，凡 cosine 沒召回的 session 不可能是 gt。**這是 [[project-grading-harness]] Tier B / [[project-d3-judge-calibration-closed]] 的 grader=author / X-as-GT 同陷阱**：用 cosine 召回定義的 gt 去評「能否打敗 cosine」，cosine 結構性勝出。

**pipeline 確認正常（排除 silent bug）**：spot-check 單 query 顯示 reranker 真有 reorder（cosine#8 的 rerank score +0.52 排到 cosine#4 之前）、score 有強區辨（+2.98 → −0.20）。recall 在 top-10/20 完全相同（0.8538）非 bug，是 gt 都在 cosine 高位（top-5 內全 GT）→ 擴大候選池加入的 rank-11-20 都不是 gt、reranker 不該把它們排進 top-3。

## 結論（誠實切窄）
1. **reranker EV 未能評估**（非證偽、非證實）——當前 golden set 無法公平評 reranker。
2. **真 artifact＝pool-recall 曲線**：top-3=0.677 → top-10=0.867 → top-20=0.964 → top-30=0.977。瓶頸從「排序」移到「**召回涵蓋率**」（top-3 候選只涵蓋 0.677 gt）。但 naive fix（擴大 retrieve top-k）對 production 不適用——top-20 context 爆 LLM window。（註：此曲線也部分受 gt cosine-bound 影響，gt 落在 vector top-15 內。）
3. **不追 domain-mismatch confound**：「更大 reranker 會贏」是無底洞；bge-reranker-v2-m3 是強 standard cross-encoder，它在此專案不贏 bge-m3 就是 scope 內的 finding。
4. **下一步不是更多 reranker run，是修 golden set**：gt 需**獨立於 bi-encoder 標註**（Shiba 瀏覽全 session 標 relevance，非只在 cosine 候選內），才能公平評 reranker；或接受 bge-m3 召回在此 domain 已足強（reranker 未顯增益）。

## 產物
- `experiments/2026-06-19_reranker_poc/poc.py`（PoC，中間產物）
- 環境：`brew install llama.cpp` + bge-reranker-v2-m3 GGUF（reranker serving 已驗可行，留作日後 golden set 修好後重評）
