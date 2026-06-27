# LightRAG: Simple and Fast Retrieval-Augmented Generation

> arXiv: https://arxiv.org/abs/2410.05779
> 作者: Zirui Guo, Lianghao Xia, Yanhua Yu, Tu Ao, Chao Huang｜ 2024

## 關鍵詞
dual-level retrieval, graph-based indexing, incremental update, entity-relation KV, cost efficiency

## 對應 Layer / Roadmap 階段
- **Roadmap P1/P2** — LightRAG 的 **incremental update（免全量重建）** 對本專案 manual-accept 飛輪持續累積特別契合；dual-level（具體 entity + 高階主題）召回對應本專案兩種召回需求。

## 核心結論（帶實證數字）
1. **勝 GraphRAG（overall 勝率）**：Agriculture 54.8% / CS 52.0% / Legal 52.8% / Mix 49.6%——**僅小幅勝**。
2. **大勝 NaiveRAG**：Legal **84.8%** / Agriculture 67.6% / CS 61.2%。
3. **成本碾壓 GraphRAG**（Legal 檢索階段）：LightRAG **<100 token / 1 API call** vs GraphRAG 610×1,000 token / 610×1,000/Cmax calls。

## 方法機制拆解
- **dual-level 檢索**：Low-level（具體 entity + 屬性/關係）+ High-level（廣主題）。
- **圖索引**：LLM 抽 entity/relation → 每節點生成 text KV pair → 去重合併跨段落同實體。
- **incremental update**：新圖與原圖取 node/edge 聯集，免全量重處理。

## 速查（綁本專案具體設計決策）
| LightRAG 機制 | 本專案落地 |
|---|---|
| **incremental update（免重建）** | **直接契合 manual-accept 飛輪**：Shiba 採納新模式即增量併入 Library 圖，不必重建索引——比 GraphRAG/HippoRAG 重建友善。 |
| **dual-level（具體+主題）** | 召回兼顧「特定指令」（low）與「這類任務怎麼做」（high）。 |
| **成本 <100 token / 1 call** | 比 MS-GraphRAG（[[paper-38]]）輕量得多，本地可行。 |

## 侷限 / 與本專案差異
1. 未明列侷限；缺可擴展性、模糊 entity 抽取、非英文表現討論。
2. 仍是 doc-corpus entity 抽取範式；本專案「指令模式」的 entity/relation 需重定義（指令、工具、前後置）。
3. 勝 GraphRAG 幅度小——若不需全域 sensemaking，[[paper-34]] 提醒先評估是否需要任何圖化。
