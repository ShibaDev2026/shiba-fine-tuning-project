# Weekly Digest — 2026-07-03

**本次議題**：#2 embedding index 去污染／召回多樣性（retrieval diversity, near-duplicate embeddings, deduplication RAG corpus, paraphrase augmentation pitfalls）
**收錄則數**：20（paper 5／news 5／blog 5／git 5，其中 git 1 則為反面教材警示）

## TL;DR

本週訊號高度收斂成一個兩層解法共識：**離線「語意去重清索引」＋查詢時「冗餘感知選擇保多樣」**。學術端 2025H2–2026 檢索冗餘/多樣性是活躍方向——對話式語料被實測為重複重災區（byte-exact 冗餘即達 80.34%），且有幾何證據顯示 bge-m3 這類原生 cosine 空間**天然偏好冗餘**（ScalDPP 負 margin 發現）；查詢側 MMR（Maximal Marginal Relevance）系方法演化出免調參（AdaGReS 閉式自適應 β）與 query-aware（DF-RAG，EACL 2026）變體，全是零訓練即插即用。產業端 vector DB 廠商把去重收編為一級索引功能（Milvus 2.6 MinHash LSH），InfoQ 銀行案例用 bge-m3 實測出「**候選集合策展品質 > 模型選擇或調閾值**」——與本專案 curation 勝 accumulation 的收斂互為印證。工具端 semhash（語意層）＋datasketch（寫入時 LSH 閘）＋text-dedup（lexical 批次）可組出輕量本地去污染鏈；另抓到一個蹭關鍵字的空殼倉（sieve），提醒此賽道選型要驗 README 一致性。**對本專案的誠實註記**：召回線已於同日 A-vs-B 實測 FAIL 結案，以下內容的當前價值是「若未來重啟召回時的施工圖」與 ingestion 衛生參考，不構成重啟理由。

---

## 論文（paper）

### 1. 對話式語料是重複重災區：byte-exact 去重即省 8 成 context
一篇務實的實證研究把 RAG（Retrieval-Augmented Generation）去重問題切成三種 regime：學術語料幾乎無重複（0.16%）、企業語料中度（24.03%）、**對話式 AI 語料極高（80.34%）**。方法只用最保守的 byte-exact chunk 去重，在 22.2M BeIR passages 上以跨四家供應商的 5 judge 驗證零品質退化（Wilson 95% 上界 <5%）。對本專案的訊息直接：對話語料天生是重複重災區，確定性去重是零風險的第一刀，但 paraphrase 污染還需語意層接手。
> paper｜https://arxiv.org/abs/2605.09611｜2026-05-10｜rel 5｜`papers/2026_july/01_Byte_Exact_Dedup_RAG_Three_Regime/`

### 2. AdaGReS：免調參的冗餘感知 context 選擇
把 token 預算下的 context 選擇寫成「相關性減冗餘懲罰」的集合目標，greedy 求解並證明 ε-近似次模性保證。最大賣點是冗餘權重 β 的**閉式自適應校準**——從語料平均相似度與預算自動推出，免去 MMR 式 λ 手調。NQ 上複雜查詢 IoU 提升 8–15 個百分點，高冗餘語料上全參數區間穩定勝出。實作只需 embedding 相似度，對千級污染語料幾乎零成本可試。
> paper｜https://arxiv.org/abs/2512.25052｜2025-12-31｜rel 5｜`papers/2026_july/02_AdaGReS_Redundancy_Aware_Context_Selection/`

### 3. ScalDPP：bge-m3 原生空間「天然偏好冗餘」的幾何證據
把行列式點過程（DPP，Determinantal Point Process）帶進 RAG chunk 子集選擇，輕量 P-Adapter 重塑 embedding 幾何、Diverse Margin Loss 訓練「互補贏過冗餘」。MultiHop-RAG 上無 reranker 平均 Recall@10 +14.3%，預算越緊增益越大（4-hop NDCG +31.8%）。**最有意思的是負 margin 發現：在原始 embedding（含 bge-m3）空間，正確互補子集的行列式反而低於冗餘子集**——cosine 幾何天然偏愛重複內容，替所有 top-k 冗餘症狀提供幾何解釋。代價是需標註訓練，小語料難直接套用。
> paper｜https://arxiv.org/abs/2604.03240｜2026-04｜rel 5｜`papers/2026_july/03_ScalDPP_Density_Meets_Diversity/`

