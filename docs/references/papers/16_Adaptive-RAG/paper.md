# Adaptive-RAG: Learning to Adapt Retrieval-Augmented LLMs through Question Complexity

> arXiv: https://arxiv.org/abs/2403.14403 ｜ html: https://arxiv.org/html/2403.14403 ｜ NAACL 2024
> 作者: Soyeong Jeong, Jinheon Baek, Sukmin Cho, Sung Ju Hwang, Jong C. Park｜ 2024

## 關鍵詞
query complexity classifier, no-retrieval/single-step/multi-step routing, automatic labeling, efficiency-accuracy tradeoff, T5-Large classifier

## 對應 Layer / Roadmap 階段
- **Roadmap P2（Agentic 召回）+ Layer 0 路由** — Adaptive-RAG 的「query 複雜度分類器 → 路由到對應策略」與本專案 **L0 router（判走本地/Claude）幾乎同構**;且其複雜度三檔 **A/B/C** 與本專案能力驗證的採納分類 **A=0/B=13/C=13**（memory [[project-capability-upper-bound-validation]]）撞名同構,值得對照。

## 核心結論（帶實證數字）
1. **複雜度分類器分三檔路由**：'A' 不檢索（LLM 直答）/ 'B' 單步檢索 / 'C' 多步迭代檢索-推理。
2. **以 ~50% 效率達到 multi-step 的準確度**（Table 1 平均）：Adaptive-RAG F1 46.94–50.91、Steps 1.03–2.17;Multi-step F1 48.85–50.87 但 Steps 2.13–4.69。
3. **SQuAD（FLAN-T5-XL）**：Adaptive F1=38.30/Time=2.02 vs Multi-step F1=35.60/Time=9.03——**單步任務硬跑多步反而更差又更慢**。

## 方法機制拆解
### 複雜度分類器（T5-Large）
- 三檔：A（直答）/ B（單步）/ C（多步）。
### 無人工標籤的自動標註（兩策略）
1. **預測結果**：最簡單的非檢索法若答對 → 標 'A'（平手時優先簡單模型）。
2. **資料集歸納偏置**：單跳資料集標 'B'、多跳標 'C'。
- 訓練：T5-Large + 6 資料集各抽 400 query（與測試集不重疊）。

## 速查（綁本專案具體設計決策）
| Adaptive-RAG 機制 | 本專案落地 |
|---|---|
| **複雜度三檔路由** | **直接升級本專案 L0 router**:不只「本地 vs Claude」,加「要不要召回 / 召回幾步」;對應已建查詢側 gate（is_short_query=近似 'A' 不檢索）。 |
| **自動標註（預測結果法）** | 與本專案 manual-accept 飛輪結合:Shiba 採納本地直答=該 query 標 'A'（本地能扛）;回退 Claude=標 'C'（需重召回/協作）——**用採納訊號自動養 router 標籤**。 |
| **單步任務硬跑多步更差** | 印證本專案「13% 採納天花板 + 優雅回退」:不是所有 query 都該重召回,過度 agentic 反傷效率與準確。 |
| **A/B/C 同構採納驗證** | ⚠ 本專案採納實測 A=0/B=13/C=13;Adaptive-RAG 的 'A' 不檢索檔可能對應本專案「本地直接會、不需 Library」的高信心區。 |

## 侷限 / 與本專案差異
1. **分類器誤分**：~31% 複雜 query 誤判單步、~47% 不檢索 query 誤判單步——本專案 router 升級後須測誤分率,誤判 'A' 會漏召回。
2. **自動標註是單一 instantiation,可能標錯**:本專案用採納訊號標註,品質取決於採納訊號乾淨度（避 auto 採納陷阱 [[project-finetune-yield-diagnosis]]）。
3. domain:開放域 QA;本專案 query 是指令任務,複雜度語義不同（單步=單指令、多步=多階段任務）。
4. 需訓練分類器:可先用規則版（已有 gate）,累積採納樣本後再訓 T5 分類器。
