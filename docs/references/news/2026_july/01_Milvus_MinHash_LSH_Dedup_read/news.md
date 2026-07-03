# MinHash LSH in Milvus: The Secret Weapon for Fighting Duplicates in LLM Training Data

- **來源 URL**：https://milvus.io/blog/minhash-lsh-in-milvus-the-secret-weapon-for-fighting-duplicates-in-llm-training-data.md
- **發布日期**：2025-05-16
- **來源類型**：news（官方產品發布技術文）
- **relevance**：5
- **與主專案關聯**：索引曾被 paraphrase 增強污染（2578←170 source），MinHash LSH 是近重複偵測標準工具，可用於去污染前的近重複掃描。

## 分析

Milvus 2.6 原生內建 MinHash LSH（Locality Sensitive Hashing）索引，鎖定 LLM 訓練資料去重場景。原理兩段式：(1) 文件先做 shingling（例：k=3 逐詞切重疊片段）→ 多個獨立雜湊函數各取最小值組成固定長度簽名向量，兩簽名對齊位置相等的機率近似原始 shingle 集合的 Jaccard 相似度 `J(A,B)=|A∩B|/|A∪B|`；(2) LSH banding：長度 N 的簽名切 b 個 band、每 band r 維（N=b×r），任一 band 落同桶即標記為候選近重複對，之後可選 Jaccard rerank 精算，最終 Union-Find 聚類成完整去重組。

實作面：schema 定義 BINARY_VECTOR 欄放 MinHash 簽名（範例 MINHASH_DIM=128、64-bit、批次 2000 筆），metric type `MHJACCARD`、index type `MINHASH_LSH`，簽名可用 datasketch `MinHash(num_perm=128)` 預生成。band 數與雜湊函數數量是 recall/precision/效能三方權衡。

實案：一家 LLM 公司在 Zilliz Cloud 對 10 億份文件去重，比 MapReduce 方案快 2 倍以上、成本降 3-5 倍。動機面四危害：訓練算力浪費、過擬合、逐字記憶（隱私/著作權）、train-test 污染。

**產業訊號**：去重從離線 MapReduce 批次工作轉為向量資料庫的一級索引能力——「資料品質基建」被收編進 vector DB 產品線。
