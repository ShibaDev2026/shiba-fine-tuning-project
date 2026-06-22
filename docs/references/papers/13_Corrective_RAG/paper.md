# CRAG: Corrective Retrieval Augmented Generation

> arXiv: https://arxiv.org/abs/2401.15884 ｜ html: https://arxiv.org/html/2401.15884
> 作者: Shi-Qi Yan, Jia-Chen Gu, Yun Zhu, Zhen-Hua Ling｜ 2024

## 關鍵詞
retrieval evaluator, confidence triage, decompose-then-recompose, knowledge refinement, web search fallback, corrective action

## 對應 Layer / Roadmap 階段
- **Roadmap P3（Verifier）+ P2（Agentic 召回）** — CRAG 在召回後加一個「檢索品質評估器」分三檔觸發矯正/回退,正是本專案 Verifier 在**檢索側**的把關（召回的 pattern 不可靠時怎麼辦）。

## 核心結論（帶實證數字）
1. **輕量 T5-large 檢索評估器分三檔**：Correct（至少一篇高於上閾）→ 知識精煉；Incorrect（全低於下閾）→ web search 取代；Ambiguous（中間）→ 內外知識合併。評估器 PopQA **84.3% 準確**（遠勝 ChatGPT 變體 58–64.7%）。
2. **CRAG vs 標準 RAG**（LLaMA2-7b）：PubHealth 59.5% vs 48.9%（**+10.6**）、Arc-Challenge 53.7% vs 43.4%（**+10.3**）、PopQA 54.9% vs 50.5%。
3. **Self-CRAG vs Self-RAG**：PopQA 61.8% vs 54.9%（+6.9）、Biography FactScore 86.2 vs 81.2（+5.0）——可疊加在 Self-RAG（[[paper-11]]）之上。

## 方法機制拆解
- **三檔信心觸發**：依檢索評估器分數對召回結果分流到不同矯正動作。
- **Decompose-then-recompose 知識精煉**：把文件切成 strip（1–2 句的獨立資訊單元）→ 評估器逐 strip 重評 → 濾掉不相關 → 按序串接重組為精煉知識。
- **Incorrect → web search**：召回全不可靠時改用外部搜尋取代。

## 速查（綁本專案具體設計決策）
| CRAG 機制 | 本專案落地 |
|---|---|
| **檢索評估器分三檔（Correct/Ambiguous/Incorrect）** | Verifier 的檢索側形式：召回的 Pattern 高信心→直接 in-context 執行;模糊→本地+Claude 合議;低信心→**優雅回退 Claude**（直接對應 13% 採納天花板的回退設計）。 |
| **decompose-then-recompose** | 召回的長 pattern/exchange 切 strip 重評,濾掉 spurious 片段（呼應 DICE 的 TK 過濾 [[paper-07]]、AWM 的參數化 [[paper-05]]）。 |
| **Incorrect→web/外部** | 本專案的「外部」=回退 Claude;CRAG 證實「知道何時不信任召回」比「硬用」好。 |
| **可疊加在 Self-RAG 上（Self-CRAG）** | 本專案 Verifier 可與查詢側 gate（is_short_query 等）疊加,多層防護。 |

## 侷限 / 與本專案差異
1. **作者自承「fine-tune 外部評估器不可避免」**：本專案傾向用本地裁判 prompt-based 評估（零訓練）替代 T5 評估器,需驗證準確率能否接近 84.3%。
2. domain：開放域 QA;本專案評估對象是「指令模式對當前任務的適用性」,評估 prompt 需重設計。
3. web search fallback 在本專案對應「回退 Claude」,語義相同但成本結構不同。