### 4. DF-RAG（EACL 2026）：query-aware 動態多樣性＋oracle gap 方法論
在 MMR 框架上做 query-aware 改進：多樣性權重不再是全域手調超參，而是 test time 依查詢動態決定，全程免訓練。推理密集型 QA 上比標準 RAG 提升 F1 4–10%，並用 oracle 分析框住上限——完美多樣性選擇值 +18% 絕對 F1，DF-RAG 拿到其中 91.3%。**「先量 oracle 天花板再決定值不值得做」的分析框架本身值得抄**（正合 base-assumption-first）。
> paper｜https://arxiv.org/abs/2601.17212｜2026-01-23｜rel 5｜`papers/2026_july/04_DF_RAG_Query_Aware_Diversity/`

### 5. 三路離線 chunk 過濾對比：瘦身 25–36%、recall 損失 <6% 的驗收基準
比較 semantic 相似度閾值、BERTopic 同主題判重、NER（Named Entity Recognition）實體重疊三路離線過濾。NER Exact 最穩健（索引縮 25–36%、recall 損失 <6%），semantic 閾值在 QA 語料已是強 baseline，隨機刪除對照組全面崩盤。實體法在低實體密度的對話語料會失效——本專案這類語料 semantic 路最對症；且有 `source_instruction` 溯源時直接按 source 折疊比任何無監督過濾更乾淨，此文價值在提供「過濾後 recall 損失 <6%」的驗收線。
> paper｜https://arxiv.org/abs/2604.24334｜2026-04-27｜rel 4｜`papers/2026_july/05_RAG_Chunk_Filtering_Redundancy/`

---

## 產業新聞（news）

### 6. Milvus 2.6 把 MinHash LSH 去重收為原生索引
透過 shingling→MinHash 簽名→banding 分桶兩段式流程，把兆級文件近重複偵測從全對比較降為桶內比較；官方案例：10 億文件去重比 MapReduce 快逾 2 倍、成本省 3–5 倍。去重從離線批次雜務升格為 vector DB 一級功能——「資料品質基建」被收編進產品線。
> news｜https://milvus.io/blog/minhash-lsh-in-milvus-the-secret-weapon-for-fighting-duplicates-in-llm-training-data.md｜2025-05-16｜rel 5｜`news/2026_july/01_Milvus_MinHash_LSH_Dedup/`

### 7. Zilliz：去重是兆級 LLM 訓練第一瓶頸（含 float32/uint32 陷阱）
Kimi K2、LLaMA 3.1 語料已達 15T tokens，MapReduce 去重動輒數週。其 MinHash LSH 方案做到 30GB 簽名檔 4 分鐘導入、44K 向量/秒查詢。實務陷阱值得記：**float32 無法精確承載 uint32 雜湊值導致簽名靜默失真，必須走 binary vector**。
> news｜https://zilliz.com/blog/data-deduplication-at-trillion-scale-solve-the-biggest-bottleneck-of-llm-training｜2025-07-26｜rel 5｜`news/2026_july/02_Zilliz_Trillion_Scale_Dedup/`

### 8. 分析師看 Milvus 2.6：「時間衰減」成一級功能＝正式承認向量內容會貶值
Aragon Research 點評：RaBitQ 1-bit 量化宣稱記憶體省 72%、QPS 翻 4 倍，加上短語精確搜尋、時間衰減相關性、冷熱分層與取代 Kafka 的 Woodpecker WAL。「時間衰減」被產品化最值得玩味——與本專案「召回是貶值資產」的判斷同構。
> news｜https://aragonresearch.com/milvus-previews-vector-database-enhancements/｜2025-05-16｜rel 4｜`news/2026_july/03_Aragon_Milvus_Enhancements/`

### 9. InfoQ 銀行案例：候選策展品質壓過模型選擇與調閾值（bge-m3 實測）
預設閾值 0.7 下部分 embedding 模型假陽性率高達 99%（「我不想要這張卡」被高信心導向「關閉投資帳戶」）。調高閾值只能到 13.4% 且犧牲命中率；真正突破是重設快取內容——100 條黃金 FAQ 配 300 條戰略干擾項，假陽性砍半，品質控管後 **bge-m3 降至 4.5%（閾值 0.8、命中 78.6%）**。結論反直覺且與本專案收斂一致：**內容策展 > 演算法優化**。
> news｜https://www.infoq.com/articles/reducing-false-positives-retrieval-augmented-generation/｜2025-11-14｜rel 4｜`news/2026_july/04_InfoQ_RAG_Semantic_Cache_False_Positives/`

