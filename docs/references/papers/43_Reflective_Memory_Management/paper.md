# In Prospect and Retrospect: Reflective Memory Management for Long-term Personalized Dialogue Agents (RMM)

> arXiv: https://arxiv.org/abs/2503.08026 ｜ ACL 2025
> 2025-03（/html 暫無，內容取自 arxiv /abs 摘要級）

## 關鍵詞
prospective reflection, retrospective reflection, multi-granularity summarization, online RL retrieval refinement, personalized memory bank

## 對應 Layer / Roadmap 階段
- **Roadmap P1/P2（記憶切割 + 召回精煉）** — RMM 的「多粒度動態摘要」對症本專案 **exchange 邊界 / macro-exchange 切割痛點**（memory: 整段召回淨負）；「用下游使用反饋精煉召回」對應 manual-accept 飛輪當 RL 訊號。

## 核心結論（帶實證數字）
1. **兩向反思**：
   - **Prospective（前瞻）**：跨粒度（utterance/turn/session）動態摘要存入個人化記憶庫，利於未來召回。
   - **Retrospective（回溯）**：依 LLM 引用的證據，用 online RL 迭代精煉召回。
2. **LongMemEval：>10% 準確提升** vs 無記憶管理 baseline。

## 速查（綁本專案具體設計決策）
| RMM 機制 | 本專案落地 |
|---|---|
| **多粒度動態摘要（非固定粒度）** | **對症 exchange 切割死路**（memory: macro-exchange 淨負）：別固定按 exchange 切，動態按語意粒度（指令/turn/session）摘要存 Library。 |
| **retrospective：用「被引用的證據」做 RL 精煉召回** | manual-accept 飛輪的精緻版——Shiba 實際採納/引用哪些召回模式 → online 精煉召回器（呼應 Query Rewriting RL [[paper-10]]）。 |
| **prospective 摘要存記憶庫** | 對應蒸餾寫入 Library（AWM description [[paper-05]]、Generative Agents reflection [[paper-30]]）。 |

## 侷限 / 與本專案差異
1. 摘要級分析、無逐項數字（LongMemEval 外）：採用前回核全文。
2. **需 online RL**：與「先零訓練」路線略衝突——可先用啟發式摘要 + 採納統計，RL 留後期。
3. domain：個人化對話；本專案是指令模式，「多粒度」對應指令/任務/任務族，需重定義粒度。
