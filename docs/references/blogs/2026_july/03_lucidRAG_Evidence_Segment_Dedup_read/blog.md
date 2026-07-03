# Deduplication of Graphitic RAG Evidence Segments in lucidRAG

- **來源 URL**：https://mostlylucid.net/blog/graphiticragdedupe
- **發布日期**：2026-01-17
- **來源類型**：blog（mostlylucid，實作設計實錄）
- **relevance**：4
- **與主專案關聯**：「near-duplicate 不刪除、改加 salience boost（重複＝作者強調的訊號）」的設計——對 770 淨列中殘留的語意近重複提供「去重不失訊」的具體參數化路徑。

## 分析

核心論點：去重是「一級編譯問題，非事後過濾」——字串比對不夠（同概念以不同措辭/結構/格式重現），多筆近重複結果會劣化而非強化輸出。

兩階段策略：
1. **Ingestion 去重**（單文件內、索引前）：exact duplicate（content hash 相同）靜默丟棄；**near-duplicate 不刪、改給 salience boost**——把重複視為作者強調的證據。
2. **Retrieval 去重**（跨文件、RRF 排序後）：留最高分變體、丟低分。

**關鍵參數（全文最有價值處）**：cosine 相似閾值 **0.90**（兩階段共用）、salience 下限 0.05（濾噪）、每筆 near-duplicate boost **+0.15**、salience 上限 1.0、boost 衰減建議對數模式（`boostPerNearDuplicate × log₂(1+count)`）。

五個設計不變量：排序後保序、不消滅概念、尊重文件邊界、內容不可變（只動選取與 salience）、完全確定性。效能：ingestion O(n²)、50–500 segment <100ms；retrieval 20–100 segment <10ms。

明確非目標：不做事實矛盾偵測、不做真值正規化、entity resolution 交給 GraphRAG。自承侷限：0.90 閾值有 false positive 風險；**短 segment embedding 品質差造成 false negative——對本專案的短 instruction 列尤其相關**。
