# Papers Index

快速引用索引。需要細節時 Read 對應 paper.md 的段落。

> ⚠ **Provenance（05–26）**：數字經 WebFetch 摘要抽取自 arxiv 頁、**未逐一對 PDF 核**。存在性/方法/方向性結論可信；任何要驅動 PoC 或花費的具體數字，行動前回核原文。05–07 附 PDF，08–26 因 arxiv 限速暫缺（可日後補抓）。

---

## 01 Self-Evolving LLMs via Continual Instruction Tuning (MoE-CL)

**路徑**: `01_Self-Evolving_LLMs_via_Continual_Instruction_Tuning/paper.md`
**arXiv**: https://arxiv.org/html/2509.18133v4
**關鍵詞**: 災難性遺忘, MoE-LoRA, GAN discriminator, continual instruction tuning, catastrophic forgetting
**對應 Layer**: Layer 3 Fine-tuning Pipeline — 持續訓練課程設計、多任務 LoRA 架構
**核心結論**:
- 雙 LoRA expert：任務專用（保留知識）+ 共享（跨任務遷移）
- GAN task-aware discriminator 抑制共享 expert 的任務無關雜訊
- MTL5 Acc: 80.5%（vs MoCL 78.2%）；Tencent3 +15.3% stripping rate
- 推論延遲 6.3ms/sample，工業可接受
**速查**: 本專案兩個 LoRA adapter（block1/block2）的分離設計靈感來源

---

## 02 SEAL: Self-Adapting Language Models

**路徑**: `02_SEAL_Self-Adapting_Language_Models/paper.md`
**arXiv**: https://arxiv.org/html/2506.10943
**關鍵詞**: self-edit, RL meta-learning, ReSTEM^EM, test-time training, knowledge incorporation
**對應 Layer**: Layer 2 自動評分迴圈 — 模型自生成訓練資料、RL 強化有效樣本
**核心結論**:
- 模型接收新資訊 → 生成 self-edit（訓練指令）→ LoRA SFT 更新 → RL 獎勵有效 edit
- ReSTEM^EM = Rejection Sampling + SFT（比 GRPO/PPO 穩定）
- SQuAD QA: 47.0%（超越 GPT-4.1 的 46.3%）；ARC-AGI: 72.5% vs 基準 20%
- 7B 模型 RL 改善比例 2.04×，越強的模型效益越高
**速查**: Layer 2 的「AI 師父生成問題集 → 模型回答 → 評分 → 訓練」迴圈的理論依據

---

## 03 From RAG to Memory (HippoRAG 2)

**路徑**: `03_From_RAG_to_Memory/paper.md`
**arXiv**: https://arxiv.org/html/2502.14802v1
**關鍵詞**: HippoRAG, Personalized PageRank, dense-sparse integration, knowledge graph, non-parametric continual learning
**對應 Layer**: Layer 1 RAG 升級路徑 — FTS5 → embedding + 知識圖譜方向
**核心結論**:
- 稀疏節點（短語概念）+ 密集節點（段落上下文）混合索引
- Query-to-triple linking 比 NER-to-node 提升 12.5%
- LLM Recognition Memory 過濾降低雜訊
- 多跳推理 +7%；MuSiQue Recall@5 +5.0%，2Wiki +13.9%
- 處理成本：GPT-4o-mini batch < $22 USD/11,656 段落
**速查**: 當前 FTS5 召回瓶頸的升級目標；中文語意召回問題的長期解法

---

## 04 FOREVER: Forgetting Curve Memory Replay

