# 已讀文章索引（processed log）

> `weekly-digest` 的**已讀清單**：凡 Phase B 讀過並進過週報的 blog／news／paper／git，URL 記於此。
> 用途：**Phase A 蒐集找新文章時，讀此「一個檔」即可跳過已讀 URL**——比掃整棵目錄樹單純。
> 本地資料夾的讀取狀態另由 `_read` 後綴標示；兩者在 Phase B 標記時**同步更新**。

## 去重規則
- **主鍵＝正規化 URL**：去 `#fragment`、去追蹤 query（`utm_*`、`ref` 等）、去結尾 `/`、host 小寫。
- 蒐集時：候選 URL 命中本表即跳過（不重新蒐集）。
- **寫入時機＝Phase B 標 `_read` 時同步追加**（讀過才登記）；本表**只追加**（append-only）。
- 次要：正規化標題（去空白/大小寫）做近重複偵測——同文不同網址時人工判斷。

## Log
| 處理日 | 來源類型 | 正規化 URL | 標題 | 議題 | 存檔路徑 |
|--------|---------|-----------|------|------|---------|
| 2026-06-27 | blog | https://towardsdatascience.com/advanced-query-transformations-to-improve-rag-11adca9b19d1 | Advanced Query Transformations to Improve RAG | HyDE/query rewriting | blogs/2026_june/01_Advanced_Query_Transformations_to_Improve_RAG_read/ |
| 2026-06-27 | blog | https://medium.com/data-science/how-to-use-hyde-for-better-llm-rag-retrieval-a0aa5d0e23e8 | How to Use HyDE for Better LLM RAG Retrieval | HyDE/query rewriting | blogs/2026_june/02_How_to_Use_HyDE_for_Better_LLM_RAG_Retrieval_read/ |
| 2026-06-27 | blog | https://medium.com/@ThinkingLoop/when-query-expansion-hurts-rag-23139f06d8d4 | When Query Expansion Hurts RAG | HyDE/query rewriting | blogs/2026_june/03_When_Query_Expansion_Hurts_RAG_read/ |
| 2026-06-27 | news | https://ragaboutit.com/the-query-rewriting-revolution-how-smart-prompt-engineering-is-eliminating-rag-retrieval-failures | The Query Rewriting Revolution | HyDE/query rewriting | news/2026_june/01_The_Query_Rewriting_Revolution_read/ |
| 2026-06-27 | news | https://venturebeat.com/data/the-retrieval-rebuild-why-hybrid-retrieval-intent-tripled-as-enterprise-rag-programs-hit-the-scale-wall | The Retrieval Rebuild: Hybrid Retrieval | HyDE/query rewriting | news/2026_june/02_The_Retrieval_Rebuild_Hybrid_Retrieval_read/ |
| 2026-06-27 | news | https://www.meilisearch.com/blog/query-rewrite-rag | Query Rewriting for RAG: how to improve retrieval accuracy | HyDE/query rewriting | news/2026_june/03_Query_Rewriting_for_RAG_Improve_Retrieval_Accuracy_read/ |
| 2026-06-27 | paper | https://arxiv.org/abs/2506.09260 | ThinkQE: Query Expansion via an Evolving Thinking Process | HyDE/query rewriting | papers/2026_june/01_ThinkQE_Query_Expansion_Evolving_Thinking_read/ |
| 2026-06-27 | paper | https://arxiv.org/abs/2507.23242 | RL-QR: Annotation-Free RL Query Rewriting | HyDE/query rewriting | papers/2026_june/02_RL-QR_Annotation-Free_RL_Query_Rewriting_read/ |
| 2026-06-27 | paper | https://arxiv.org/abs/2606.13905 | ADORE: Iterative Query Expansion with Retrieval-Grounded Relevance Feedback | HyDE/query rewriting | papers/2026_june/03_ADORE_Iterative_Query_Expansion_Relevance_Feedback_read/ |
| 2026-06-27 | git | https://github.com/thealper2/ollama-hypothetical-document-embeddings | thealper2/ollama-hypothetical-document-embeddings | HyDE/query rewriting | git/2026_june/01_ollama-hypothetical-document-embeddings_read/ |
| 2026-06-27 | git | https://github.com/LeoBergmiller/rag-evaluation | LeoBergmiller/rag-evaluation | HyDE/query rewriting | git/2026_june/02_rag-evaluation_read/ |
| 2026-06-27 | git | https://github.com/hasifumi/qe_rag | hasifumi/qe_rag | HyDE/query rewriting | git/2026_june/03_qe_rag_read/ |
