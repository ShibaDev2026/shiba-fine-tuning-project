# SoK: Agentic Retrieval-Augmented Generation — Taxonomy, Architectures, Evaluation, and Research Directions

> arXiv: https://arxiv.org/abs/2603.07379
> 作者: Saroj Mishra, Suman Niroula, Umesh Yadav, Dilip Thakur, Srijan Gyawali, Shiva Gaire｜ 2026-03
> ⚠ 後截止日論文（2026-03），本分析以 arxiv 全文內容為準。

## 關鍵詞
POMDP formalization, planning topology, retrieval strategy, failure modes, verifier checklist, layered evaluation

## 對應 Layer / Roadmap 階段
- **Roadmap P3（Verifier）+ 評估框架** — 提供 agentic RAG 的**形式化 + 失效模式清單**：六大 failure mode 直接當 **Verifier 該防什麼的檢查清單**;分層評估回應本專案 golden set 困局。

## 核心結論（形式化 + 清單）
### POMDP 形式模型
把 agentic RAG 形式化為有限視界 POMDP `⟨S_env, A, Ω, O, π_θ, M, T⟩`,目標 `max E[R_task − λ·ΣC(a_t)]`（任務獎勵減動作成本）——**把「召回幾步」變成成本-效益決策**,呼應本專案 13% 天花板下的 EV 思維。

### 四正交軸
| 軸 | 類別 |
|---|---|
| Planning Topology | Single-Agent / Planner–Executor / Multi-Agent |
| Retrieval Strategy | One-Shot / Iterative / Self-Refining |
| Reasoning Paradigm | CoT / ReAct / Reflection / Tree |
| Memory Model | Dynamic Pruning / Episodic / Persistent |

### ★六大 failure mode（= Verifier 檢查清單）
1. **Retrieval Drift / Query Misalignment**（查詢偏離意圖）
2. **Hallucination Despite Retrieval**（無脈絡仍捏造）
3. **Tool Misuse & Cascading Errors**（無效呼叫連鎖）
4. **Prompt Injection in Iterative Retrieval**（語料對抗污染）
5. **Memory Poisoning**（episodic buffer 被污染）
6. **Systemic Risk Amplification**（迭代放大錯誤）
+ Verification 須防「evaluation blind spots」（誤信瑕疵輸出）。

### 分層評估
Layer 1 組件級（retriever recall/planner 一致性）→ Layer 2 軌跡級（多步推理連貫）→ Layer 3 系統級（最終正確+成本效益）;「靜態 benchmark 不足、要評決策序列非僅輸出」。

## 速查（綁本專案具體設計決策）
| SoK 概念 | 本專案落地 |
|---|---|
| **六大 failure mode** | **Verifier(P3) 的需求清單**：本專案最該防 #3 Tool Misuse（bash/git 危險指令,連 VeriGuard [[paper-14]]/capability labels [[paper-15]]）+ #4/#5（Library 被污染的指令模式,連 ingestion 雜訊去噪 [[project-exchange-embeddings-ingestion-noise]]）。 |
| **POMDP 成本-效益目標** | 形式化本專案「召回/執行 vs 回退 Claude」的 EV 決策。 |
| **分層評估** | 回應 golden set cosine-bound：組件級召回 recall + 系統級採納率分開評,別只看單一指標。 |
| **本專案定位** | Single-Agent + One-Shot→Iterative + Reflection + Episodic(Library)——四軸明確,不需 Multi-Agent/Tree 重架構。 |

## 侷限 / 與本專案差異
1. SoK 是綜整非新方法,無實證。
2. 偏通用 agentic RAG;本專案 CLI 特化,部分軸（Tree reasoning）不適用。
3. 價值在「Verifier 檢查清單 + 評估分層」的方法論,落地細節需自行設計。