**路徑**: `04_FOREVER_Forgetting_Curve_Memory_Replay/paper.md`
**arXiv**: https://arxiv.org/html/2601.03938v1
**關鍵詞**: Ebbinghaus forgetting curve, parameter update magnitude, model-centric time, replay scheduler, intensity-aware regularization
**對應 Layer**: Layer 1 衰減設計（access_count/last_accessed/decay_score）+ Layer 3 訓練樣本比例
**核心結論**:
- 用參數更新量 Δₜ 定義「模型時間」，替代步數計時
- Ebbinghaus 間隔 {1,2,4,7,15,30...} 映射到模型時間閾值 → 早密後疏重播
- 強度感知正則化：rₜ = μₜ/μ₀，變化劇烈時加強重播約束
- 記憶緩衝區僅需訓練資料 2%；0.6B~13B 一致改善
- vs VBM（step-based Ebbinghaus）: +1.2% OP, +1.1% BWT
**速查**: 本專案 70/20/10 訓練比例設計靈感；Layer 1 decay_score 衰減邏輯依據

---

> 以下 05+ 為 2026-06-22 RAG-augmented 代理執行重定向後收錄（主線：Pattern Library + Agentic 召回 + Verifier）。pending 暫存區尚有 19 篇待分析。

## P1 — Pattern Library / 經驗學習

## 05 Agent Workflow Memory (AWM)

**路徑**: `05_Agent_Workflow_Memory/paper.md`
**arXiv**: https://arxiv.org/abs/2409.07429
**關鍵詞**: workflow induction, reusable routine, selective injection, offline/online memory, Mind2Web, WebArena
**對應 Layer**: Roadmap P1 Pattern Library 學術原型 + P2 in-context 執行 + Layer 1 selective injection
**核心結論**:
- 歸納可重用 workflow（非堆原始軌跡）：WebArena 23.5%→35.5%（+51.1% 相對）、步數更少
- 無人工監督卻贏人工 workflow（SteP 33.0%）；cross-domain 增益最大 +16.9pt
- online 模式 induce→integrate→utilize 迴圈，L_eval 成功才寫回 memory
- 非固定值參數化（dry cat food→{product-name}）提升泛化
**速查**: P1 飛輪閉環直接採用 AWM；本專案改 L_eval→Shiba manual-accept（避 auto 採納陷阱）；參數化解 RAG 逐字具體死路

## 06 ExpRAG: Learning to Learn from Experience

**路徑**: `06_ExpRAG_Learning_to_Learn_from_Experience/paper.md`
**arXiv**: https://arxiv.org/abs/2603.18272
**關鍵詞**: experience retrieval, trajectory memory, ExpRAG-LoRA, static vs dynamic retrieval, OOD generalization
**對應 Layer**: 主線最直接學術對應（storage/query/trajectory 三決策）+ P1/P2 + P5 fine-tune 配方
**核心結論**:
- 推論期檢索增強：ALFWorld zero-shot 29.9%→64.18%；top-K 是主旋鈕（K=1→4：41%→64%）
- ExpRAG-LoRA 解標準 LoRA 的 OOD 崩潰：Qwen2.5-7B 70.5%→90.2%（本專案 training base！）
- 空 index→88.5% 崩 29.5%：**涵蓋率是硬約束**（背書 P1 EV gate）
- dynamic 召回任務相依（ALFWorld +7.1 / ScienceWorld −9.3）
**速查**: storage 三決策軸指導 Library；read-only 侷限正由本專案 manual-accept 飛輪補上；P5 用 retrieval-augmented LoRA 非裸 LoRA

## P2 — 召回品質 / in-context 範例選擇

## 07 DICE: Dynamic In-Context Example Selection

**路徑**: `07_DICE_Dynamic_In-Context_Example_Selection/paper.md`
**arXiv**: https://arxiv.org/abs/2507.23554
**關鍵詞**: transferable knowledge, causal decomposition, information-theoretic selection, InfoNCE, training-free plug-in, stepwise
**對應 Layer**: P1 transferability 軸 + P2 example selection + Layer 1（破 cosine-bound）
**核心結論**:
- 用「可遷移知識(TK)」軸選範例，正交於 cosine、濾 spurious：HotpotQA ReAct 32.1%→41.4%（+9.3）
- 免訓練贏過 kNN(KATE 34.7%) 與 trained selector(EPR 36.5%)；stepwise>taskwise
- 3 精選範例 = 6 隨機範例效能（省 context）；retriever 用 gemma-2-2b-it（可本地）
**速查**: 直接破 golden set cosine-bound 困局（換軸非比排序）；TK 抽取濾掉 spurious 的 repo 路徑/檔名；少而精注入貼合 13% 天花板

