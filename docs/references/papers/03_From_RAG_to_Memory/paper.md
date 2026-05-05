# From RAG to Memory: Non-Parametric Continual Learning for Large Language Models

> arXiv: https://arxiv.org/html/2502.14802v1

## Abstract

This research addresses limitations in how retrieval-augmented generation (RAG) systems approximate human long-term memory. The authors introduce HippoRAG 2, a framework that improves upon standard RAG approaches by combining Personalized PageRank algorithms with deeper passage integration and more effective LLM utilization. The system achieves superior performance across three memory dimensions: factual recall, sense-making, and associative reasoning. HippoRAG 2 demonstrates "7% improvement in associative memory tasks" while maintaining strong performance on simpler factual queries and complex discourse understanding tasks.

## Introduction

Contemporary language models struggle with continual learning—the ability to acquire, organize, and leverage evolving knowledge similar to human intelligence. While RAG has emerged as the dominant approach for non-parametric knowledge integration, its reliance on vector similarity alone cannot capture the "dynamic and interconnected nature of human long-term memory." The paper identifies a critical gap: existing structure-augmented RAG methods excel at either sense-making or associativity but underperform on basic factual retrieval.

The proposed HippoRAG 2 framework addresses this through three key enhancements: dense-sparse integration combining conceptual and contextual information, deeper contextualization leveraging queries more effectively, and recognition memory filtering to reduce noise. Experiments across seven datasets demonstrate comprehensive improvements, with particularly strong gains on multi-hop reasoning tasks.

## Related Work

### Continual Learning for LLMs

The paper surveys three primary approaches to continual learning: continual fine-tuning (periodic retraining with catastrophic forgetting risks), model editing (direct parameter modification with localized effects), and RAG (scalable non-parametric adaptation). RAG emerges as the most practical production solution, though it has limitations in capturing complex reasoning patterns and associative knowledge structures.

### Non-Parametric Continual Learning for LLMs

Recent embedding models like NV-Embed-v2 have significantly advanced RAG quality. The field diverges into two directions:
- **Sense-making approaches**: RAPTOR, GraphRAG, LightRAG（使用摘要與圖結構）
- **Associativity approaches**: HippoRAG（利用圖形多跳推理）

關鍵區別：HippoRAG 2 使用 KG 輔助檢索過程，而非擴展檢索語料庫，減少雜訊。

## Method: HippoRAG 2

### Overview

HippoRAG 2 維持神經生物學啟發架構，引入三項改良。系統分兩階段運作：
1. **離線索引**：提取知識圖三元組、偵測同義詞、整合段落
2. **線上檢索**：將查詢連結至相關內容、過濾無關三元組、執行圖搜尋、排名結果

### Dense-Sparse Integration（密疏整合）

從神經科學神經編碼理論汲取靈感：
- **稀疏表示（Sparse）**：短語節點，有效編碼概念
- **密集表示（Dense）**：段落節點，捕捉上下文語境

段落節點透過「contains」邊連接到其所包含的短語，在檢索時實現更豐富的語意導航。

### Deeper Contextualization（深度上下文化）

三種連結策略比較：
- NER-to-node：原始方法，僅提取命名實體
- Query-to-node：全查詢匹配（粒度不匹配，效果差）
- **Query-to-triple**（最佳）：將完整查詢與三元組關係匹配，平均提升 **12.5%**

### Recognition Memory（識別記憶）

靈感來自人類記憶區分「回憶」與「識別」：
1. 透過嵌入相似性取得候選三元組
2. LLM 過濾去除不相關關聯
3. 提升下游圖搜尋品質

### Online Retrieval

完整流程：
1. 從過濾後的三元組識別種子節點
2. 設定 PageRank 的重置機率（weight factor 0.05）
3. 執行 Personalized PageRank 遍歷
4. 依重要性分數排名段落
5. 若無三元組剩餘則降級至密集檢索（graceful degradation）

## Experimental Setup

### Datasets（七個資料集）

| 類別 | 資料集 | 查詢數 |
|------|--------|--------|
| Simple QA | NaturalQuestions, PopQA | 各 1,000 |
| Multi-hop QA | MuSiQue, 2WikiMultihopQA, HotpotQA, LV-Eval | 1,000 / 1,000 / 1,000 / 124 |
| Discourse Understanding | NarrativeQA | 293 |

### Metrics

- 檢索品質：Passage Recall@5
- QA 效能：F1 分數

### Implementation Details

- LLM：Llama-3.3-70B-Instruct（三元組提取與過濾）
- 嵌入：NV-Embed-v2
- 過濾 prompt 用 DSPy MIPROv2 優化

## Results

### QA Performance

| 對比 | 提升 |
|------|------|
| vs NV-Embed-v2（2Wiki） | +9.5% F1 |
| vs NV-Embed-v2（LV-Eval） | +3.1% F1 |
| 多跳任務整體 | +7% |

### Retrieval Performance

| 對比 | MuSiQue Recall@5 | 2Wiki Recall@5 |
|------|-----------------|----------------|
| vs NV-Embed-v2 | +5.0% | +13.9% |

## Ablation Studies

| 移除項目 | 影響 |
|----------|------|
| Query-to-triple → NER-to-node | -12.5% 平均 |
| Recognition Memory 過濾 | 小幅但明顯下降 |
| Passage Nodes | 多跳檢索大幅下降 |

## Error Analysis

100 個失敗案例分析：
- 識別記憶過濾誤刪相關三元組：26%
- PageRank 導航限制：50%
- 圖構建問題：2%
- 零三元組強制降級：18%

## Cost & Efficiency

- 處理 11,656 段落：每段落約 1.1 秒（Llama-3.3-70B）
- GPT-4o-mini batch API：低於 $22 USD
- Token 用量顯著低於 LightRAG 和 GraphRAG

## Conclusion

HippoRAG 2 透過結合圖形推理、段落級上下文整合與 LLM 過濾，實現跨事實、語意理解、聯想推理任務的全面改善。未來方向包含利用進階圖技術強化延伸對話中的情節記憶（episodic memory）。

## Key Contributions

1. **Dense-Sparse Integration**：稀疏短語表示 + 密集段落上下文
2. **Query-to-Triple Linking**：+12.5% 透過全查詢對三元組匹配
3. **Recognition Memory**：LLM 兩階段過濾降低雜訊
4. **全面評估框架**：首次系統比較三類記憶任務
5. **實證改善**：多跳 +7%，維持事實召回品質
