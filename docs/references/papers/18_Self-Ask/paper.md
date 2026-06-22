# Self-Ask: Measuring and Narrowing the Compositionality Gap in Language Models

> arXiv: https://arxiv.org/abs/2210.03350 ｜ ar5iv: https://ar5iv.labs.arxiv.org/html/2210.03350
> 作者: Ofir Press, Muru Zhang, Sewon Min, Ludwig Schmidt, Noah A. Smith, Mike Lewis｜ 2022

## 關鍵詞
self-ask, follow-up questions, compositionality gap, prompt-only decomposition, search engine integration

## 對應 Layer / Roadmap 階段
- **Roadmap P2（Agentic 召回）** — 最輕量的 query 分解+檢索交錯範式,**prompt-only 零微調**,可直接在本地模型上跑,補多步任務的召回涵蓋率。

## 核心結論（帶實證數字）
1. **Compositionality gap**：「子問題都答對、但合成題答錯」的比例,GPT-3 family **恆約 40%** 不隨規模縮小（GPT-4 降到 23.0%）——大模型沒自動學會組合推理。
2. **Self-ask 顯著勝 CoT/direct**：Compositional Celebrities（davinci-002）direct 45.4% → self-ask **79.6%**;Bamboogle direct 17.6% → CoT 46.4% → self-ask 57.6% → **+search 60.0%**;2WikiMultiHopQA self-ask+search 40.1% vs direct 25.4%。
3. **+search 一致再加分**:結構化 follow-up 格式可無縫接搜尋引擎,且「不需微調或改架構」。

## 速查（綁本專案具體設計決策）
| Self-Ask 機制 | 本專案落地 |
|---|---|
| **prompt-only 分解,零微調** | 本地模型把複雜指令任務拆 follow-up 子任務,逐個召回 Pattern——零訓練符合主線,P2 可立即試。 |
| **結構化 follow-up 接檢索** | 每個子任務當 query 召回 Library,呼應 IRCoT（[[paper-20]]）但更輕。 |
| **compositionality gap 恆定** | 警示:本地模型即使會單一指令,組合多步任務仍可能斷裂 → Agentic 分解召回有結構性價值,非僅排序問題。 |

## 侷限 / 與本專案差異
1. 僅測英文 2-hop;本專案中文多步指令需重設計 prompt scaffold。
2. 未測 > 175B 模型;本地模型更小,分解品質需實測。
3. domain：知識 QA;本專案是指令執行,「子問題」對應「子任務/子指令」。