## 08 Completing Missing Annotation: Multi-Agent Debate (DREAM / BRIDGE)

**路徑**: `08_Completing_Missing_Annotation_Multi-Agent_Debate/paper.md`
**arXiv**: https://arxiv.org/abs/2602.06526（ICLR 2026）
**關鍵詞**: hole problem, missing relevance annotation, multi-agent debate, DREAM, BRIDGE, human-in-the-loop escalation
**對應 Layer**: P1 + Layer 1 評估框架（修 golden set cosine-bound）
**核心結論**:
- 多代理辯論補漏標：95.2% 準確率、僅 3.5% 人工介入；建 BRIDGE 揪 29,824 漏標 chunk
- 漏標扭曲 retriever 排名 + RAG retrieval-generation misalignment（=本專案 reranker PoC 失敗根因）
**速查**: 本地三裁判可當辯論 agent 補標 → 解除 cosine-bound、讓 reranker/sparse 能被公平評；把「修 golden set」成本壓到 3.5% 人工，可能翻轉「不划算」結論

## 09 HyDE: Hypothetical Document Embeddings

**路徑**: `09_HyDE_Hypothetical_Document_Embeddings/paper.md`
**arXiv**: https://arxiv.org/abs/2212.10496
**關鍵詞**: hypothetical document embeddings, zero-shot dense retrieval, query-document asymmetry, dense bottleneck
**對應 Layer**: P2 + Layer 1（補短查詢召回涵蓋率）
**核心結論**:
- LLM 生成假設文件再 embed：TREC DL19 nDCG@10 61.3 vs Contriever 44.5、逼近 fine-tuned 62.1
- BEIR TREC-COVID 59.3 vs 27.3；多語言 Mr.TyDi 跨語言一致增益（中文場景正向）
- dense bottleneck 過濾假設文件的錯誤細節、接地真實語料
**速查**: 本地模型依短指令生成「假設模式文件」→ bge-m3 embed 召回真實 Pattern；解 is_short_query 兩難（短但有意義 query 先 HyDE 擴寫不必一刀攔）

## 10 Query Rewriting for RAG (Rewrite-Retrieve-Read)

**路徑**: `10_Query_Rewriting_for_RAG/paper.md`
**arXiv**: https://arxiv.org/abs/2305.14283
**關鍵詞**: query rewriting, trainable rewriter, PPO, black-box reader feedback
**對應 Layer**: P2 + Layer 1（縮 query-document gap）
**核心結論**:
- T5-large(770M) + PPO rewriter：HotpotQA EM 30.47→34.38、AmbigNQ→47.80
- reward = EM/F1/Hit + KL 正則；弱 reader(Vicuna) 改善更大
**速查**: manual-accept 飛輪 = 天然 RL reward（採納+/回退−）；可先用 few-shot LLM rewriter 零訓練版；與 HyDE 互補可 A/B

## 11 Self-RAG

**路徑**: `11_Self-RAG/paper.md`
**arXiv**: https://arxiv.org/abs/2310.11511（ICLR 2024 Oral）
**關鍵詞**: reflection tokens, adaptive retrieval, self-critique, on-demand retrieval, IsRel/IsSup/IsUse
**對應 Layer**: P2 + P3 Verifier + Layer 0 路由
**核心結論**:
- 四種 reflection token（Retrieve/IsRel/IsSup/IsUse）做按需檢索+自我批判
- Self-RAG 7B/13B 全面勝 Llama2-chat 與標準 RAG；PubHealth/PopQA 勝 ChatGPT（citation 輸 65.1 vs 70.3）
**速查**: Retrieve token 對應本專案查詢側 gate（is_short_query 等）；IsSup/IsUse = P3 Verifier 的 check 階段；低 IsUse 優雅回退 Claude（13% 天花板）

