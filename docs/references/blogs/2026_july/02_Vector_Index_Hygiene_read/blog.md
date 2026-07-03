# Vector Index Hygiene: A New Layer of Technical SEO

- **來源 URL**：https://duaneforresterdecodes.substack.com/p/vector-index-hygiene-a-new-layer
- **發布日期**：2025-09-29
- **來源類型**：blog（Substack，作者為前 Bing 搜尋主管 Duane Forrester）
- **relevance**：4
- **與主專案關聯**：「index hygiene」概念正對應 `exchange_embeddings` 的 ingestion 雜訊清洗待辦（slash command / stdout echo 混入 instruction 欄）——入庫前預處理而非事後補救。

## 分析

核心論點：SEO 已進入「檢索時代」，內容能否被 answer engine（ChatGPT/Gemini/Claude/Perplexity）召回，取決於 chunk 與 embedding 的乾淨度——作者稱之為 vector index hygiene。

五種索引病：①跨主題的臃腫 block（弱 embedding）；②boilerplate 重複（相同向量淹沒獨特內容）；③sidebar/CTA/footer 雜訊滲入主內容；④內容型別錯配（FAQ 與長文同法切）；⑤模型過期造成 stale embedding。

六步法：①embedding 前剝離導航/樣板/橫幅；②依內容型別調 chunk 大小、最小 overlap；③去重（避免各文重複的導言/摘要）；④metadata 標註（型別/語言/日期/URL）支援檢索過濾；⑤模型升級後 re-embed、按內容變更節奏 refresh；⑥檢索端 hybrid search（dense+keyword）+ RRF（Reciprocal Rank Fusion）+ re-ranking。

附 cookie banner 案例：跨頁完全相同的同意橫幅產生大量重複向量、推向 lost-in-the-middle。

對本專案的映射：病徵清單幾乎逐條對應 instruction 欄的 harness 雜訊（slash echo＝boilerplate、system-reminder＝noise leakage）——**佐證「寫入層清洗優先於檢索端補救」**。

侷限：零量化 benchmark、無具體 chunk 長度/overlap/refresh 頻率建議；SEO 視角觀念文。
