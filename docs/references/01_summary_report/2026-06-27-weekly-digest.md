# 每週研究情報週報 — 2026-06-27

> **本次議題**：#1 HyDE / query rewriting（召回改善）
> 來源：weekly-digest skill（試跑，`TOP_K=3`）｜ 收錄 12 則（blog 3｜tech news 3｜arXiv 3｜GitHub 3）

## TL;DR
本週聚焦「純查詢側召回改善」——與本專案主線 P2（不動語料、在 `rag.py:_vector_search` 注入 HyDE / query rewrite）高度同向。重點訊號：
1. **業界共識已收斂到「不改向量碼、只重寫查詢」就能拿 30–45% 召回增益**（ragaboutit、Meilisearch），正是本專案想驗證的低改動切入點。
2. **2025–2026 學術前沿全往「test-time、免標註、語料回饋」走**：ThinkQE（零訓練、勝過訓練式 dense retriever）、RL-QR（免標註 RL、召回 3.5×）、ADORE（檢索接地的 suppress/補召回迭代）——三者都純查詢側、不動權重/語料，契合本地小模型約束。
3. **反面警示不可忽視**：query expansion 會藉 intent 漂移、移除 lexical anchor、near-duplicate 冗餘毒化召回——直接呼應本專案 embedded index 被 paraphrase 增強污染（2578←170）的發現 → expansion 必須「按 query 類型設 gate」。
4. **可直接對照的工程資產**：`rag-evaluation`（HyDE 與 baseline 同介面 A/B + RAGAS + CI gate，與本專案 `evaluation/` 同構）、`ollama-hyde`（本地端到端對照組）。

---

## 📰 Tech News

### 查詢重寫革命：智慧提示工程如何消除 RAG 召回失敗（The Query Rewriting Revolution）
約 35% 的 RAG（Retrieval-Augmented Generation，檢索增強生成）召回失敗源自查詢構造不良、而非檢索器品質。報導主張僅靠「查詢重寫（query rewriting）」即可在**不改動任何向量搜尋程式碼**下提升 30–45% 召回精度，三機制為查詢分解、領域脈絡注入、重構多樣性，延遲低（50–150ms），並附金融業精度 62%→89% 案例。直接對應本專案主線 P2「純查詢側改善現有召回」——示範不動 `_vector_search` 也能改召回，正是本地小模型想驗證的低改動切入點。
- 來源：news ｜ URL：https://ragaboutit.com/the-query-rewriting-revolution-how-smart-prompt-engineering-is-eliminating-rag-retrieval-failures/ ｜ 發布：2025-12-04 ｜ relevance 5 ｜ 存檔：`news/2026_june/01_The_Query_Rewriting_Revolution_read/`

### 檢索重建：企業 RAG 撞上規模牆，混合檢索採用意願季增三倍（The Retrieval Rebuild: Why Hybrid Retrieval Intent Tripled as Enterprise RAG Programs Hit the Scale Wall）
VentureBeat（Sean Michael Kerner，2026-04-29）依 VB Pulse 企業調查（1–3 月、每月 45–58 位 100 人以上企業受訪者）指出，2026 Q1 企業 RAG 從「不斷加檢索層」轉為「修補既有架構」。關鍵數據：採用 hybrid retrieval（dense embeddings＋sparse 關鍵字＋reranking）的意願單季 **10.3%→33.3%（三倍）**；投資重心從「評估/相關性測試」（32.8%→15.6%）轉向「檢索優化」（19.0%→28.9%）；保留專用向量層的首要理由由「精度」變為「規模下營運可靠性」（31.1%）；評估標準上 response correctness／retrieval accuracy／answer relevance 三者於 3 月收斂同為 53.3%（答對已不夠、還要來源正確且切題）。結論：「RAG 沒死、死的是最初的純向量架構」。與本專案高度相關：印證 bge-m3 向量＋FTS5 混合召回方向，且「以 recall 衡量成敗、多路平行查詢再 rerank」與查詢側 HyDE、召回涵蓋率瓶頸思路一致。
- 來源：news ｜ URL：https://venturebeat.com/data/the-retrieval-rebuild-why-hybrid-retrieval-intent-tripled-as-enterprise-rag-programs-hit-the-scale-wall ｜ 發布：2026-04-29（作者 Sean Michael Kerner）｜ relevance 4 ｜ 取得：本機存檔 HTML（直連被組織政策擋）｜ 存檔：`news/2026_june/02_The_Retrieval_Rebuild_Hybrid_Retrieval_read/`

