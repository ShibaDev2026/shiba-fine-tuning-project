# From Local to Global: A Graph RAG Approach to Query-Focused Summarization (Microsoft GraphRAG)

> arXiv: https://arxiv.org/abs/2404.16130
> 作者: Darren Edge, Ha Trinh, Newman Cheng, Joshua Bradley, Alex Chao, Apurva Mody, Steven Truitt, Jonathan Larson（Microsoft）｜ 2024

## 關鍵詞
entity knowledge graph, Leiden community detection, hierarchical community summaries, map-reduce query-focused summarization, global sensemaking

## 對應 Layer / Roadmap 階段
- **Roadmap P1（機制借鏡，非直接適配）** — 奠基 GraphRAG。針對「全域理解（global sensemaking）」查詢——這與本專案「找對的具體指令模式」（局部、事實型）**任務型態相反**，故屬機制借鏡（community 摘要思路）而非直接套用。

## 核心結論（帶實證數字）
1. **全域 sensemaking 查詢大勝向量 RAG**（~1M token 語料）：comprehensiveness 勝率 **72–83%**（Podcast）/72–80%（News）p<.001；diversity 75–82% / 62–71%。
2. **root-level 摘要（C0）省 9×–43× token** vs 原文 baseline。

## 方法機制拆解
- ① LLM 抽 entity 知識圖 ② Leiden 階層 community detection ③ 預生成 community 摘要 ④ map-reduce query-focused summarization 跨 community。

## 速查（綁本專案具體設計決策）
| GraphRAG 機制 | 本專案落地 |
|---|---|
| **針對 global sensemaking** | ⚠ **與本專案任務型態相反**：本專案是「找特定指令模式」（local fact），[[paper-34]] 已證此型 vanilla RAG ≈ 或勝 GraphRAG → **不適合直接套用**。 |
| **community 階層摘要** | 唯一可借鏡：若 Library 大到要「跨模式主題概覽」（如「我這類任務都怎麼做」），community 摘要有價值；但非當前 P1 需求。 |
| **9–43× token 節省（root 摘要）** | 預生成摘要降 query 期 token——但建索引成本高。 |

## 侷限 / 與本專案差異
1. **只測兩個 ~1M token 語料的 sensemaking**，泛化未知；有 fabrication 風險。
2. **建圖+community 摘要成本高**：對本專案「局部事實型」查詢 EV 低（[[paper-34]] 40× token 膨脹警示）。
3. 結論：**列為對照/煞車片**，非本專案 P1 採用對象。
