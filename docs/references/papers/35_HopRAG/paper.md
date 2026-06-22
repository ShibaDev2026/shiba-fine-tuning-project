# HopRAG: Multi-Hop Reasoning for Logic-Aware Retrieval-Augmented Generation

> arXiv: https://arxiv.org/abs/2502.12442 ｜ html: https://arxiv.org/html/2502.12442
> 2025

## 關鍵詞
pseudo-query edges, logic-aware retrieval, retrieve-reason-prune, graph traversal, helpfulness metric

## 對應 Layer / Roadmap 階段
- **Roadmap P2（Agentic 召回）+ P3** — HopRAG 用 pseudo-query 邊把 passage 間的「邏輯/前後置」關係顯式建模，retrieve→reason→prune 三段——對應本專案把指令模式的邏輯依賴建模 + Verifier 式 prune。

## 核心結論（帶實證數字）
1. **邏輯感知圖檢索勝 rerank 基線**（MuSiQue/2Wiki/HotpotQA）：answer +**36.25%** vs rerank、retrieval F1 +**20.97%** vs 傳統 IR。
2. **效率**：top-12 passage 達競品 top-20 的效果（省 context，呼應 RankRAG N→k [[paper-17]]）。
3. 勝 RAPTOR ~9.94% avg F1、SiReRAG ~1.11%（GPT-4o）。

## 方法機制拆解
- **建索引**：為每 passage 生成 pseudo-query——「out-coming questions」（它引發的問題）+「in-coming questions」（它回答的問題），當連接相關 passage 的橋。
- **retrieve**：相似度初篩候選。
- **reason**：LLM 在圖上推理哪些鄰居對回答有用。
- **prune**：「Helpfulness」指標（文字相似 × 邏輯重要性）選最終 context。

## 速查（綁本專案具體設計決策）
| HopRAG 機制 | 本專案落地 |
|---|---|
| **pseudo-query 邊（邏輯關係）** | 指令模式間用「這個模式回答什麼/引發什麼」建邏輯邊（比 GoS 的 I/O schema [[paper-27]] 更語意），補捉「前置條件/後續步驟」。 |
| **retrieve-reason-prune** | 召回後本地模型推理選用 + Helpfulness prune——對應 CRAG decompose-recompose [[paper-13]] + Verifier。 |
| **top-12≈top-20（省 context）** | 邏輯剪枝降 context 量。 |

## 侷限 / 與本專案差異
1. **只測多跳 QA**，跨域泛化不確定；passage 圖未呈 power-law（small-world 假設未完全成立）。
2. pseudo-query 生成成本（每 passage 多次 LLM 呼叫）——本專案 Library 建索引成本需評估。
3. domain：多文件 QA；本專案指令模式的 pseudo-query（「這指令解什麼問題」）需重設計，但天然契合 Pattern 的 description（AWM d [[paper-05]]）。
4. ⚠ 受 [[paper-34]] 約束：多數簡單指令任務可能不需圖化。
