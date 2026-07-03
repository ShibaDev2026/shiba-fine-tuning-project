# Enhancing RAG with Maximum Marginal Relevance (MMR) in Azure AI Search

- **來源 URL**：https://farzzy.hashnode.dev/enhancing-rag-with-maximum-marginal-relevance-mmr-in-azure-ai-search
- **發布日期**：日期未確認（原文 hashnode 403 封鎖；ESPC 轉載標 2026-01-16，本檔依轉載版產出）
- **來源類型**：blog（作者 Farzad Sunavala，Azure AI 團隊）
- **relevance**：4
- **與主專案關聯**：MMR 是純檢索後處理、零索引改動的召回多樣性解法——對 paraphrase 污染造成「top-k 全是同源近重複」對症下藥。

## 分析

核心論點：RAG top-k 檢索常回傳彼此高度相似的文件，餵給 LLM 的 context 單一化、答案缺角；MMR（Maximum Marginal Relevance，最大邊際相關性）以重排序同時權衡相關性與多樣性。

公式：`MMR(Dᵢ) = λ·Sim(Dᵢ,Q) − (1−λ)·max[Sim(Dᵢ,Dⱼ)]`——λ=1 純相關、λ=0 純多樣，文中示例 **λ=0.7**。

實作五步：向量檢索取 top-N（**初始 50 筆**）→ cosine 算相關/多樣分 → 迭代選 MMR 最大者 → 從候選池移除 → 回傳重排結果（**MMR 後取 top 10**）。embedding 用 text-embedding-3-large（3072 維）、NumPy cosine 實作。

對本專案的直接價值：MMR 是 greedy 後處理，可直接套在 `rag.py:_vector_search` 的候選池上，不動 bge-m3 也不動索引；索引含同源 paraphrase 群時，`max Sim(Dᵢ,Dⱼ)` 懲罰項天然壓制同群霸榜——**檢索端 soft 去重，與寫入層清污互補**。

侷限：作者自承效果依資料集/索引策略/任務而異；評估只比較檢索結果差異、非端到端 RAG 評估（無 answer quality benchmark）。
