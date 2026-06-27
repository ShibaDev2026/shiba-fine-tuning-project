# RL-QR: Annotation-Free Reinforcement Learning Query Rewriting via Verifiable Search Reward

- **arXiv URL**: https://arxiv.org/abs/2507.23242
- **發布日期**: 2025-07-31 (submitted); revised 2025-12-12
- **來源類型**: paper
- **relevance**: 5
- **作者群**: Sungguk Cha, DongWook Kim, Taeseung Hahn, Mintae Kim, Youngsub Han, Byoung-Ki Jeon
- **與主專案關聯**: annotation-free RL query rewriting，用 verifiable search reward 免人工標註——對「累積驗證模式」+ 查詢側召回改善有方法借鑑，且無標註門檻契合本地小資料現實。

---

## Abstract

Optimizing queries for Retrieval-Augmented Generation (RAG) systems poses a significant challenge, particularly across diverse modal indices. We introduce RL-QR, a novel annotation-free reinforcement learning framework for query rewriting that eliminates the need for costly human-annotated data. By leveraging verifiable search rewards derived from index-aligned synthetic queries, RL-QR overcomes human-annotation dependencies, extending its applicability to various modalities and index domains. Experimental results demonstrate the framework's robustness, achieving substantial retrieval performance gains of up to 3.9× on lexical retrievers and 3.5× on semantic retrievers on the MTEB VIDORE V2 benchmark for unstructured visual documents, along with consistent 5% to 10% improvements on MS MARCO v2.1 and internal industrial datasets.

---

## Method highlights (from abstract)

- Annotation-free RL framework for query rewriting — removes dependence on costly human-annotated data.
- Reward signal = verifiable search rewards derived from index-aligned synthetic queries.
- Generalizes across modalities and index domains (incl. unstructured visual documents).
- Reported gains: up to 3.9× (lexical) and 3.5× (semantic) on MTEB VIDORE V2; 5–10% on MS MARCO v2.1 and internal industrial datasets.
