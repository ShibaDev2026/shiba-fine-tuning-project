# Reducing False Positives in RAG Semantic Caching: a Banking Case Study

- **來源 URL**：https://www.infoq.com/articles/reducing-false-positives-retrieval-augmented-generation/
- **發布日期**：2025-11-14
- **來源類型**：news（InfoQ 案例文）
- **relevance**：4
- **與主專案關聯**：本專案召回同樣困在「表面語言相似≠功能意圖相同」（短控制詞巧合匹配 0.678 > floor 0.35、13% 採納天花板）；本文用 bge-m3 實測且結論「內容策展 > 模型選擇或調閾值」——直接呼應 curation 勝 accumulation。

## 分析

銀行客服 RAG semantic caching 假陽性實戰。病灶：零語境匹配——bi-encoder 憑表面相似而非功能意圖配對，「我不想要這張卡」以 88.7% 信心命中「關閉投資帳戶」流程，部分模型假陽性率 99%。

四階段實驗（1,000 條真實銀行查詢、7 個 bi-encoder）：
1. 基準（閾值 0.7）：e5-large-v2 與 instructor-large 假陽性 99%、all-MiniLM-L6-v2 19.3%。
2. 調閾值（0.7→0.93）：最佳仍 13.4–14.1% 假陽性，且命中率掉到 53–69.8%、LLM 呼叫成本反升——**單靠閾值救不了**。
3. **突破點＝預載快取架構**：100 條黃金 FAQ＋300 條戰略干擾項（3:1；主題相鄰 0.8-0.9、語意近似 0.85-0.95、跨域 0.6-0.8），假陽性平均降 51.3%——核心原則「**確保最優候選存在，比優化檢索演算法更有效**」。
4. 快取品質控制後：instructor-large 3.8%（閾值 0.93）、**bge-m3 4.5%（閾值 0.8、命中 78.6%、20.72ms）**、all-MiniLM 4.7%（7.46ms）。

生產建議：精度選 instructor-large、性價比選 bge-m3、避開 e5-large-v2。核心洞察：假陽性根因不在模型能力，而在候選集合缺乏足夠精確的候選——**內容策展壓過演算法優化**。
