# ThinkQE: Query Expansion via an Evolving Thinking Process

- **arXiv URL**: https://arxiv.org/abs/2506.09260
- **發布日期**: 2025-06-10 (v1); last revised 2026-03-09 (v2); EMNLP 2025
- **來源類型**: paper
- **relevance**: 5
- **作者群**: Yibin Lei, Tao Shen, Andrew Yates
- **與主專案關聯**: 查詢側 test-time query expansion + corpus-interaction 迭代精煉，直接對應主線 P2 HyDE / `rag.py:_vector_search` 召回改善方向。

---

## Abstract

Effective query expansion for web search benefits from promoting both exploration and result diversity to capture multiple interpretations and facets of a query. While recent LLM-based methods have improved retrieval performance and demonstrate strong domain generalization without additional training, they often generate narrowly focused expansions that overlook these desiderata. We propose ThinkQE, a test-time query expansion framework addressing this limitation through two key components: a thinking-based expansion process that encourages deeper and comprehensive semantic exploration, and a corpus-interaction strategy that iteratively refines expansions using retrieval feedback from the corpus. Experiments on diverse web search benchmarks (DL19, DL20, and BRIGHT) show ThinkQE consistently outperforms prior approaches, including training-intensive dense retrievers and rerankers.

---

## Method highlights (from abstract)

- Test-time query expansion framework; no additional training required.
- Two key components: (1) a thinking-based expansion process encouraging deeper, more comprehensive semantic exploration; (2) a corpus-interaction strategy that iteratively refines expansions using retrieval feedback from the corpus.
- Targets the exploration + result-diversity gap left by narrowly-focused LLM expansions.
- Evaluated on DL19, DL20, and BRIGHT; reported to outperform training-intensive dense retrievers and rerankers.
