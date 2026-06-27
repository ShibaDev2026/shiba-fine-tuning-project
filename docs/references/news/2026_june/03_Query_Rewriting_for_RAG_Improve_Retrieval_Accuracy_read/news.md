---
title: "Query Rewriting for RAG: How to Improve Retrieval Accuracy"
url: https://www.meilisearch.com/blog/query-rewrite-rag
published: 2026-06-09
author: Maya Shin (Head of Marketing @ Meilisearch)
source_type: news
relevance: 4
project_link: 系統化整理 query rewriting 技術光譜（expansion/decomposition/paraphrasing/multi-query/step-back），直接支撐主線 P2 查詢側召回改善的技術選型與評估指標。
---

# Query Rewriting for RAG: How to Improve Retrieval Accuracy

Source: Meilisearch blog — Maya Shin, 2026-06-09 (14 min read)

## Key Points

### What it is
Modifying user queries before retrieval to produce "a better, more structured version that matches the language used in the datasets and knowledge bases." Differs from query expansion (which adds related terms rather than restructuring).

### Why it matters
Retrieval quality directly determines LLM response accuracy. Converting queries "into a form better understood by the retrieval layer" locates more relevant documents and reduces hallucinations.

### How it works in a RAG pipeline
1. User submits natural-language question (potentially vague/incomplete)
2. A rewrite model transforms the query (LLM analysis or transformation algorithms)
3. Rewritten query reaches the retriever for vector or hybrid search
4. A reranking model improves relevance via k-scoring
5. LLM generates a grounded response from retrieved docs

### Common techniques
- **Query Expansion** — add related terms ("heart attack treatment" → also "myocardial infarction")
- **Query Decomposition** — break complex multi-part questions into simpler sub-queries
- **Query Paraphrasing** — alternative wording to capture linguistic variation
- **Multi-Query Generation** — several rewritten versions targeting different perspectives
- **Step-Back Prompting** — generate a broader general question first to identify underlying concepts, then refine

### Problems solved
Ambiguous/vague queries; missing context; vocabulary mismatch between users and datasets; conversational follow-ups needing prior context; enterprise search over large datasets.

### Implementation steps
1. **Capture and Normalize** — clean/format query, remove unnecessary tokens
2. **Generate Rewritten Query** — LLM + prompt engineering into retrieval-friendly form
3. **Retrieve Documents** — pass rewritten query to retriever (vector or hybrid)
4. **Generate Final Response** — send retrieved docs + original query to LLM

### Key limitations
- Over-expansion can introduce irrelevant documents
- Semantic drift may alter query meaning
- Additional LLM calls increase latency and cost
- Evaluation complexity requires extensive benchmarking
- Not a complete solution alone — metadata filtering, reranking, and strong embeddings still needed

### Evaluation metrics
Recall@k; MRR (Mean Reciprocal Rank); NDCG; Answer Accuracy; Human Evaluation.

### Comparisons
- **vs. Reranking:** rewriting modifies queries before retrieval (improves recall); reranking reorders retrieved docs (improves precision). Most systems combine both.
- **vs. Query Expansion:** rewriting restructures the query (reflects intent); expansion adds supplementary terms (improves recall via terminology).

### Tools cited
Meilisearch (fast hybrid search for RAG); Azure AI Search (hybrid search + semantic ranking); LangChain (orchestration with LLM-based query transformation).

### Conclusion
Query rewriting is becoming essential for modern RAG since "most user queries don't match the language of the datasets and knowledge bases"; integrated with strong retrieval infrastructure it significantly enhances production performance.
