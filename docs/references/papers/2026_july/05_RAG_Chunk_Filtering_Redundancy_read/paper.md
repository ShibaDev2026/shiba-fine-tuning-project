# Reducing Redundancy in Retrieval-Augmented Generation through Chunk Filtering

- **來源 URL**：https://arxiv.org/abs/2604.24334
- **發布日期**：2026-04-27
- **來源類型**：paper（arXiv）
- **relevance**：4
- **與主專案關聯**：離線索引瘦身的三路方法比較（語意/主題/實體），semantic 閾值過濾正是清 15× paraphrase 同源展開最對症的一路——byte-exact 抓不到的近重複由此接手。

## 分析

問題設定：chunking 過程引入的冗餘讓向量索引虛胖，能否用輕量離線過濾縮小索引而不傷召回？

三路方法：①**semantic**——embedding cosine 超過閾值 τ 即刪；②**topic-based**——先用 BERTopic 分主題，只在同主題內判重（降低跨主題誤殺）；③**NER（Named Entity Recognition）兩變體**——NER Exact（實體集合完全相同才刪）與 NER Half（實體重疊 ≥50% 即刪）。

資料集：Chroma 五語料（State of the Union、Wikitext、Chatlogs、Finance、PubMed）＋SQuAD 1.1 dev＋WebFAQ。指標為 token 級 precision/recall/IoU。

結果：**NER Exact 最穩健**——索引縮 25–36% 而 recall 掉 <6%、IoU 掉 <8%；semantic 縮 20–35%，SQuAD 上「單靠 semantic 已是強 baseline」；topic-based 相對 semantic 只有邊際改善；NER Half 過激、precision 明顯退化；random 對照組全面崩。

適用性判斷：高但要挑路——本專案 772 exchange 是**對話/指令語料，實體密度低**（NER 路徑會漏掉大量無實體描述性列），semantic 閾值過濾最對症，且已知污染是同源 paraphrase（cosine 極高、好切）。另本專案有 `source_instruction` 溯源欄位，**直接按 source 折疊比任何無監督過濾更乾淨**——此文的價值在提供驗收基準：「過濾後 recall 損失應 <6%」。

侷限：只評檢索層、未測端到端生成品質；NER 有實體密度偏差；部分過濾會誤刪含參考答案的 chunk（oracle 上限下降）但檢索指標仍穩——提醒驗收不能只看檢索指標。