## 12 BGE-M3 Embedding

**路徑**: `12_BGE-M3_Embedding/paper.md`
**arXiv**: https://arxiv.org/abs/2402.03216
**關鍵詞**: multi-functionality, dense/sparse/multi-vector, self-knowledge distillation, hybrid scoring
**對應 Layer**: Layer 1（本專案 embedding 本體！）+ P2
**核心結論**:
- 同模型同時輸出 dense/sparse/multi-vector；MIRACL hybrid 71.5 > dense 69.2、長文檔 sparse 62.2 ≫ dense 52.5
- hybrid = w1·dense+w2·sparse+w3·multivec；self-knowledge distillation 三 head 互教
**速查**: ⚠ **謹慎 reframe（advisor 校正）**：本專案 Layer 1 本就是「FTS5 + Embedding」、已有 lexical arm，但 B 組 probe 記錄該 FTS5 arm 壞掉（sessions_fts 不對齊 exchange、|fts|=0）。故 bge-m3 sparse head 的價值是「**修/換這條已壞的 lexical arm**」而非全新軸；增益仍部分撞 golden set cosine-bound 測量牆 → 須與 08 DREAM 補標**綁一起**（先解除 cosine-bound 才測得出）。**非重開已結案的 B 組**，要提 Shiba 須連同此前提

## P3 — Verifier（propose-check-execute 安全閘）

## 13 CRAG: Corrective Retrieval Augmented Generation

**路徑**: `13_Corrective_RAG/paper.md`
**arXiv**: https://arxiv.org/abs/2401.15884
**關鍵詞**: retrieval evaluator, confidence triage, decompose-then-recompose, web search fallback
**對應 Layer**: P3 Verifier（檢索側）+ P2
**核心結論**:
- T5-large 評估器分三檔（Correct/Ambiguous/Incorrect）觸發精煉/合併/web 回退；評估器 PopQA 84.3% 準確
- vs 標準 RAG：PubHealth +10.6、Arc +10.3；Self-CRAG 可疊加 Self-RAG（PopQA 61.8 vs 54.9）
**速查**: 召回側 Verifier——高信心執行/模糊合議/低信心回退 Claude（對應 13% 天花板）；decompose-recompose 濾 spurious 片段

## 14 VeriGuard: Verified Code Generation

**路徑**: `14_VeriGuard_Verified_Code_Generation/paper.md`
**arXiv**: https://arxiv.org/abs/2510.05156
**關鍵詞**: propose-check-execute, formal verification, Nagini, Hoare triple, offline policy + online monitor, ASR/TSR
**對應 Layer**: P3 Verifier 最直接藍本
**核心結論**:
- 離線生成+formal 驗證 policy（Nagini/Hoare）+ 線上執行前攔截，五種違規策略
- ASB ASR 51.9%→0.0%、TSR 維持（Claude-Sonnet-4 85.1%）；EICU-AC 100%
- 勝純 LLM 護欄 GuardRail（ASR 0 但 TSR 僅 40.2% 過度阻擋）= 本專案「擋危險不過度阻擋」量化警示
**速查**: 把 CLAUDE.md 危險操作規則編成可驗證 policy + 執行前攔截器；formal verification 重型，初期用規則+本地裁判輕量版

## 15 Towards Verifiably Safe Tool Use

**路徑**: `15_Verifiably_Safe_Tool_Use/paper.md`
**arXiv**: https://arxiv.org/abs/2601.08012（ICSE NIER 2026）
**關鍵詞**: STPA hazard analysis, MCP capability labels, blocklist/mustlist/allowlist/confirmation, Alloy modeling
**對應 Layer**: P3 Verifier（規格方法論層）
**核心結論**:
- ⚠ NIER 初步成果無實證數字；用 Alloy 形式建模證可行
- STPA 系統導出 hazard + MCP capability/confidentiality/trust 標籤 + 四層 enforcement
**速查**: **直接形式化本專案危險操作確認規則**（rm/push main=Confirmation、洩漏 Key=Blocklist、git status=Allowlist）；與 VeriGuard 互補（本篇給規格、VeriGuard 給引擎）