### 10. VentureBeat 2026 預測：RAG 讓位 contextual memory、vector DB 降格為資料型別
年度預測稱 RAG 不會消失，但 contextual memory 將在 agentic 部署中超越它成為標配；PostgreSQL 40 歲之年迎來最高相關性（Snowflake $250M 購 Crunchy Data、Databricks $1B 購 Neon）；向量資料庫從獨立品類降格為通用 DB 的一種資料型別。⚠ 原文遭封鎖直連，本則依搜尋摘要重建、未全數核實。
> news｜https://venturebeat.com/data/six-data-shifts-that-will-shape-enterprise-ai-in-2026｜日期未確認｜rel 3｜`news/2026_july/05_VB_Six_Data_Predictions_2026/`

---

## 技術部落格（blog）

### 11. 合成資料三治理：安全生成、去重、漂移感知策展
dev.to（Maxim AI 背景）主張 RAG 合成評估資料須同時治理三件事，未經治理的合成資料會以重複灌水指標、以分佈漂移讓評估失真；建議 embedding 聚類抓 near-duplicate、**比對合成與 production 資料防洩漏**——正是本專案 paraphrase 增強 2578←170 該做而沒做的事。概念框架＋產品導流，無可複用數值參數。
> blog｜https://dev.to/kuldeep_paul/synthetic-data-for-rag-safe-generation-deduplication-and-drift-aware-curation-in-2025-3298｜2025-10-14｜rel 5｜`blogs/2026_july/01_Synthetic_Data_for_RAG_Dedup_Curation/`

### 12. 前 Bing 搜尋主管提出「向量索引衛生」：五大索引病＋六步法
Duane Forrester 主張 AI 答案引擎時代的內容可見度取決於 chunk 與 embedding 品質：臃腫 chunk、樣板重複、雜訊滲漏、內容型別錯配、過期 embedding 五大病，配預處理→chunk 紀律→去重→metadata→re-embed→hybrid 檢索六步法。無量化數據，但病徵清單與本專案 instruction 欄的 harness 雜訊高度同構——佐證**寫入層清洗優先於檢索端補救**。
> blog｜https://duaneforresterdecodes.substack.com/p/vector-index-hygiene-a-new-layer｜2025-09-29｜rel 4｜`blogs/2026_july/02_Vector_Index_Hygiene/`

### 13. lucidRAG 兩階段去重實錄：near-duplicate 不刪、改加 salience boost
本週參數最完整的一篇：ingestion 階段 near-duplicate 不刪除而是加 salience boost（每筆 +0.15、對數衰減、上限 1.0）——把重複視為「作者強調」的訊號；retrieval 階段 RRF 排序後跨文件留最高分變體。兩階段共用 **cosine 0.90 閾值**，全程確定性、內容不可變。自承短 segment embedding 品質差導致漏抓——對本專案短 instruction 列尤其相關。
> blog｜https://mostlylucid.net/blog/graphiticragdedupe｜2026-01-17｜rel 4｜`blogs/2026_july/03_lucidRAG_Evidence_Segment_Dedup/`

### 14. Azure AI Search 的 MMR 實作：λ=0.7、50 進 10 出
Azure 團隊成員示範在 RAG 管線加 MMR 重排：向量檢索取 50 筆、以 λ=0.7 權衡相關性與已選多樣性、貪婪選出 top 10，附完整 NumPy 實作。零索引改動的檢索後處理——同源 paraphrase 群裡第一筆選入後，其餘 marginal gain 立即崩落，等於查詢時 soft 去重。原文 403，依 ESPC 全文轉載產出。
> blog｜https://farzzy.hashnode.dev/enhancing-rag-with-maximum-marginal-relevance-mmr-in-azure-ai-search｜2026-01-16（轉載）｜rel 4｜`blogs/2026_july/04_MMR_Azure_AI_Search/`

