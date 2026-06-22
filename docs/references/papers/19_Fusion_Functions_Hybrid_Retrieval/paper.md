# An Analysis of Fusion Functions for Hybrid Retrieval

> arXiv: https://arxiv.org/abs/2210.11934 ｜ ar5iv: https://ar5iv.labs.arxiv.org/html/2210.11934
> 作者: Sebastian Bruch, Siyu Gai, Amir Ingber｜ 2022（ACM TOIS）

## 關鍵詞
hybrid retrieval, convex combination (TM2C2), reciprocal rank fusion (RRF), score normalization, Lipschitz continuity, in-domain vs out-of-domain

## 對應 Layer / Roadmap 階段
- **Roadmap P2 + Layer 1** — 本專案若啟用 bge-m3 的 sparse head（見 [[paper-12]]）做 dense+sparse hybrid,**本篇直接回答「該怎麼融合」**：別用 RRF,用 convex combination。

## 核心結論（帶實證數字）
1. **RRF 對參數敏感、且調好的參數無法跨域泛化**：作者用 heatmap 證 RRF 效能「隨參數劇烈擺盪」,in-domain 調好的 RRF 參數 OOD 失效——推翻「RRF 免調穩健」的普遍印象。
2. **Convex Combination（CC/TM2C2）全面更穩更好**（NDCG@1000）：MS MARCO TM2C2 0.454 vs RRF 0.425;NQ 0.542 vs 0.514;HotpotQA 0.699 vs 0.675。in-domain 與 OOD 都贏。
3. **理論**：CC 具 Lipschitz 連續（分數小變動→融合分數小變動）,RRF 因作用在 rank 上不具此性質;且不同正規化（min-max / z-score）的 CC 互為 rank-equivalent → 正規化選擇不敏感。
4. **CC 樣本效率高**：只需少量樣本調唯一參數 α 即可適配新域。

## 速查（綁本專案具體設計決策）
| 本篇結論 | 本專案落地 |
|---|---|
| **hybrid 用 CC 不用 RRF** | bge-m3 dense+sparse 融合直接採 `α·dense + (1−α)·sparse`,別用 RRF——避開本專案 golden set 小、OOD 調參不穩的坑。 |
| **CC 樣本效率高（單參數）** | 本專案標註資料稀缺,CC 只需調 α、少量樣本即可,契合資源約束。 |
| **正規化不敏感** | 減少本專案調參負擔,min-max 即可。 |
| **Lipschitz 穩定** | sparse 分數有雜訊時 CC 不會爆走,比 RRF 適合本專案不穩定的指令語料。 |

## 侷限 / 與本專案差異
1. 假設檢索分數變異夠大;本專案若召回分數集中需注意邊界。
2. 主要融合兩系統;加 multi-vector 第三路稱「trivial 但未測」。
3. domain：通用 IR；本專案需先實測 dense+sparse CC 在中文指令模式上是否真贏純 dense（base-assumption-first，配合 [[paper-12]] 的 sparse PoC）。
