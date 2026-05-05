# Papers Index

快速引用索引。需要細節時 Read 對應 paper.md 的段落。

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
