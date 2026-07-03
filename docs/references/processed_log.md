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
| 2026-07-03 | paper | https://arxiv.org/abs/2605.09611 | Byte-Exact Deduplication in RAG: A Three-Regime Empirical Analysis | 索引去污染/召回多樣性 | papers/2026_july/01_Byte_Exact_Dedup_RAG_Three_Regime_read/ |
| 2026-07-03 | paper | https://arxiv.org/abs/2512.25052 | AdaGReS: Adaptive Greedy Context Selection via Redundancy-Aware Scoring | 索引去污染/召回多樣性 | papers/2026_july/02_AdaGReS_Redundancy_Aware_Context_Selection_read/ |
| 2026-07-03 | paper | https://arxiv.org/abs/2604.03240 | Scaling DPPs for RAG: Density Meets Diversity | 索引去污染/召回多樣性 | papers/2026_july/03_ScalDPP_Density_Meets_Diversity_read/ |
| 2026-07-03 | paper | https://arxiv.org/abs/2601.17212 | DF-RAG: Query-Aware Diversity for RAG | 索引去污染/召回多樣性 | papers/2026_july/04_DF_RAG_Query_Aware_Diversity_read/ |
| 2026-07-03 | paper | https://arxiv.org/abs/2604.24334 | Reducing Redundancy in RAG through Chunk Filtering | 索引去污染/召回多樣性 | papers/2026_july/05_RAG_Chunk_Filtering_Redundancy_read/ |
| 2026-07-03 | news | https://milvus.io/blog/minhash-lsh-in-milvus-the-secret-weapon-for-fighting-duplicates-in-llm-training-data.md | MinHash LSH in Milvus | 索引去污染/召回多樣性 | news/2026_july/01_Milvus_MinHash_LSH_Dedup_read/ |
| 2026-07-03 | news | https://zilliz.com/blog/data-deduplication-at-trillion-scale-solve-the-biggest-bottleneck-of-llm-training | Data Deduplication at Trillion Scale | 索引去污染/召回多樣性 | news/2026_july/02_Zilliz_Trillion_Scale_Dedup_read/ |
| 2026-07-03 | news | https://aragonresearch.com/milvus-previews-vector-database-enhancements | Milvus Previews Vector Database Enhancements | 索引去污染/召回多樣性 | news/2026_july/03_Aragon_Milvus_Enhancements_read/ |
| 2026-07-03 | news | https://www.infoq.com/articles/reducing-false-positives-retrieval-augmented-generation | Reducing False Positives in RAG Semantic Caching | 索引去污染/召回多樣性 | news/2026_july/04_InfoQ_RAG_Semantic_Cache_False_Positives_read/ |
| 2026-07-03 | news | https://venturebeat.com/data/six-data-shifts-that-will-shape-enterprise-ai-in-2026 | 6 data predictions for 2026 | 索引去污染/召回多樣性 | news/2026_july/05_VB_Six_Data_Predictions_2026_read/ |
| 2026-07-03 | blog | https://dev.to/kuldeep_paul/synthetic-data-for-rag-safe-generation-deduplication-and-drift-aware-curation-in-2025-3298 | Synthetic Data for RAG: Safe Generation, Deduplication, and Drift-Aware Curation | 索引去污染/召回多樣性 | blogs/2026_july/01_Synthetic_Data_for_RAG_Dedup_Curation_read/ |
| 2026-07-03 | blog | https://duaneforresterdecodes.substack.com/p/vector-index-hygiene-a-new-layer | Vector Index Hygiene: A New Layer of Technical SEO | 索引去污染/召回多樣性 | blogs/2026_july/02_Vector_Index_Hygiene_read/ |
| 2026-07-03 | blog | https://mostlylucid.net/blog/graphiticragdedupe | Deduplication of Graphitic RAG Evidence Segments in lucidRAG | 索引去污染/召回多樣性 | blogs/2026_july/03_lucidRAG_Evidence_Segment_Dedup_read/ |
| 2026-07-03 | blog | https://farzzy.hashnode.dev/enhancing-rag-with-maximum-marginal-relevance-mmr-in-azure-ai-search | Enhancing RAG with MMR in Azure AI Search | 索引去污染/召回多樣性 | blogs/2026_july/04_MMR_Azure_AI_Search_read/ |
| 2026-07-03 | blog | https://sabarishkumarg.medium.com/designing-rag-architectures-that-scale-chunking-deduplication-and-accuracy-improvements-1adb76dbd8ec | Designing RAG Architectures That Scale | 索引去污染/召回多樣性 | blogs/2026_july/05_Designing_RAG_Architectures_That_Scale_read/ |
| 2026-07-03 | git | https://github.com/minishlab/semhash | MinishLab/semhash | 索引去污染/召回多樣性 | git/2026_july/01_semhash_read/ |
| 2026-07-03 | git | https://github.com/maycxc/sqlite-mmr | MayCXC/sqlite-mmr | 索引去污染/召回多樣性 | git/2026_july/02_sqlite_mmr_read/ |
| 2026-07-03 | git | https://github.com/protonhash/sieve | Protonhash/sieve ⚠空殼倉警示 | 索引去污染/召回多樣性 | git/2026_july/03_sieve_shell_repo_warning_read/ |
| 2026-07-03 | git | https://github.com/chenghaomou/text-dedup | ChenghaoMou/text-dedup | 索引去污染/召回多樣性 | git/2026_july/04_text_dedup_read/ |
| 2026-07-03 | git | https://github.com/ekzhu/datasketch | ekzhu/datasketch | 索引去污染/召回多樣性 | git/2026_july/05_datasketch_read/ |
