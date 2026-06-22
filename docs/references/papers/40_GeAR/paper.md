# GeAR: Graph-enhanced Agent for Retrieval-augmented Generation

> arXiv: https://arxiv.org/abs/2412.18431 ｜ ACL 2025 Findings
> 作者: Zhili Shen, Chenxin Diao, Pavlos Vougiouklis, Pascual Merita, Shriram Piramanayagam, Damien Graux, Dandan Tu, Zeren Jiang, Ruofei Lai, Yang Ren, Jeff Z. Pan｜ 2024
> （/html 與 ar5iv 渲染失敗，內容取自 arxiv /abs 摘要級）

## 關鍵詞
graph expansion, retriever-agnostic augmentation, agent gist memory, multi-step retrieval, low-risk increment

## 對應 Layer / Roadmap 階段
- **Roadmap P2（Agentic 召回）** — GeAR 的「graph expansion 掛在**任何**既有 retriever（BM25/dense）上」是**低風險增量**：本專案不必換掉 bge-m3，只在其上加圖擴展 + agent gist memory 補多跳。

## 核心結論（帶實證數字）
1. **MuSiQue 提升 >10%（SOTA）**，且「比既有多步檢索系統用更少 token、更少迭代」。
2. 兩創新：(i) 高效 graph expansion 增強任何 base retriever；(ii) agent 框架把圖檢索納入多步流程。
3. 解「sparse/dense retriever 本質難處理 multi-hop」。

## 方法機制拆解
- **graph expansion**：在 base retriever（BM25/bge-m3 等）召回結果上做圖擴展，補相鄰相關內容。
- **agent + gist memory**：多步檢索框架，gist memory 保留摘要狀態跨步。

## 速查（綁本專案具體設計決策）
| GeAR 機制 | 本專案落地 |
|---|---|
| **掛在既有 retriever 上（retriever-agnostic）** | **最低風險的圖化路徑**：保留 bge-m3，只加 graph expansion——不需重建 Library、不換召回器。 |
| **gist memory 跨步** | 多階段任務時保留摘要狀態（呼應 MemGPT external context [[paper-32]]）。 |
| **更少 token/迭代** | 比一般多步檢索省成本，貼本專案 context 預算。 |

## 侷限 / 與本專案差異
1. 摘要級分析（渲染失敗），方法細節/完整數字須回核 PDF。
2. 仍針對多跳 QA；本專案多數指令任務是否需多跳待量（[[paper-34]] 約束）。
3. graph expansion 的「相鄰」定義在文件 corpus 是語意/實體鄰接；指令模式需定義鄰接（前後置/同任務族）。
