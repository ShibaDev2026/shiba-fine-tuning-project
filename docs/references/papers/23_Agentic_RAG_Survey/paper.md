# Agentic Retrieval-Augmented Generation: A Survey on Agentic RAG

> arXiv: https://arxiv.org/abs/2501.09136 ｜ html: https://arxiv.org/html/2501.09136
> 作者: Aditi Singh, Abul Ehtesham, Saket Kumar, Tala Talaei Khoei｜ 2025

## 關鍵詞
agentic RAG taxonomy, single/multi-agent, hierarchical, corrective, adaptive, graph-based, reflection/planning/tool-use

## 對應 Layer / Roadmap 階段
- **Roadmap 全線（設計詞彙）** — 提供 agentic RAG 架構分類軸與設計模式詞彙,用來**定位本專案在設計空間的位置**並命名各組件。

## 核心結論（分類軸，非 benchmark）
### 六大架構分類
1. **Single-Agent（Router）**：單一 agent 管檢索/路由/整合——**本專案當前 L0 router 屬此**。
2. **Multi-Agent**：多專職 agent 並行。
3. **Hierarchical**：分層,高層調度低層檢索專家。
4. **Corrective**：分離 agent 做相關性評估/查詢精煉/回應驗證——**對應 CRAG [[paper-13]] + 本專案 Verifier**。
5. **Adaptive**：依 query 複雜度動態選策略——**對應 Adaptive-RAG [[paper-16]]**。
6. **Graph-Based**（Agent-G / GeAR）：圖結構知識。

### 四大設計模式
- **Reflection**（自我評估精煉）/ **Planning**（任務分解）/ **Tool Use**（API/DB）/ **Multi-Agent**（專職協作）。

### Open challenges（與本專案相關）
協調與湧現行為、**評估方法（超越輸出品質）**、記憶管理與長期適應、計算效率、**安全/信任/治理**、跨域泛化。

## 速查（綁本專案具體設計決策）
| Survey 概念 | 本專案落地 |
|---|---|
| **本專案 = Single-Agent Router → 目標往 Corrective+Adaptive 演進** | 路線圖定位：L0 router(Single)+ Verifier(Corrective)+ 複雜度路由(Adaptive),不需 Multi-Agent/Graph 重架構。 |
| **設計模式詞彙** | Reflection=Verifier 自評;Planning=Agentic 多步召回;Tool Use=本專案 CLI 工具——用統一詞彙描述 roadmap。 |
| **「評估超越輸出品質」challenge** | 呼應本專案 golden set cosine-bound 困局 + SoK 分層評估（[[paper-26]]）。 |

## 侷限 / 與本專案差異
1. Survey 無實證數字,僅分類與詞彙。
2. 偏 LLM 通用 agent;本專案是 CLI/code 特化,Graph-Based 等類別不適用。
3. 價值在「定位與命名」而非「方法細節」——細節看對應單篇（CRAG/Adaptive-RAG/Self-RAG）。
