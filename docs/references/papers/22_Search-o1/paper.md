# Search-o1: Agentic Search-Enhanced Large Reasoning Models

> arXiv: https://arxiv.org/abs/2501.05366 ｜ html: https://arxiv.org/html/2501.05366
> 作者: Xiaoxi Li, Guanting Dong, Jiajie Jin, Yuyao Zhang, Yujia Zhou, Yutao Zhu, Peitian Zhang, Zhicheng Dou｜ 2025

## 關鍵詞
agentic RAG, large reasoning model, uncertainty-triggered retrieval, Reason-in-Documents, knowledge gap

## 對應 Layer / Roadmap 階段
- **Roadmap P2（Agentic 召回）** — 把召回嵌進推理模型的思考鏈,且加「文件精煉模組」再注入——對應本專案「召回後不直接塞、先精煉」的 Verifier/精煉思路。

## 核心結論（帶實證數字）
1. **uncertainty-triggered 檢索**：推理模型思考時頻繁產不確定詞（如 "perhaps" 平均 >30 次/難題）→ 觸發自主搜尋補知識缺口。
2. **Reason-in-Documents 模組**：不直接注入原始召回文件,而是先針對當前查詢+先前推理**精煉抽取相關資訊**再回填推理鏈（= 召回後過濾,呼應 CRAG decompose-recompose [[paper-13]]）。
3. **數字**：GPQA 63.6% vs RAgent-QwQ-32B 61.6%、MATH500 86.4%、多跳 QA 平均 EM 超 RAG-QwQ-32B **+29.6%**（HotpotQA 45.2% vs 34.2%）;GPQA 擴展集 57.9% 超人類專家 39.9–48.9%。
4. **單跳 QA 增益微小**：agentic 檢索只在複雜多步推理才划算。

## 速查（綁本專案具體設計決策）
| Search-o1 機制 | 本專案落地 |
|---|---|
| **Reason-in-Documents（注入前精煉）** | 召回的 Pattern 先精煉成「與當前任務相關的部分」再餵本地模型,降雜訊、省 context（呼應 CRAG/TRAD）。 |
| **uncertainty-triggered 檢索** | 本地模型執行時偵測自身不確定→才召回,對應 adaptive retrieval（[[paper-16]]）+ Verifier 的 IsUse 自評（[[paper-11]]）。 |
| **單跳增益微小** | 印證：簡單指令不需 agentic 召回,過度檢索無益（13% 天花板下省成本）。 |

## 侷限 / 與本專案差異
1. 用大型推理模型（QwQ-32B 級）；本專案本地模型較小,uncertainty 訊號與推理深度受限。
2. domain：科學/數學/QA；本專案指令執行的「知識缺口」語義不同。
3. 化學等專業仍輸專家——召回非萬靈丹。