## P2 補 — 召回路由 / 排序

## 16 Adaptive-RAG

**路徑**: `16_Adaptive-RAG/paper.md`
**arXiv**: https://arxiv.org/abs/2403.14403（NAACL 2024）
**關鍵詞**: query complexity classifier, A/B/C routing, automatic labeling, efficiency-accuracy tradeoff
**對應 Layer**: P2 + Layer 0 路由（升級 router）
**核心結論**:
- 複雜度分類器三檔（A 不檢索/B 單步/C 多步）路由；~50% 效率達 multi-step 準確度
- 單步任務硬跑多步反更差更慢（SQuAD F1 38.3/2.02s vs 35.6/9.03s）；誤分 31%/47%
**速查**: 升級 L0 router（要不要召回/幾步）；用 manual-accept 採納訊號自動養 A/B/C 標籤；A/B/C 與採納驗證 A=0/B=13/C=13 同構

## 17 RankRAG: Unifying Context Ranking with RAG

**路徑**: `17_RankRAG/paper.md`
**arXiv**: https://arxiv.org/abs/2407.02485（NeurIPS 2024）
**關鍵詞**: unified ranking+generation, instruction tuning, retrieve-rerank-generate, ranking data efficiency
**對應 Layer**: P2 召回品質 → P5 fine-tune
**核心結論**:
- 同一 LLM 用 ~50k ranking pairs 學會自排序：NQ R@10 84.0% 追平 bge-reranker-v2-m3（後者 503k–1.6M pairs，效率 10–30×）
- 9 QA 全勝 ChatQA-1.5/GPT-4 RAG（NQ EM 50.6 vs 42.4）；reranking 延遲僅 0.9–6×
**速查**: reranker PoC 失敗後的替代——讓本地模型自排序（繞 cosine-bound 陷阱）；manual-accept 採納對當 ranking pair；寬召回 N=100→壓 k=5 解擴 top-k 爆 context

## P2 補 — 多步召回（補涵蓋率）

## 18 Self-Ask

**路徑**: `18_Self-Ask/paper.md` ｜ **arXiv**: https://arxiv.org/abs/2210.03350
**關鍵詞**: self-ask, follow-up questions, compositionality gap, prompt-only
**對應 Layer**: P2 ｜ **核心**: prompt-only 分解+檢索交錯，零微調；Compositional Celebrities 45.4%→79.6%；compositionality gap 恆 40% 不隨規模縮
**速查**: 本地最輕量多步召回；複雜指令拆 follow-up 子任務各召回；組合推理斷裂非僅排序問題

## 19 Fusion Functions for Hybrid Retrieval

**路徑**: `19_Fusion_Functions_Hybrid_Retrieval/paper.md` ｜ **arXiv**: https://arxiv.org/abs/2210.11934
**關鍵詞**: convex combination (TM2C2), RRF, score normalization, Lipschitz, OOD
**對應 Layer**: P2 + Layer 1（hybrid 融合法）｜ **核心**: RRF 對參數敏感+OOD 失效；CC 更穩更好（HotpotQA 0.699 vs 0.675）、樣本效率高、Lipschitz 連續
**速查**: bge-m3 dense+sparse 融合用 CC（α·dense+(1−α)·sparse）不用 RRF；單參數少樣本適配——直接配 [[paper-12]] sparse PoC

## 20 IRCoT

**路徑**: `20_IRCoT/paper.md` ｜ **arXiv**: https://arxiv.org/abs/2212.10509
**關鍵詞**: interleaved retrieval, chain-of-thought, multi-hop, retrieval recall
**對應 Layer**: P2 ｜ **核心**: 推理↔檢索交錯；檢索 recall 大增（2Wiki +14~+22）、事實錯誤減半——直擊「瓶頸是涵蓋率」
**速查**: 多階段任務每步重召回補 recall；與 Adaptive-RAG 互補（先判該不該多步）

