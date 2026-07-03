# Byte-Exact Deduplication in RAG: A Three-Regime Empirical Analysis

- **來源 URL**：https://arxiv.org/abs/2605.09611
- **發布日期**：2026-05-10
- **來源類型**：paper（arXiv）
- **relevance**：5
- **與主專案關聯**：直接命中「索引被 paraphrase 增強污染 15× 同源展開」的離線去重層——其對話式 AI 情境 80.34% 冗餘率與 772 exchange 語料的污染型態同構。

## 分析

問題設定：RAG（Retrieval-Augmented Generation，檢索增強生成）管線中，chunk 層級的位元組完全一致（byte-exact）重複到底有多普遍、去掉會不會傷品質？作者刻意選最保守的去重法（確定性、零誤殺、可用雜湊實作），在跨公開基準（含 22.2M 篇 BeIR passages）的實測中辨識出三種冗餘 regime：學術檢索語料僅 0.16%（去重幾乎無收益）、企業型語料 24.03%（中度收益）、對話式 AI 語料高達 80.34%（去重即省 8 成 context）。品質驗證用跨供應商 5 judge（四大 LLM 供應商）評估，宣稱零可測品質退化，且退化幅度壓在 Wilson 95% 信賴上界 5% 之內——「省 token 不賠品質」的統計化表述。

對千級小語料的適用性：本專案語料屬其第三 regime（對話式），且 paraphrase 增強造成的同源展開比 byte-exact 更廣（語意重複、非位元組重複），故此文結論是**下界**——byte-exact 去重能安全清掉的只是最粗的一層，15× 同源污染需再疊語意層去重。方法本身零成本、確定性、可離線跑，772 列規模一個 script 即可。

侷限：只處理 byte-exact，near-duplicate/paraphrase 完全不碰；三 regime 分界是經驗性觀察非理論；judge 評估仍是 LLM-as-judge（本專案已知其偏誤）；單一作者、未見頂會接收記錄。
