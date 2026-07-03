# DF-RAG: Query-Aware Diversity for Retrieval-Augmented Generation

- **來源 URL**：https://arxiv.org/abs/2601.17212
- **發布日期**：2026-01-23（EACL 2026 Findings 接收）
- **來源類型**：paper（arXiv）
- **relevance**：5
- **與主專案關聯**：免訓練、test-time 動態調多樣性的 MMR 系方法——三篇查詢側方法中工程門檻最低、最能直接掛在 `rag.py:_vector_search` 後的一個。

## 分析

問題設定：推理密集型 QA 上，標準 RAG 按相關性排序會系統性選進彼此重複的 chunk，擠掉互補證據。

方法：建立在 MMR（Maximal Marginal Relevance，最大邊際相關性）框架上——迭代選「與 query 相關且與已選集合不相似」的 chunk——關鍵改進是 **query-aware 動態多樣性**：多樣性權重不是全域固定超參，而是 test time 依查詢特性動態決定，全程零 fine-tuning、零訓練。

實驗數字：推理密集型基準上比標準 RAG 提升 F1 4–10%；作者估出 oracle 上限（完美多樣性選擇）為 +18% 絕對 F1，DF-RAG 捕獲其中 **91.3%** 的可得增益。

**方法論可抄的點**：oracle gap 分析框架——先量「完美選擇的上限」再決定值不值得做，正合本專案 base-assumption-first 紀律（任何 A-vs-B 對照前可先量 oracle 天花板）。

適用性：高——純推理時重排、無訓練需求、計算只是 embedding 相似度上的 greedy，772 列規模開銷可忽略；本專案索引的 15× 同源展開正是 MMR 類方法最擅長壓制的型態（同源列彼此 cosine 極高，第一列選入後其餘 marginal gain 立即崩落）。

侷限：增益主張綁定「推理密集型」基準，單跳事實題增益可能縮水；abs 頁未披露動態權重具體機制與所用 embedding 模型；與 AdaGReS 同樣未解決「檢回多少候選再重排」的 pool size 問題。
