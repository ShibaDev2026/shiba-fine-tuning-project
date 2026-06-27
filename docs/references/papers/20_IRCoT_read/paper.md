# IRCoT: Interleaving Retrieval with Chain-of-Thought Reasoning for Knowledge-Intensive Multi-Step Questions

> arXiv: https://arxiv.org/abs/2212.10509 ｜ ar5iv: https://ar5iv.labs.arxiv.org/html/2212.10509
> 作者: Harsh Trivedi, Niranjan Balasubramanian, Tushar Khot, Ashish Sabharwal｜ 2022（ACL 2023）

## 關鍵詞
interleaved retrieval, chain-of-thought, multi-hop QA, reasoning-guided retrieval, retrieval recall

## 對應 Layer / Roadmap 階段
- **Roadmap P2（Agentic 召回）** — 直接對症本專案「真瓶頸是召回涵蓋率非排序」：用推理逐步驅動檢索,補一次性查詢漏掉的相關內容。

## 核心結論（帶實證數字）
1. **推理↔檢索交錯**：每步用上一句 CoT 當 query 再檢索,讓檢索引導推理、推理引導檢索。
2. **檢索 recall 大幅提升**（vs 一次性問題檢索）：2WikiMultihopQA **+14.3~+22.6**、IIRC +10.2~+21.2、HotpotQA +7.9~+11.3、MuSiQue +3.5~+12.5。
3. **QA F1 提升**（Flan-T5-XXL）：2WikiMultihopQA +15.3、HotpotQA +9.4。
4. **事實錯誤減半**：HotpotQA −50%、2Wiki −40%。

## 速查（綁本專案具體設計決策）
| IRCoT 機制 | 本專案落地 |
|---|---|
| **推理驅動逐步檢索補 recall** | 多階段任務時,本地模型每完成一步推理就重召回 Library,補一次召回漏掉的 pattern——直擊「涵蓋率」瓶頸。 |
| **檢索 recall 比 QA 增益更大** | 印證本專案診斷：瓶頸在召回涵蓋率;IRCoT 證「多步召回」是補涵蓋率的有效手段（對照 ExpRAG dynamic [[paper-06]]）。 |

## 侷限 / 與本專案差異
1. **需 LLM 有 CoT 能力 + 長 input**：本地小模型 CoT 品質與 context 長度受限,須實測。
2. **每步一次 LLM 呼叫,成本高**：與 13% 採納天花板的 EV 權衡。
3. **與 Adaptive-RAG（[[paper-16]]）互補**：不是每個 query 都該多步,複雜度分類器先判該不該交錯。
