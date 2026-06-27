---
title: "Advanced Query Transformations to Improve RAG"
url: https://towardsdatascience.com/advanced-query-transformations-to-improve-rag-11adca9b19d1/
author: Iulia Brezeanu
published: 2024-01-10
source_type: blog
relevance: 5
project_link: 直接對應 roadmap P2 查詢側召回改善（HyDE / 子問題分解 / multi-step / router 選法），是 rag.py:_vector_search 注入點的方法菜單。
fetch_failed: false
---

# Advanced Query Transformations to Improve RAG

## Overview
Query transformations enhance Retrieval-Augmented Generation (RAG) systems. RAG addresses
LLM hallucinations by incorporating external knowledge sources, but retrieval accuracy is
critical. The core challenge: initial user queries may not align well with indexed documents,
requiring strategic modifications before retrieval.

## Problem Context
Limitations demonstrated using two test queries against Wikipedia data about Nicolas Cage and
Leonardo DiCaprio:

1. *"Who directed the pilot that marked the acting debut of Nicolas Cage?"* — The retriever
   cannot locate relevant content because the pilot's name isn't mentioned in the query.
2. *"Compare the education received by Nicolas Cage and Leonardo DiCaprio."* — Retrieved chunks
   focus only on DiCaprio, missing Cage's educational background.

## Query Transformation Techniques

### HyDE (Hypothetical Document Embeddings)
Generates a hypothetical answer to the query using an LLM, then embeds both the query and the
hallucinated answer to find similar documents. Results showed partial improvement — for Query 1,
the model identified "The Best of Times" but gave an incorrect director name. For Query 2, it
produced accurate educational comparisons.

### Sub Questions Decomposition
Breaks complex queries into simpler sub-questions targeting different document sections. Effective
for comparative questions but less useful for queries requiring iterative context building.
Query 2 benefited significantly from this approach.

### Multi-Step Query Transformation
Based on the self-ask methodology — prompts the model to generate follow-up questions before
answering the original query. It resolved Query 1 (correctly identifying Don Mischer as director)
by first identifying the pilot name, then asking specifically about its director. Works best for
questions requiring "exploring context iteratively."

## RouterQueryEngine Solution
Rather than applying all transformations uniformly, a router selects the appropriate method per
query:

- **Simple queries** bypass transformation entirely
- **Comparative questions** trigger sub-question decomposition
- **Multi-faceted queries** activate multi-step transformation

The router chose "simple_tool" for direct factual questions, "sub_question_tool" for comparisons,
and "multi_step_tool" for linked information chains.

## Technical Implementation
Python code using LlamaIndex libraries — VectorStoreIndex for document retrieval, ServiceContext
configuration, and query engine setup with various transformation strategies.

## Conclusion
Query transformations are a targeted enhancement to RAG systems, improving retrieval accuracy by
bridging the gap between user input phrasing and source document language.
