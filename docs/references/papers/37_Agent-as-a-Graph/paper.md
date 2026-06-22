# Agent-as-a-Graph: Knowledge Graph-Based Tool and Agent Retrieval for LLM Multi-Agent Systems

> arXiv: https://arxiv.org/abs/2511.18194 ｜ html: https://arxiv.org/html/2511.18194
> 作者: Faheem Nizar, Elias Lumer, Anmol Gulati, Pradeep Honaganahalli Basavaraju, Vamse Kumar Subbiah｜ 2025-11

## 關鍵詞
KG tool/agent retrieval, bipartite ownership graph, type-specific weighted RRF, graph traversal, MCP tool selection

## 對應 Layer / Roadmap 階段
- **Roadmap P2（Agentic 召回，工具層）** — 把工具/agent 表成二部圖（ownership 邊），vector→wRRF→圖遍歷兩段召回。對應本專案「召回零散指令模式 → 沿關係聚成可執行單位」。

## 核心結論（帶實證數字）
1. **二段式 KG 召回勝向量基線**（LiveMCPBench：70 MCP server/527 工具/95 真實查詢）：Recall@5 **0.85 vs MCPZero 0.70（+14.9%）**、nDCG@5 0.48 vs 0.41（+14.6%）。
2. **type-specific 加權**：α_agent=1.5/α_tool=1.0 最佳，wRRF 優化 +2.4%；跨 8 個 embedding 模型平均 Recall@5 +19.4%。

## 方法機制拆解
- **建圖**：二部圖 `G=(A,T,E)`，邊=工具↔父 agent 的 ownership。
- **vector retrieval**：統一語料 `C=C_A ∪ C_T` 取 top-N。
- **type-specific wRRF + 遍歷**：`α_T/(k+r) 或 α_A/(k+r)` 分型計分（避免異質排序混血）→ 沿 ownership 邊把工具映回父 agent → 回傳 top-K unique agent。

## 速查（綁本專案具體設計決策）
| Agent-as-a-Graph 機制 | 本專案落地 |
|---|---|
| **type-specific wRRF（分型不混血）** | 本專案若召回混合「指令模式 + 工具 + 前置」異質節點，分型加權避免排序混血（注意 [[paper-19]]：純 RRF 不穩，此處是分型 RRF、用途不同）。 |
| **ownership 邊聚成可執行單位** | 召回指令模式時沿關係拉出完整可執行單位（呼應 GoS 前置回溯 [[paper-27]]）。 |
| **MCP 工具召回** | 若本專案接 MCP/工具集，此為工具選擇的召回範式。 |

## 侷限 / 與本專案差異
1. 未討論複雜度/可擴展性（>527 工具未測）、無 ablation 隔離圖貢獻 vs 加權。
2. domain：多 agent 系統工具選擇；本專案是單 agent + 指令模式，二部圖結構需重映射。
3. 規模小（527 工具）；本專案 Library 規模待長大後才需此類結構。
