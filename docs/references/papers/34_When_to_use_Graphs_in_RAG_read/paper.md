# When to use Graphs in RAG: A Comprehensive Analysis for Graph Retrieval-Augmented Generation

> arXiv: https://arxiv.org/abs/2506.05690 ｜ html: https://arxiv.org/html/2506.05690
> 2025

## 關鍵詞
GraphRAG vs vanilla RAG, decision boundary, token overhead, complex reasoning vs fact retrieval, base-assumption brake

## 對應 Layer / Roadmap 階段
- **Roadmap P1（圖化前的決策閘）** — 本篇是「煞車片」：在投入建圖前先問「值不值得」。直接服務本專案 **base-assumption-first 紀律**（gate 不過不建），對 27/35 等 Graph RAG 方案是必要的前置判斷。

## 核心結論（帶實證數字）
1. **GraphRAG 贏複雜推理、輸簡單事實檢索**：
   - 簡單事實（Level 1）：vanilla RAG+rerank **60.92%** ≈ HippoRAG2 60.14%（**RAG 略勝**）。
   - 複雜推理（Level 2）：HippoRAG2 **53.38%** vs RAG 42.93%（**GraphRAG +10.45**）。
   - 醫療事實檢索：差距縮小、GraphRAG 微勝（66.28 vs 64.73）。
2. **40× token 膨脹**：MS-GraphRAG global 達 ~4×10⁴ token vs vanilla ~879 token → 對簡單查詢引入雜訊反降效能。

## 方法機制拆解
- **GraphRAG 有用**：需橋接多概念複雜關係、證據跨遠距文段、多跳推理。
- **GraphRAG 有害**：Level 1 證據通常在單一 passage、圖引入冗餘、token 開銷過大。

## 速查（綁本專案具體設計決策）
| 本篇結論 | 本專案落地 |
|---|---|
| **簡單事實檢索 vanilla RAG ≈ 或勝 GraphRAG** | **多數指令任務是「找對的模式」（近 Level 1）→ 先別建圖**，bge-m3 召回足夠；Graph-of-Skills（[[paper-27]]）的依賴圖只在「模式間有複雜前後置」才划算。 |
| **40× token 膨脹** | 圖化的隱性成本警示，與本專案 context 預算 + 13% 天花板衝突。 |
| **複雜推理才用圖** | 圖化的 EV gate：先量「指令任務有多少需要跨多模式橋接」，少→不建圖。呼應 P1 量重複頻率。 |

## 侷限 / 與本專案差異
1. 評測在通用/醫療 QA；本專案指令任務的「複雜度分布」需自量（多數可能是 Level 1 → 不需圖）。
2. 是分析性論文非新方法；價值在決策框架。
3. 與 27/35 配套讀：先用本篇判該不該圖化，再看 GoS/HopRAG 怎麼建。
