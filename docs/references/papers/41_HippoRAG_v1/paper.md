# HippoRAG: Neurobiologically Inspired Long-Term Memory for Large Language Models (v1)

> arXiv: https://arxiv.org/abs/2405.14831 ｜ ar5iv: https://ar5iv.labs.arxiv.org/html/2405.14831 ｜ NeurIPS 2024
> 作者: Bernal Jiménez Gutiérrez, Yiheng Shu, Yu Gu, Michihiro Yasunaga, Yu Su｜ 2024
> ⚠ v2「From RAG to Memory」已在庫（[[paper-03]]）；本檔留 v1 的 PPR 原始機制 + cost/latency 量化。

## 關鍵詞
Personalized PageRank, hippocampal indexing, OpenIE knowledge graph, single-step multi-hop, node specificity

## 對應 Layer / Roadmap 階段
- **Roadmap P2 + Layer 1** — HippoRAG v1 用 PPR over LLM-建知識圖做**單步多跳**召回，比 IRCoT 迭代式便宜 10–30×。本專案若走圖召回，PPR 是 GoS（[[paper-27]]）/Agent-as-a-Graph（[[paper-37]]）的共同底層機制。

## 核心結論（帶實證數字）
1. **單步多跳召回勝 ColBERTv2**：2WikiMultiHopQA +11% R@2 / +20% R@5；MuSiQue +3%；HotpotQA 持平。
2. **效率**：單步 HippoRAG「達到或勝過 IRCoT 迭代式，但便宜 10–30×、快 6–13×」。
3. **與 IRCoT 結合**再加分：MuSiQue +4% R@5、2Wiki +18% R@5。

## 方法機制拆解
- **離線索引**：LLM 用 OpenIE 抽名詞三元組 → schemaless 知識圖；encoder 加同義邊。
- **線上召回**：抽 query 命名實體 → 語意連到圖節點 → 以 query 概念為種子跑 **PPR** 單步探多跳路徑。
- **Node Specificity**：依 passage 頻率調節 entity 重要性（局部可算，類 IDF）。

## 速查（綁本專案具體設計決策）
| HippoRAG v1 機制 | 本專案落地 |
|---|---|
| **PPR 單步多跳（比迭代便宜 10–30×）** | 若 Library 建圖，PPR 一次擴展取代 IRCoT 多輪 LLM 呼叫——省本地推論成本（GoS 的 reverse-aware PPR [[paper-27]] 是其進化）。 |
| **Node Specificity（類 IDF）** | 高頻泛用指令 down-weight、特定模式 up-weight——對應稀有但精準的模式召回。 |
| **OpenIE schemaless 圖** | 免預定義 schema 建圖；但本專案指令模式的「三元組」需定義。 |

## 侷限 / 與本專案差異
1. **★NER 依賴**：~48% 錯誤來自命名實體抽取漏關鍵資訊——本專案中文指令的「實體」（指令名/檔名/flag）抽取品質是瓶頸。
2. **concept-context tradeoff**：entity-centric 忽略脈絡訊號。
3. **OpenIE 品質**：漏時序、長實體。
4. v2（[[paper-03]]）已用 query-to-triple linking + recognition memory 改善此些；v1 主要價值在 PPR 機制與成本量化的引用。
