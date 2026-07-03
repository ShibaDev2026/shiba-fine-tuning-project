# AdaGReS: Adaptive Greedy Context Selection via Redundancy-Aware Scoring for Token-Budgeted RAG

- **來源 URL**：https://arxiv.org/abs/2512.25052
- **發布日期**：2025-12-31
- **來源類型**：paper（arXiv，preprint under review）
- **relevance**：5
- **與主專案關聯**：查詢時多樣性層的直接候選——在 bge-m3 cosine top-k 之後加一個免調參的 redundancy-aware greedy 重選，正對「同源展開列擠佔 top-k」的症狀。

## 分析

問題設定：token 預算受限的 RAG 中，標準 top-k 只按 query 相似度排序，常選進彼此高度重複的 chunk，浪費預算。

方法：集合層級目標函數 `F(q,C)=α·S_qC(q,C)−β·S_CC(C)`——前項是 query-chunk 相關性總和、後項是集合內兩兩相似度的冗餘懲罰；greedy 迭代選 marginal gain `ΔF(x|C)=α·sim(q,x)−β·Σsim(x,c)` 最大者，直到無正增益或預算耗盡。關鍵貢獻是 **β 的閉式自適應校準**：`β* = α·E[sim(q,x)] / ((k̄−1)/2·E[sim(x,y)])`，其中 k̄≈T_max/L̄ 由預算與平均 chunk 長度估出——從語料統計自動定冗餘權重，免手調（MMR〔Maximal Marginal Relevance，最大邊際相關性〕的 λ 手調痛點就在此）。理論上證明目標具 ε-近似次模性（ε-approximate submodularity），greedy 有近似最優保證。

實驗：Natural Questions（NQ）＋高冗餘專有藥物語料；主指標 IoU。NQ 複雜查詢上比 similarity-only top-k 提升 8–15 個百分點；固定 β∈{0.55,0.65,0.7} 全區間皆勝 baseline，自適應版更穩。

對千級小語料的適用性：極高——只需 embedding 兩兩 cosine，772 列上毫秒級；自適應 β 依語料統計自校，污染語料（E[sim(x,y)] 偏高）會自動加重懲罰。侷限：preprint；未與 MMR 直接對打；作者自承冗餘分布極不均勻的長 context 下 greedy 可能失衡；藥物語料私有不可重現。
