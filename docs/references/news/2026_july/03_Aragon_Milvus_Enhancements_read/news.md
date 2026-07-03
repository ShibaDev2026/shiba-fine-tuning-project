# Milvus Previews Vector Database Enhancements

- **來源 URL**：https://aragonresearch.com/milvus-previews-vector-database-enhancements/
- **發布日期**：2025-05-16（預告 Milvus 2.6）
- **來源類型**：news（分析師報導）
- **relevance**：4
- **與主專案關聯**：bge-m3 + SQLite 自建召回的能力基準線參照——特別是「時間衰減相關性」被產品化＝「召回是貶值資產」的工程化對應。

## 分析

Aragon Research 對 Milvus 2.6 預覽版的分析師整理，七項功能：(1) **RaBitQ 1-bit 量化**——記憶體佔用降 72%、QPS 提升 4 倍、召回損失最小；(2) 短語與多詞精確匹配，補 dense retrieval 在法律/技術文件上的精確性短板；(3) **時間衰減相關性（time-decay relevance）**——依新近度加權結果；(4) 冷熱分層儲存——支撐數百億向量規模；(5) Woodpecker WAL——雲原生零磁碟日誌，取代 Kafka/Pulsar 外部佇列；(6) MinHash LSH 去重索引；(7) 多攝影機即時身分追蹤。

**三個產業訊號**：①量化（1-bit）成為記憶體成本主戰場；②「時間衰減」做成一級功能＝**正式承認向量索引內容會貶值、新近度是通用排序訊號**（與本專案「召回是貶值資產」判斷同構）；③WAL 內建化反映 vector DB 從「元件」走向「自足平台」。

侷限：功能多為預覽宣稱，正式版數字待驗；分析師文體、無獨立實測。
