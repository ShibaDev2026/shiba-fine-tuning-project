# Synthetic Data for RAG: Safe Generation, Deduplication, and Drift-Aware Curation

- **來源 URL**：https://dev.to/kuldeep_paul/synthetic-data-for-rag-safe-generation-deduplication-and-drift-aware-curation-in-2025-3298
- **發布日期**：2025-10-14
- **來源類型**：blog（dev.to，Maxim AI 背景）
- **relevance**：5
- **與主專案關聯**：本專案索引正是被「合成/paraphrase 增強資料」污染（2578←170 源）的實例——文中去重與 drift-aware curation 直接對應清污方向。

## 分析

核心論點：RAG 評估集光靠 production 資料不夠（隱私、稀有 edge case、多樣性缺口），必須程式化合成；但劣質合成會引入偏差、重複與分佈漂移（distribution drift），反而毀掉評估可信度。

方法三維：
1. **安全生成（Safe Generation）**：source grounding + 驗證工作流保事實性；控制變異 + 多樣性稽核（diversity audit）防偏差；對抗測試加安全約束。
2. **去重（Deduplication）**：exact duplicate 直接移除（防指標灌水）；near-duplicate 用 embedding + clustering 做語意相似偵測；**比對合成樣本 vs production 資料防資料洩漏（data leakage）**。
3. **漂移感知策展（Drift-Aware Curation）**：統計方法 + clustering 監測查詢模式/文件演化/品質期待的分佈移動；production 失敗案例持續轉為測試案例形成改進迴圈。

對本專案最可轉用：「**合成樣本應與源語料去重比對防洩漏**」——正是 paraphrase 增強 2578←170 該做而沒做的事。

侷限：全文無任何具體數值閾值或 benchmark（僅提 threshold tuning 不給值）；明顯是 Maxim AI 產品置入文（Data Engine），方法偏概念框架、可操作性須自行補齊。
