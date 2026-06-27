# ADORE: Iterative Query Expansion with Retrieval-Grounded Relevance Feedback

- **arXiv URL**: https://arxiv.org/abs/2606.13905
- **發布日期**: 2026-06-11
- **來源類型**: paper
- **relevance**: 5
- **作者群**: Amin Bigdeli, Negar Arabzadeh, Radin Hamidi Rad, Sajad Ebrahimi, Charles L. A. Clarke, Ebrahim Bagheri
- **與主專案關聯**: retrieval-grounded relevance feedback 的迭代查詢擴展，回應主線「可稽核 RAG 重用」與召回多樣性/去污染需求（用 corpus 回饋抑制誤導詞、補未覆蓋詞）。

---

## Abstract

LLM-based query expansion improves retrieval by enriching the original query with additional context. Yet most methods remain generation-driven, producing plausible pseudo-documents or expansions without checking how the target corpus responds. This can introduce retrieval drift, amplify misleading vocabulary, or miss terms that distinguish relevant from non-relevant documents. We argue that effective expansion requires retrieval-grounded feedback, not just single-pass generation or unverified iteration. We introduce ADORE (ADapt, Observe, Relevance Evaluate), an iterative framework that turns retrieval outcomes into feedback for the next expansion. At each round, an LLM generates pseudo-passages, a retriever exposes the corpus response, and a relevance assessor evaluates retrieved documents against the original query. These judgments identify what to reinforce, what remains undercovered, and what to suppress. Across TREC Deep Learning, BEIR, and BRIGHT, ADORE consistently outperforms strong query expansion baselines with notable improvements across nearly all evaluation settings, improving average nDCG@10 by 24.5% over BM25 and 3.6% over the strongest prior query expansion method on BEIR, and by 122.9% over BM25 and 9.2% over the best query expansion baseline on BRIGHT. Our code and data are publicly available.

---

## Method highlights (from abstract)

- Argues query expansion needs retrieval-grounded feedback, not single-pass generation or unverified iteration.
- ADORE = ADapt, Observe, Relevance Evaluate — an iterative loop.
- Each round: LLM generates pseudo-passages → retriever exposes corpus response → relevance assessor evaluates retrieved docs against the original query.
- Feedback identifies what to reinforce, what remains undercovered, and what to suppress (counters retrieval drift / misleading-vocabulary amplification).
- Evaluated on TREC Deep Learning, BEIR, BRIGHT; reported +24.5% nDCG@10 over BM25 and +3.6% over best prior QE on BEIR; +122.9% over BM25 and +9.2% over best QE baseline on BRIGHT. Code and data public.