### RAG 的查詢重寫：如何提升檢索準確度（Query Rewriting for RAG）
Meilisearch 部落格系統化整理查詢重寫技術光譜：查詢擴展（expansion）、分解、改寫、多查詢生成、回退提示（step-back），核心論點「多數使用者查詢與資料庫語言不匹配」。誠實列出限制：過度擴展引雜訊、語意漂移、額外 LLM 呼叫增延遲成本，且單靠重寫不足、仍需 metadata 過濾與 reranking；並區分重寫（改召回）vs reranking（改精度）。為本專案 P2 提供技術選型藍圖與評估指標（Recall@k、MRR、NDCG）。
- 來源：news ｜ URL：https://www.meilisearch.com/blog/query-rewrite-rag ｜ 發布：2026-06-09 ｜ relevance 4 ｜ 存檔：`news/2026_june/03_Query_Rewriting_for_RAG_Improve_Retrieval_Accuracy_read/`

---

## ✍️ Blog

### 進階查詢轉換以改善 RAG（Advanced Query Transformations to Improve RAG）
系統盤點四種查詢側轉換：HyDE（Hypothetical Document Embeddings，假設性文件嵌入）、子問題分解、多步驟（self-ask）轉換，並以 RouterQueryEngine 依 query 類型動態選法（簡單題不轉換、比較題分解、多面向題多步驟）。對 P2 的具體啟發：`rag.py:_vector_search` 不應對所有 query 一律套 HyDE，而應如 router「按類型選法或不選」；文中 HyDE 對事實型 query 仍會生成錯誤細節，顯示假設答案的幻覺風險須留意。
- 來源：blog ｜ URL：https://towardsdatascience.com/advanced-query-transformations-to-improve-rag-11adca9b19d1/ ｜ 發布：2024-01-10 ｜ relevance 5 ｜ 存檔：`blogs/2026_june/01_Advanced_Query_Transformations_to_Improve_RAG_read/`

### 如何用 HyDE 改善 LLM RAG 召回（How to Use HyDE for Better LLM RAG Retrieval）
作者 Dr. Leon Eversberg。HyDE（Hypothetical Document Embeddings，源自 2022《Precise Zero-Shot Dense Retrieval without Relevance Labels》）核心：先用現成 LLM 把短問句轉成「假設文件」——作者實作對本地 `Qwen2.5-0.5B-Instruct` 下 prompt `Write a paragraph that answers the question. Question: {question}` 生成段落（含幻覺也無妨，encoder 視為有損壓縮器會濾掉錯誤細節），**改嵌入這份假設文件（而非原始 query）**，以 `all-MiniLM-L12-v2` 算 embedding 後 cosine 檢索。實測假設文件 vs 真實 Wikipedia 段落相似度 **0.8039 ≫ 原始 query 的 0.4566**，證實縮短了短 query↔長文件的 domain gap。**關鍵適用判準**：HyDE 只對「未經 supervised 標註訓練」的 contriever 型 embedding 有效；已用 MS MARCO 等標註做 asymmetric search 訓練者（`msmarco-*`/`multi-qa-*`）理論上不受益。後續研究指出 hybrid search + HyDE 最佳、且把原始 query 與假設文件**串接**更好，代價是每 query 多一次 LLM 呼叫（延遲/成本）。對本專案 P2 直接相關（注入點 `rag.py:_vector_search`，對症短控制詞 query vs 長 session 記憶文件落差）；但**須先確認 bge-m3 是否已屬 supervised asymmetric 訓練**——若是，HyDE 增益可能有限、須各自 gate 實測。
- 來源：blog ｜ URL：https://medium.com/data-science/how-to-use-hyde-for-better-llm-rag-retrieval-a0aa5d0e23e8 ｜ 發布：2024-10-04（作者 Dr. Leon Eversberg）｜ relevance 5 ｜ 取得：本機存檔 HTML（完整版，含 5 code blocks／4 References）｜ 存檔：`blogs/2026_june/02_How_to_Use_HyDE_for_Better_LLM_RAG_Retrieval_read/`

