# Scaling DPPs for RAG: Density Meets Diversity

- **來源 URL**：https://arxiv.org/abs/2604.03240
- **發布日期**：2026-04（arXiv ID 推定；abs 頁顯示日期不一致）
- **來源類型**：paper（arXiv）
- **relevance**：5
- **與主專案關聯**：唯一直接在 bge-m3 上做實驗的多樣性選擇法，但需訓練 P-Adapter＋標註正例子集——方向印證強、直接落地弱。

## 分析

問題設定：top-k 只排相關性、忽略 chunk 間關係，導致冗餘 context。

方法三件套：①**P-Adapter**——輕量 bottleneck 前饋網路，把 chunk embedding 變換到能編碼「互補性」的空間，不動 base encoder，初始檢索不啟用、只在子集選擇階段用；②**動態 DPP（Determinantal Point Process，行列式點過程）kernel**——不預訓固定 kernel，對每次檢回的候選動態建 Γ=QLQ（Q 可吸收 reranker 分數）；③**DML（Diverse Margin Loss）**——集合級目標，懲罰「冗餘負子集行列式大於真值正子集」，用 LogSumExp＋softplus 可微化，比標準 NLL 收斂穩（NDCG@10 高 4.1%）。

實驗：MultiHop-RAG 2,255 題（2–4 hop），embedding 涵蓋 bge-large-en-v1.5、**bge-m3**、Qwen3-Embedding-0.6B/4B。無 reranker 時平均 NDCG@10 +7.7%、Recall@10 +14.3%；預算收緊到 K=4 增益放大（NDCG@4 +14.2%、Recall@4 +31.9%）；4-hop 最顯著（NDCG@10 0.4913 vs baseline 0.3729，+31.8%）。選擇階段開銷極小（greedy MAP O(k²N)），訓練單卡 0.3–1.5 小時。

**關鍵旁證（對本專案最有價值的一點）**：原始 embedding 空間裡，真值正子集的行列式竟低於冗餘負子集（margin 為負）——即 **bge-m3 原生 cosine 幾何天然偏好冗餘**，P-Adapter 變換後 margin 才轉正。這替「top-k 被同源 paraphrase 擠滿」提供了幾何解釋。

適用性：中偏低——需要標註「正確互補子集」訓練 DML，本專案無此標註。侷限：僅 MultiHop-RAG 單基準；未明列 limitations；exact MAP NP-hard 靠 greedy 近似。
