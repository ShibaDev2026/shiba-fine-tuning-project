# Generative Agents: Interactive Simulacra of Human Behavior

> arXiv: https://arxiv.org/abs/2304.03442 ｜ ar5iv: https://ar5iv.labs.arxiv.org/html/2304.03442 ｜ UIST 2023
> 作者: Joon Sung Park, Joseph C. O'Brien, Carrie J. Cai, Meredith Ringel Morris, Percy Liang, Michael S. Bernstein｜ 2023

## 關鍵詞
memory stream, recency/importance/relevance retrieval, reflection, recursive planning, memory architecture

## 對應 Layer / Roadmap 階段
- **Roadmap P1/P2（召回排序）+ Layer 1** — 奠基作。其三因子加權召回（recency×importance×relevance）**直接補本專案目前單一 cosine 排序**的不足，importance 因子可讓「Shiba 高度採納的模式」召回權重更高。

## 核心結論（帶實證數字）
1. **記憶架構各組件都有顯著貢獻**（ablation, TrueSkill μ）：完整 **29.89** > 無 reflection 26.88 > 無 reflection/planning 25.64 > **無記憶 21.21**；完整 vs 無記憶 effect size **d=8.16**（八個標準差）。
2. **湧現行為**：資訊擴散達 32%/52%，網路密度 0.167→0.74，五 agent 自發協調聚會。

## 方法機制拆解
### 三因子加權召回
`score = α_recency·recency + α_importance·importance + α_relevance·relevance`（實作 **所有 α=1**）：
- **recency**：指數衰減 factor 0.995（呼應本專案 FOREVER decay [[paper-04]]）。
- **importance**：LLM 直接評 1–10（1 平庸如刷牙、10 極重要）。
- **relevance**：query 與記憶 embedding 的 cosine。
### Reflection
重要度累積超閾值（150）觸發 → 對近期經驗抽「高階抽象想法」+ 引證據，每日約 2–3 次。
### Planning
遞迴分解：日計畫 → 小時 → 5–15 分鐘動作；遇環境變化更新。

## 速查（綁本專案具體設計決策）
| Generative Agents 機制 | 本專案落地 |
|---|---|
| **recency×importance×relevance 三因子召回** | **補本專案單一 cosine（=只有 relevance）**：加 importance（Shiba 採納次數/品質）+ recency（近期用過的模式優先）→ 召回排序更貼實際效用，繞 cosine-bound 的另一條路。 |
| **importance 由 LLM 評分** | 對應 manual-accept：Shiba 採納＝高 importance；可用本地裁判初評 + Shiba 校正。 |
| **reflection（累積觸發抽高階）** | ＝本專案 memory consolidation（已有每日 consolidation）；指令模式累積到閾值可蒸餾出更高階 meta-pattern。 |
| **recency 指數衰減 0.995** | 與既有 decay 設計一致（[[paper-04]]）。 |

## 侷限 / 與本專案差異
1. **記憶幻覺 + 召回失敗**：agent 會編造未驗證細節、也會漏召回相關記憶——對應本專案 Verifier 須擋幻覺（SoK #2 [[paper-26]]）。
2. **成本高**（25 agent×2 天＝數千美元 token）：本專案本地推論成本結構不同但仍需控。
3. **prompt/memory hacking 脆弱**：呼應本專案 Library 污染風險（ingestion 雜訊去噪、recall gate）。
4. domain：社會模擬；本專案取其**記憶架構（memory stream + 三因子召回 + reflection）**，非角色模擬。