### 當查詢擴展反而傷害 RAG（When Query Expansion Hurts RAG）
反面警示，挑戰「expansion 一律有益」共識：改寫會藉扭曲 intent、稀釋 reranker 而毒化召回（「reranker 不是魔術師，只是處理你交給它的候選的裁判」——初召回漏掉的，重排救不回）。10 種失效模式中與本專案技術語料高度相關者：意圖泛化（把程序型 query 變概念型）、詞彙錨點移除（改寫掉 build 名/config key/error string）、冗餘獎勵（near-duplicate 擴展「有共識無涵蓋率」，**呼應 embedded index 被 paraphrase 污染 2578←170**）、評估盲區（offline recall 升卻掩蓋位置劣化）。對 P2：HyDE/expansion 應採「擴展閘」按類型啟用、保留 lexical anchor、用原始 query 去 rerank、以 misses 而非 offline 指標驗證——完全支持本專案「expansion 須各自 gate、保守路線」立場。
- 來源：blog ｜ URL：https://medium.com/@ThinkingLoop/when-query-expansion-hurts-rag-23139f06d8d4 ｜ 發布：2026-03-24 ｜ relevance 4 ｜ 存檔：`blogs/2026_june/03_When_Query_Expansion_Hurts_RAG_read/`

---

## 📄 arXiv 論文

### ThinkQE：以演化式思考過程進行查詢擴展（ThinkQE: Query Expansion via an Evolving Thinking Process）
針對 LLM 查詢擴展「過度聚焦、缺多樣性」問題，提出 test-time（免額外訓練）框架，兩支柱：thinking-based 深度語意探索 + corpus-interaction（用語料召回回饋逐輪精煉擴展詞）。DL19/DL20/BRIGHT 上穩定勝過需大量訓練的 dense retriever 與 reranker。啟發直對 P2：純查詢側、零訓練、不動語料，契合本地小模型「不改權重也不重建語料」約束；corpus-interaction 迭代精煉呼應「可稽核 RAG 重用」（但多輪召回增本地延遲，須設 gate）。
- 來源：paper ｜ URL：https://arxiv.org/abs/2506.09260 ｜ 發布：2025-06-10（v1）/ EMNLP 2025 ｜ relevance 5 ｜ 存檔：`papers/2026_june/01_ThinkQE_Query_Expansion_Evolving_Thinking_read/`

### RL-QR：免標註強化學習查詢改寫（RL-QR: Annotation-Free RL Query Rewriting via Verifiable Search Reward）
處理 RAG 查詢最佳化跨多模態索引難題，提出 annotation-free RL 查詢改寫：用 index-aligned 合成查詢推導「可驗證搜尋獎勵」，免人工標註、能泛化跨模態/索引域。MTEB VIDORE V2 上 lexical 3.9×、semantic 3.5× 召回增益；MS MARCO v2.1 與內部資料集 5–10% 提升。最契合「免標註」——本地小資料無標註預算，而「累積驗證過的指令模式」恰可作 verifiable reward 來源；改寫純查詢側、不動語料（但 RL 訓練成本須先以最小實驗驗證 EV）。
- 來源：paper ｜ URL：https://arxiv.org/abs/2507.23242 ｜ 發布：2025-07-31（submitted）/ 2025-12-12（revised）｜ relevance 5 ｜ 存檔：`papers/2026_june/02_RL-QR_Annotation-Free_RL_Query_Rewriting_read/`

### ADORE：以檢索接地相關性回饋的迭代查詢擴展（ADORE: Iterative Query Expansion with Retrieval-Grounded Relevance Feedback）
指出多數 LLM 擴展是「generation-driven」——只生成貌似合理的 pseudo-document、不檢查語料實際回應，致 retrieval drift。提出 ADORE（ADapt, Observe, Relevance Evaluate）迭代框架：每輪 LLM 生成 pseudo-passage → retriever 暴露語料回應 → relevance assessor 判定詞該「強化/補（未覆蓋）/抑制」。BEIR nDCG@10 較 BM25 +24.5%（較最強前法 +3.6%）、BRIGHT +122.9%，程式與資料公開。最貼合 memory「可稽核 RAG 重用」與「embedded index 去 paraphrase 污染」——suppress/undercovered 機制正好抑制誤導詞、補召回多樣性，是純查詢側、不動語料的可稽核迴圈（多輪 LLM 呼叫須評本地延遲）。
- 來源：paper ｜ URL：https://arxiv.org/abs/2606.13905 ｜ 發布：2026-06-11 ｜ relevance 5 ｜ 存檔：`papers/2026_june/03_ADORE_Iterative_Query_Expansion_Relevance_Feedback_read/`

