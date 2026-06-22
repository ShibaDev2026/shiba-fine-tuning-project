# RankRAG: Unifying Context Ranking with Retrieval-Augmented Generation in LLMs

> arXiv: https://arxiv.org/abs/2407.02485 ｜ html: https://arxiv.org/html/2407.02485 ｜ NeurIPS 2024
> 作者: Yue Yu, Wei Ping, Zihan Liu, Boxin Wang, Jiaxuan You, Chao Zhang, Mohammad Shoeybi, Bryan Catanzaro（NVIDIA）｜ 2024

## 關鍵詞
unified ranking+generation, instruction tuning, retrieve-rerank-generate, ranking data efficiency, single-model reranker, ChatQA

## 對應 Layer / Roadmap 階段
- **Roadmap P2（召回品質）→ P5（fine-tune 後期）** — RankRAG 證明「**同一個 LLM 用少量 ranking 資料就學會自排序候選**」,免養獨立 reranker。這對本專案 reranker PoC 失敗（memory: bge-reranker-v2-m3 零增益 + eval 陷阱）是另一條路:把排序內化進本地模型。

## 核心結論（帶實證數字）
1. **僅 ~50k ranking pairs 就追平專用 reranker**：RankRAG 8B 在 NQ 達 **R@10 84.0%**,**匹配/超越 monoT5-3B 與 BGE-Rerank-v2-m3**（後者用 503k–1.6M pairs）——資料效率 10–30×。
2. **9 個通用 QA 全面勝 ChatQA-1.5 與 GPT-4 RAG**（zero-shot）：NQ EM 50.6%（vs ChatQA 42.4%、GPT-4 40.4%）;2WikimQA EM 31.4%（vs 14.4%）;PopQA 57.6%。
3. **70B 不需生醫微調**就在 Mirage 達 78.06%,逼近 GPT-4 的 79.97%——泛化強。
4. **reranking 延遲僅 0.9×–6.0×**（N=20–100）,遠低於預期的 20×–100×。

## 方法機制拆解
### 兩階段 instruction tuning
- Stage I：128K 通用指令跟隨（對話/QA/CoT）。
- Stage II：統一 ranking+generation,blend ~50k ranking pairs（SFT + context-rich QA + RAG QA + context ranking MS MARCO + RAG ranking),全部轉成 (question, context, answer) 統一格式。
### 推論 Retrieve-Rerank-Generate
1. retriever 取 top-N（8B 用 N=100、70B 用 N=30）;
2. RankRAG 對每個 context「以 ranking prompt 生成答案為 True」算相關分;
3. rerank 留 top-k（典型 k=5）;
4. top-k 餵回同一模型生成答案。

## 速查（綁本專案具體設計決策）
| RankRAG 機制 | 本專案落地 |
|---|---|
| **同模型自排序、免獨立 reranker** | 本專案 reranker PoC 失敗後的替代:讓本地 Qwen/GLM **自己排序召回的 Pattern**,而非加 bge-reranker。排序內化 → 繞開「獨立 reranker 在 cosine-bound golden set 上無法評」的陷阱。 |
| **僅 50k ranking pairs（10–30× 效率）** | 對本專案資料稀缺友善:不需海量標註;manual-accept 採納對（採納=正例、回退=負例）可當 ranking pair 種子。 |
| **retrieve 多(N=100)→rerank 少(k=5)** | 解本專案「擴 top-k 爆 context」兩難:先寬召回再由模型壓到 top-5 注入,兼顧涵蓋率（ExpRAG K 越大越好 [[paper-06]]）與 context 預算。 |
| **延遲僅 0.9–6×** | 本地推論可接受;但 N=100 對本地模型 context 仍重,需實測。 |

## 侷限 / 與本專案差異
1. **單輪檢索為主**,多輪 RAG 整合留未來——本專案 Agentic 多步召回需另解。
2. **需 instruction tuning**（Stage II）：與「先零訓練」略衝突 → P5 才考慮;P2 可先用 prompt-based 讓本地模型排序（零訓練近似）。
3. domain:通用知識 QA;本專案排序對象是「指令模式適用性」,ranking prompt 需重設計。
4. 與獨立 reranker 路線的取捨:RankRAG 省一個模型但加本地模型負擔;本專案本地資源緊（JIT 載入裁判）需評估。
