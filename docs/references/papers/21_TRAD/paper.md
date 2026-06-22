# TRAD: Enhancing LLM Agents with Step-Wise Thought Retrieval and Aligned Decision

> arXiv: https://arxiv.org/abs/2403.06221 ｜ html: https://arxiv.org/html/2403.06221 ｜ SIGIR 2024
> 作者: Ruiwen Zhou, Yingxuan Yang, Muning Wen, Ying Wen, Wenhao Wang, Chunling Jin, et al.｜ 2024

## 關鍵詞
step-wise thought retrieval, aligned decision, temporal neighbor expansion, plausible-example problem, trajectory vs step retrieval

## 對應 Layer / Roadmap 階段
- **Roadmap P2（Agentic 召回 + in-context 執行）** — 解本專案 macro-exchange 死路（memory: 整段軌跡召回淨負）的對症法：**step-level 召回 + 鄰步補齊**,在不爆 context 下提升召回有用性。

## 核心結論（帶實證數字）
1. **Thought Retrieval**：不用任務 metadata 召回整條軌跡,而是對當前狀態生成「思考」、用語意相似度召回**匹配的 demonstration 單步**——避開「任務描述像但解法不同」的 plausible examples（= spurious,呼應 DICE [[paper-07]]）。
2. **Aligned Decision**：召回步補上時序鄰步（前 B 步、後 F 步）+ 相對位置標記,容忍思考生成不完美。
3. **數字**：ALFWorld **96.77%** vs Synapse+ReAct 93.78%;Mind2Web step SR 28.0% vs 26.6%、cross-domain 增益最大;**真實部署（保險公司）整體成功率 65.0%→92.5%**。

## 速查（綁本專案具體設計決策）
| TRAD 機制 | 本專案落地 |
|---|---|
| **step-level 召回 > trajectory-level** | **直接對症 macro-exchange 死路**（memory）：不召回整段對話,召回「單一指令步」的 pattern。 |
| **避開 plausible examples** | 用思考相似度而非任務描述相似度,濾掉「看起來像但其實不同」的 spurious pattern（與 DICE TK 軸同向）。 |
| **時序鄰步補齊** | 召回的指令步補上前後步,給本地模型完整脈絡而不必塞整段軌跡——平衡 context 預算。 |
| **cross-domain 增益最大** | 飛輪價值最高在新任務族（呼應 AWM online [[paper-05]]）。 |

## 侷限 / 與本專案差異
1. **依賴思考品質與 backbone 能力**：本地模型生成思考品質需實測。
2. **時序擴展的 trade-off**：補太多鄰步引入雜訊——B/F 窗需調。
3. domain：ALFWorld/Mind2Web；本專案 CLI agent 的「步」= 單指令/工具呼叫,需定義步邊界（連 D4 exchange 切割問題）。
