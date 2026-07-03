# Designing RAG Architectures That Scale: Chunking, Deduplication, and Accuracy Improvements

- **來源 URL**：https://sabarishkumarg.medium.com/designing-rag-architectures-that-scale-chunking-deduplication-and-accuracy-improvements-1adb76dbd8ec
- **發布日期**：2025-06-18
- **來源類型**：blog（Medium）
- **relevance**：4
- **與主專案關聯**：主張「文件層去重先於 chunk 層」與 incremental update（file hash 追蹤）——對應 stop_hook 寫入層的 per-exchange 去重時點選擇問題。

## 分析

核心論點：多數開源 RAG 範本在 production 失敗，因為只做 retrieval-generation 而漏掉基礎工程——garbage in, garbage out，文件處理層決定系統可靠度。

八模組架構：①文件預處理（→乾淨文字＋語意結構＋去噪＋metadata）；②**去重——在 chunking 之前做文件層去重**（chunk 層比對「慢、吵、浪費」），方法為正規化文字（小寫、空白摺疊、去標點）後取 MD5 hash；③chunking——recursive splitting、**500 token chunk + 50 token overlap**、title-aware、表格另抽；④embedding 持久化 + hybrid retrieval（dense+sparse）；⑤增量更新——追蹤 file hash 與版本化 metadata，只處理新/改文件；⑥回饋迴圈——顯性評分＋隱性訊號，分析低分查詢改 prompt/chunking；⑦prompt 工程（結構化 context、A/B 測試）；⑧production 支柱（metadata filtering、session memory、觀測、PII 遮罩、fallback）。

侷限：MD5 hash 只抓 exact duplicate、對 paraphrase 級近重複無力（與 lucidRAG 語意去重互補）；參數（500/50）為經驗值無 benchmark；作者自承 fine-tuning「昂貴且常常不動針」——與本專案 P5 廢止結論一致。
