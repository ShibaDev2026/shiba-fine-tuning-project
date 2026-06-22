# A Benchmark for Procedural Memory Retrieval in Language Agents

> arXiv: https://arxiv.org/abs/2511.21730
> 作者: Ishant Kohar, Aswanth Krishnan｜ 2025-11
> ⚠ 後截止日論文（2025-11），本分析以 arxiv 全文內容為準。

## 關鍵詞
procedural memory, generalization cliff, mean-pooling bag-of-words, state-aware vs action-only embeddings, coverage-balanced benchmark

## 對應 Layer / Roadmap 階段
- **Layer 1 RAG + Roadmap P1/P2（根本診斷）** — **本篇從機制層解釋本專案「純 cosine 召回指令模式為何失效」**：embedding mean pooling 把程序當無序詞袋、丟失時序結構,換物件就崩——這是比「golden set cosine-bound」更底層的原因。

## 核心結論（帶實證數字）
1. **Generalization cliff**：sentence-transformer 因 mean pooling「把軌跡當無序 token 集合」,丟時序結構;物件一換（apple→salt shaker）相似程序的 embedding 崩成幾乎相同,認不出「不同物件上的等價動作」。「在熟悉情境強的方法,在新情境顯著退化」。
2. **數字（探索性 78 軌跡）**：Combined Embeddings seen MAP 0.844 → unseen 0.592（**−29.9%**）;Action-Only −35.5%;Summary −11.0%（摘要式最抗跌）。
3. **State-aware > Action-only**（336 軌跡）：MAP 0.7945 vs 0.7231。
4. **★語料規模效應**：軌跡 4.3×（78→336）→ MAP **+27.7%**;加豐富 state context 只 +9.9% → **涵蓋率 >> 表徵精煉**（強力呼應 ExpRAG 空 index 崩盤 [[paper-06]] + AWM cross-domain [[paper-05]]）。

## 速查（綁本專案具體設計決策）
| 本篇發現 | 本專案落地 |
|---|---|
| **mean pooling 把程序當詞袋、丟時序** | **本專案指令模式召回的根本警示**：純 bge-m3 dense（mean pooling）對「步驟順序」不敏感 → 換檔名/路徑就可能召回失準。對症：①參數化（AWM）②sparse head 補 term（[[paper-12]][[paper-19]]）③state-aware 表徵。 |
| **涵蓋率 +27.7% >> 表徵精煉 +9.9%** | **直接背書 P1 EV gate**：與其精修 embedding,不如先把 Library 養大（更多驗證模式）。本專案「先量重複頻率」正是在賭涵蓋率。 |
| **summary embedding 最抗跌（−11%）** | 召回 Pattern 用「摘要式描述」（AWM 的 NL description d）比 raw 軌跡更耐物件變動——支持蒸餾而非存 raw。 |
| **state-aware > action-only** | Pattern 不只存動作序列,要帶狀態脈絡（任務前提/環境）。 |

## 侷限 / 與本專案差異
1. **LLM judge 一致性中等**（Cohen's κ=0.178）→ 結果是「實用下界」;本專案本地裁判補標也須注意一致性（連 DREAM [[paper-08]]）。
2. 限 ALFWorld 家務任務;軟體 workflow（本專案場景）「仍需驗證」——作者明列。
3. 只評推論期召回,無 fine-tune/架構調整。
4. domain：embodied;但「程序召回的詞袋陷阱」對 CLI 指令序列高度可遷移。
