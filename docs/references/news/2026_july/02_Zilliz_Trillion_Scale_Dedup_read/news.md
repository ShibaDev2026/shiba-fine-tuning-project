# Data Deduplication at Trillion Scale: How to Solve the Biggest Bottleneck of LLM Training

- **來源 URL**：https://zilliz.com/blog/data-deduplication-at-trillion-scale-solve-the-biggest-bottleneck-of-llm-training
- **發布日期**：2025-07-26（原頁 JS 渲染，內容依 Zilliz 官方 Medium 鏡像確認）
- **來源類型**：news（官方技術發布）
- **relevance**：5
- **與主專案關聯**：EV gate／keystone probe 均因語料重複度測量而生；本文「重複資料四危害」與 MinHash LSH 工程化細節可直接對映索引去污染需求（規模上本專案是玩具級、原理相同）。

## 分析

Zilliz 針對兆級 token 訓練語料去重的工程長文。問題面：訓練集規模已到 Kimi K2 15.5T tokens、LLaMA 3.1 15T、GPT-4 估 13T，重複內容造成算力浪費、過擬合、逐字記憶、評估洩漏；傳統法全失效——精確比對算不動、語意去重成本爆炸、MapReduce 跑單一資料集要數週至數月。

解法為 MinHash＋LSH 三層架構：文件→shingles→獨立雜湊取最小值成定長簽名；LSH 把簽名切 band 各自雜湊入桶（band 數/行數控制 recall/precision/效能）；只比對同桶候選。工程數字：780 維 int32 簽名、30GB 檔案導入從 15 分鐘壓到 4 分鐘；查詢吞吐 44,000 向量/秒。

**關鍵陷阱（值得記）**：頂級 AI 客戶對數十億資料點去重時撞上 **float32 無法精確表示 uint32**（float32 精確整數僅至 ~1,677 萬、uint32 到 43 億）→ 簽名必須走 binary vector 路徑，否則雜湊值靜默失真。

產業解讀：去重被定位為 LLM 訓練的第一瓶頸而非後處理雜務，vector DB 廠商把「資料品質」作為新戰場。