### 15. Production RAG 八模組：去重應在 chunking 之前的文件層完成
Medium 工程總覽主張 chunk 層去重「慢、吵、浪費」，正解是正規化後 MD5 hash 的文件層去重＋file-hash 增量更新；並給 500 token chunk＋50 overlap 等經驗值。hash 法只抓完全重複、對語意近重複無解（與 lucidRAG 互補）。作者附帶「fine-tuning 昂貴且常不動針」——與本專案 P5 廢止結論相符。
> blog｜https://sabarishkumarg.medium.com/designing-rag-architectures-that-scale-chunking-deduplication-and-accuracy-improvements-1adb76dbd8ec｜2025-06-18｜rel 4｜`blogs/2026_july/05_Designing_RAG_Architectures_That_Scale/`

---

## GitHub（git，未取碼）

### 16. semhash：最順手的語意去重即插即用選項
MinishLab 輕量函式庫（939★、v0.4.1），self-dedup／離群過濾／代表樣本選取全程 CPU 可跑，**支援自訂 encoder 接 bge-m3**——「與召回同一向量空間判重」避免空間錯位。接法：`exchange_embeddings` 匯出 → `SemHash.from_records()` → `selected` 白名單重建索引。
> git｜https://github.com/MinishLab/semhash｜v0.4.1 2026-01-20｜rel 5｜`git/2026_july/01_semhash/`

### 17. sqlite-mmr：SQLite 內原生 MMR 重排虛擬表（4★、概念正確、極早期）
純 C 單檔 extension，把 MMR 做成可包 FTS5 表的 virtual table，直讀倒排索引取 matched tokens 免解壓。與本專案「SQLite + 本地 RAG + 召回多樣性」一比一對應，但多樣性算 lexical Jaccard 非 dense 空間、無 release——**參考實作價值大於直接投產**。
> git｜https://github.com/MayCXC/sqlite-mmr｜pushed 2026-06-23｜rel 5｜`git/2026_july/02_sqlite_mmr/`

### 18. ⚠ 反面教材：sieve——蹭關鍵字的空殼倉
描述標榜「多語語料語意去重、fast/offline/open」，實查 README 僅 11 行且內容（AMD GPU 測試清單、OOM 排障）與去重完全無關；帳號建立不滿兩個月、無 release、repo 僅 32KB。**建議剔除追蹤、勿 clone 執行（供應鏈風險）**。教訓：語意去重賽道熱度升高後蹭關鍵字 repo 開始出現，README 與描述一致性是快速濾網。
> git｜https://github.com/Protonhash/sieve｜pushed 2026-06-25｜rel 4→實查降 1｜`git/2026_july/03_sieve_shell_repo_warning/`

### 19. text-dedup：BigCode 血統的 lexical 去重全家桶
MinHash/SimHash/Suffix Array/Bloom Filter 四法俱全、TOML 驅動、附 cluster 稽核輸出（765★、Zenodo DOI）。與 semhash 互補：「改幾個字的 echo」用 MinHash n-gram 就抓到、免跑 embedding。release tag 停 2023 但主幹 2026-03 仍推進。
> git｜https://github.com/ChenghaoMou/text-dedup｜pushed 2026-03-09｜rel 4｜`git/2026_july/04_text_dedup/`

### 20. datasketch v1.10.0：寫入時 LSH 查重閘的首選積木
老牌機率資料結構庫（2,940★），四月發 v1.10.0（修 MinHashLSH 跨後端 bug、AsyncMinHashLSH 轉正、Python 3.10+）。依賴僅 NumPy/SciPy——最適合在 ingestion 層嵌一道 MinHashLSH 寫入時查重閘，從源頭擋 paraphrase 洪水，與既有 `>15` 字閘同位置的第二道防線。
> git｜https://github.com/ekzhu/datasketch｜v1.10.0 2026-04-17｜rel 4｜`git/2026_july/05_datasketch/`

---

## 對主專案的收斂觀察（三行）

1. **兩層共識**＝離線語意去重（semhash/SemDeDup 式）＋查詢時冗餘感知選擇（MMR/AdaGReS/DF-RAG，全部免訓練）；本專案若日後重啟召回，施工圖已齊——且 `source_instruction` 溯源折疊比任何無監督法更乾淨。
2. **兩個獨立來源與本專案既有結論互證**：InfoQ「策展勝調參」（bge-m3 實測）↔ curation 勝 accumulation；Milvus「時間衰減」產品化 ↔ 召回是貶值資產。
3. **ScalDPP 的負 margin 幾何證據**（cosine 空間天然偏好冗餘）為 13% 天花板與 top-k 同源霸榜提供了理論註腳——問題不在 bge-m3 不夠強，在 cosine 幾何本身。