## 21 TRAD

**路徑**: `21_TRAD/paper.md` ｜ **arXiv**: https://arxiv.org/abs/2403.06221
**關鍵詞**: step-wise thought retrieval, aligned decision, temporal neighbor, plausible-example
**對應 Layer**: P2 ｜ **核心**: step-level 召回+鄰步補齊，避 plausible examples；ALFWorld 96.77%；真實部署 65%→92.5%
**速查**: **直接對症 macro-exchange 死路**——召回單一指令步非整段軌跡；思考相似度濾 spurious（同 DICE 軸）

## 22 Search-o1

**路徑**: `22_Search-o1/paper.md` ｜ **arXiv**: https://arxiv.org/abs/2501.05366
**關鍵詞**: agentic RAG, reasoning model, uncertainty-triggered, Reason-in-Documents
**對應 Layer**: P2 ｜ **核心**: 不確定觸發檢索 + 注入前精煉（Reason-in-Documents）；多跳 EM +29.6%；單跳增益微小
**速查**: 召回後先精煉再餵本地模型（降雜訊省 context）；簡單指令不需 agentic 召回

## 24 Search-R1

**路徑**: `24_Search-R1/paper.md` ｜ **arXiv**: https://arxiv.org/abs/2503.09516
**關鍵詞**: RL for retrieval, PPO/GRPO, retrieved-token masking, Qwen2.5, outcome reward
**對應 Layer**: P5 + P2 ｜ **核心**: RL 教交錯搜尋，base=Qwen2.5-3B/7B（本專案 base！）7B +24% 勝 RAG；retrieved-token masking + 純 EM reward
**速查**: P5 訓「會召回的本地模型」直接配方；manual-accept ≈ outcome reward；P2 不採留 P5

## L1 診斷 / 評估方法論

## 25 Procedural Memory Retrieval Benchmark

**路徑**: `25_Procedural_Memory_Retrieval_Benchmark/paper.md` ｜ **arXiv**: https://arxiv.org/abs/2511.21730
**關鍵詞**: generalization cliff, mean-pooling bag-of-words, state-aware vs action-only, coverage
**對應 Layer**: Layer 1 + P1/P2（根本診斷）｜ **核心**: mean pooling 把程序當詞袋丟時序、換物件即崩（unseen MAP −29.9%）；**語料 4.3×→MAP +27.7% ≫ 表徵精煉 +9.9%**
**速查**: **指令模式純 cosine 召回失效的機制層解釋**；背書 P1 EV gate（涵蓋率>>精煉）；summary embedding 最抗跌→支持蒸餾非存 raw

## Survey / SoK（設計詞彙 + Verifier 清單）

## 23 Agentic RAG: A Survey

**路徑**: `23_Agentic_RAG_Survey/paper.md` ｜ **arXiv**: https://arxiv.org/abs/2501.09136
**關鍵詞**: taxonomy, single/multi-agent, corrective, adaptive, reflection/planning/tool-use
**對應 Layer**: 全線（設計詞彙）｜ **核心**: 六大架構分類 + 四設計模式；open challenge 含「評估超越輸出品質」
**速查**: 本專案=Single-Agent Router→往 Corrective+Adaptive 演進，不需 Multi-Agent/Graph 重架構

## 26 SoK: Agentic RAG

**路徑**: `26_SoK_Agentic_RAG/paper.md` ｜ **arXiv**: https://arxiv.org/abs/2603.07379
**關鍵詞**: POMDP formalization, four axes, six failure modes, layered evaluation
**對應 Layer**: P3 Verifier + 評估框架 ｜ **核心**: POMDP 形式化（成本-效益）；**六大 failure mode = Verifier 檢查清單**；三層評估（組件/軌跡/系統）
**速查**: Verifier 需求清單（本專案最該防 #3 Tool Misuse + #4/#5 Library 污染）；分層評估回應 cosine-bound 困局；四軸定位本專案
