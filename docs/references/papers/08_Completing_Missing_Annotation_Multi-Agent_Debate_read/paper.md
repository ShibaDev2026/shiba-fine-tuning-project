# Completing Missing Annotation: Multi-Agent Debate for Accurate and Scalable Relevance Assessment for IR Benchmarks (DREAM / BRIDGE)

> arXiv: https://arxiv.org/abs/2602.06526 ｜ ICLR 2026
> 作者: Minjeong Ban, Jeonghwan Choi, Hyangsuk Min, Nicole Hee-Yeon Kim, Minseok Kim, Jae-Gil Lee, Hwanjun Song｜ 2026-02
> ⚠ 後截止日論文（2026-02），本分析以 arxiv 內容為準。

## 關鍵詞
hole problem, missing relevance annotation, multi-agent debate, DREAM, BRIDGE benchmark, human-in-the-loop escalation, retrieval-generation misalignment

## 對應 Layer / Roadmap 階段
- **Roadmap P1 + Layer 1 評估框架** — 直擊本專案**最痛的評估盲點**：golden set 是 cosine-bound（gt 候選抽自 bi-encoder+FTS5），有「漏標的相關項（hole problem）」→ 任何「打敗 cosine 的召回法」（reranker、bge-m3 sparse head）都無法被公平評出。DREAM 提供「**獨立補標**」的可行機制。

## 核心結論（帶實證數字）
1. **不完整 IR benchmark 的漏標會扭曲 retriever 排名**，並在 RAG 造成「retrieval-generation misalignment」——正是本專案 reranker PoC 失敗的根因（memory: grader=author 陷阱）。
2. **DREAM 多代理辯論補標：95.2% 標註準確率，僅需 3.5% 人工介入**。
3. 用 DREAM 建出 **BRIDGE** 精修 benchmark，揪出 **29,824 個漏標的相關 chunk**。
4. 既能給「有信心的標註決策」，又能給「可靠的不確定訊號」做 AI→人工 escalation。

## 方法機制拆解
- **對立初始立場 + 迭代相互批判**：多個 agent 對「某 chunk 是否相關」持相反立場，多輪互批 → 收斂共識，或標記為需人工複核。
- **減 single-annotator bias**：用系統性辯論 + human-in-the-loop，緩解「benchmark 作者兼評分者」的循環偏誤（雖未明用 grader=author 一詞，機制正對症）。

## 速查（綁本專案具體設計決策）
| DREAM 機制 | 本專案落地 |
|---|---|
| **多代理辯論補漏標、95.2%/3.5% 人工** | **修 golden set 的具體配方**：本專案本地三裁判家族（Qwen/GLM/Gemma）正好可當辯論 agent，對 `build_candidates` 漏掉的相關 exchange 做對立辯論補標 → 產出獨立於 bi-encoder 的 gt，**解除 cosine-bound**，讓 reranker/bge-m3 sparse head 能被公平評估。 |
| **AI→人工 escalation 訊號** | 只有不確定案例才需 Shiba 介入（3.5% 量級），符合「低摩擦」約束；對應 manual-accept 飛輪——Shiba 只在高不確定點當仲裁。 |
| **漏標→retriever 排名扭曲** | 印證 memory 記載「修 golden set 不划算」的反面：**不修則所有召回改善都測不出**。DREAM 把「修」的成本壓到 3.5% 人工，可能翻轉「不划算」結論——值得 P1 小實驗評估。 |

## 侷限 / 與本專案差異
1. 摘要未列明確侷限（需讀全文 PDF 補）。
2. domain：通用 IR benchmark；本專案 gt 是「指令模式↔對話 exchange」相關性，辯論 prompt 需針對性重設計。
3. 多代理辯論成本（多輪 LLM 呼叫）需評估，本專案本地裁判 JIT 載入，吞吐受限。
4. ⚠ 採用前先 base-assumption 小實驗：本地三裁判辯論對中文指令相關性的補標準確率，需先驗證能否接近論文 95.2%。