---

## 🔧 GitHub

### thealper2/ollama-hypothetical-document-embeddings
本地 Ollama 上的 RAG + HyDE 最小範例：查詢 → LLM 生成假設答案文件 → embedding → 向量檢索，全本地推論、不依賴外部付費 API，與本專案本地化約束一致。可借鏡 HyDE 生成 prompt 形狀、假設文件與原查詢 embedding 的合併取捨——可作 P2 純查詢側 HyDE（`rag.py:_vector_search`）對 bge-m3 做 base-assumption-first 最小實驗的端到端對照組。
- 來源：git ｜ URL：https://github.com/thealper2/ollama-hypothetical-document-embeddings ｜ 最近更新：2026-02-09 ｜ relevance 5 ｜ 存檔：`git/2026_june/01_ollama-hypothetical-document-embeddings_read/`

### LeoBergmiller/rag-evaluation
建在 arXiv 論文語料的 production 取向 RAG，重點在評估 harness：dense/bm25/hybrid(RRF)/cross-encoder rerank/HyDE 五策略放在同一可抽換 `Retriever` 介面後純 config 切換，再用 RAGAS + 自訂 LLM-judge 量品質/延遲/成本、以 CI regression gate 守門；刻意讓生成模型與裁判模型不同家族避 self-preference bias、以 `Config.fingerprint()` 鎖變數。與本專案高度同構：HyDE 與 baseline 同介面 A/B、四檢查、fingerprint 鎖變數，可直接對照 `evaluation/` 框架與「baseline 比較前提檢查」。
- 來源：git ｜ URL：https://github.com/LeoBergmiller/rag-evaluation ｜ 最近更新：2026-06-18 ｜ relevance 5 ｜ 存檔：`git/2026_june/02_rag-evaluation_read/`

### hasifumi/qe_rag
社內文件本地 RAG 問答，核心特色 QE（Query Expansion）：先用輕量 LLM 把問題擴展成 3 條說法再多路檢索，對用詞晃動更穩健；流程 expand_query → ChromaDB+multilingual-e5-small → cross-encoder rerank top-3 → 重型 LLM 生成附參照，純 CPU、可選 Ollama/llama-server 後端。QE 是 HyDE 同族查詢側改寫，可與 HyDE 並列做最小實驗對照（哪種對 bge-m3 召回增益大）；多路檢索可驗證「召回涵蓋率瓶頸」能否不擴大單路 top-k 緩解；增分索引設計對「去 paraphrase 污染」維護有運維借鏡。
- 來源：git ｜ URL：https://github.com/hasifumi/qe_rag ｜ 最近更新：2026-06-07 ｜ relevance 4 ｜ 存檔：`git/2026_june/03_qe_rag_read/`

---

## 後續動作建議（本週情報 → 本專案）
- **P2 HyDE 最小實驗**可直接拿 `ollama-hyde` 當對照組、`rag-evaluation` 當評估 harness 範本（同介面 A/B + gate）。⚠ **前置 gate**：先確認 bge-m3 是否屬 supervised asymmetric 訓練——若是，HyDE 增益理論上有限（見 Medium HyDE 篇適用判準），須先量再決定是否投。
- **務必設「擴展閘」**：When Query Expansion Hurts RAG 的失效模式（intent 漂移、lexical anchor 移除、near-duplicate 冗餘）對本專案技術語料全部成立，與既定「expansion 須各自 gate」立場一致。
- **ADORE / ThinkQE 的語料回饋迭代**與「可稽核 RAG 重用」「去 paraphrase 污染」方向最契合，值得列為 P2 後續候選（但須先量多輪 LLM 呼叫的本地延遲 EV）。
