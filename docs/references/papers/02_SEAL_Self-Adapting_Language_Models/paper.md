# SEAL: Self-Adapting Language Models

> arXiv: https://arxiv.org/html/2506.10943

## Abstract

Large language models remain fundamentally static post-pretraining, lacking inherent mechanisms to adjust their parameters in response to fresh data, tasks, or examples. This paper introduces Self-Adapting LLMs (SEAL), enabling models to autonomously generate their own training data and modification instructions. Given novel input, the system creates a "self-edit"—a generation that restructures information, specifies optimization settings, or invokes data augmentation tools for weight updates. Through supervised finetuning, these self-generated modifications produce lasting parameter adjustments. A reinforcement learning framework trains the model to produce effective self-edits, utilizing downstream performance as the reward signal. Unlike prior approaches depending on separate adaptation modules, SEAL leverages the model's native generation capabilities to parameterize and manage adaptation. Testing on knowledge incorporation and few-shot generalization demonstrates SEAL as a meaningful advancement toward models capable of autonomous, data-driven self-modification.

## 1 Introduction

本研究探索核心問題：**語言模型能否透過生成並轉換自身訓練材料與學習程序來自我適應？**

類比：學生考前主動將課堂筆記重組為個人化學習指南（而非被動消化原始資料），透過主動重構（概念圖、換句話說、具體範例）提升理解與表現。

**SEAL 的核心機制**：
- 模型接收新資訊 → 生成「self-edit」（自然語言指令，指定訓練資料及優化超參數）
- 執行 LoRA SFT 更新參數
- RL 框架訓練模型生成更有效的 self-edit，以下游效能為獎勵訊號

**兩個評估應用**：
1. **知識整合（Knowledge Incorporation）**：將 SQuAD 段落知識融入模型參數，QA 準確率從 33.5% → 47.0%，超越 GPT-4.1 合成資料
2. **少樣本學習（Few-shot Learning）**：ARC-AGI 基準，自動選擇資料增強與優化超參數，成功率 72.5% vs 基準 20%

## 2 Related Work

| 研究領域 | 與 SEAL 的關係 |
|----------|---------------|
| Synthetic Data Generation | SEAL 用 RL 訓練生成機制，直接最大化合成資料的下游效用 |
| Knowledge Updating | SEAL 採生成補充微調材料策略，用 RL 改善效果 |
| Test-Time Training (TTT) | SEAL inner loop 包含 TTT 迭代 |
| RL for LLMs | RL 用於優化 self-edit 材料創建，非最終輸出 |
| Meta-Learning | SEAL 透過外部優化循環學習適應策略 |

## 3 Methods

### 3.1 General Framework

**符號定義**：
- θ：模型參數
- (C, τ)：任務實例，C = 上下文，τ = 下游評估
- SE：self-edit（模型生成的訓練指令）
- θ' ← SFT(θ, SE)：使用 self-edit 更新參數

**RL 優化目標**：

```
L_RL(θ_t) := -E[(C,τ)~D][E[SE~LM_θt(·|C)][r(SE, τ, θ_t)]]
```

**訓練算法（ReSTEM^EM）**：
```
for outer iteration t=1,2,… do
  Sample (C,τ)~D
  Generate self-edit SE~LM_θ(·|C)
  Inner Loop: θ'_t ← SFT(θ_t, SE)
  Evaluate: Ans~LM_θ'_t(·|τ)
  Compute reward: r ← r(Ans, τ)
  Update: θ_{t+1} ← RL_Update(θ_t, r, SE)  ← 只保留 r=1 的 SE
end for
```

採用 **ReSTEM^EM**（Rejection Sampling + SFT）而非 GRPO/PPO（訓練不穩定）。

### 3.2 Domain Instantiations

#### 知識整合（Knowledge Incorporation）

- 提示模型列出段落衍生的 implications
- 對每個生成的 implication 計算語言模型損失，更新 LoRA 參數
- RL 訓練使模型學會以最有利於權重吸收的方式重組段落

#### 少樣本學習（Few-Shot Learning，ARC-AGI）

工具箱包含：
- **資料增強**：旋轉、翻轉、反射、轉置、調整大小、組合/迭代轉換
- **優化參數**：學習率、訓練輪數、損失計算方式（全 token 或僅輸出 token）

## 4 Results

### 4.1 Few-Shot Learning（Llama-3.2-1B-Instruct，ARC-AGI）

| 方法 | 成功率 |
|------|--------|
| ICL（無適應） | 0% |
| TTT + Self-Edit（無先驗 RL） | 20% |
| **SEAL** | **72.5%** |
| Oracle TTT | 100% |

### 4.2 Knowledge Incorporation（Qwen2.5-7B，SQuAD）

| 方法 | 單段落 (n=1) | 持續預訓練 (n=200) |
|------|-------------|-------------------|
| Base Model | 32.7% | 32.7% |
| Train on Passage Only | 33.5% | 36.0% |
| + 合成資料（無 RL） | 39.7% | 50.6% |
| + GPT-4.1 合成資料 | 46.3% | 59.4% |
| **SEAL** | **47.0%** | **58.2%** |

SEAL 以 7B 模型超越 GPT-4.1 合成資料（單段落）。RL 改善比例：7B 模型 2.04×（3B 模型 1.75×），模型越強效果越顯著。

## 5 Limitations

### 災難性遺忘（Catastrophic Forgetting）

持續修改後早期任務效能逐漸下降（Figure 6）。未來方向：
- 獎勵懲罰早期任務退步
- 空間約束修改（null-space constrained）
- RL inner loop 替換 SFT（RL 遺忘比 SFT 少）

### 計算開銷

每個 self-edit 評估需完整模型微調與評估，約 30-45 秒/個。比標準 RL 方法昂貴得多。

### 依賴標注資料

目前每個上下文需配對下游評估任務。未來方向：讓模型自行生成評估問題，擴展至無標注語料庫。

## 6 Discussion and Conclusion

**資料牆（Data Wall）論點**：Villalobos 等人預測 2028 年前沿模型將耗盡所有公開人類生成文本。未來發展需要：
1. 模型自行生成高效用訓練訊號
2. Meta 訓練專用 SEAL 合成材料生成器

**未來應用**：
- 學術論文攝取後自動生成 implications → 持續自我精進
- 與 chain-of-thought RL 結合（reasoning 前後更新參數）
- Agentic 模型：互動後生成 self-edit 更新權重，隨時間適應

## Implementation Details

| 設定 | 值 |
|------|---|
| Knowledge Incorporation 基底模型 | Qwen2.5-7B |
| Few-shot 基底模型 | Llama-3.2-1B-Instruct |
| LoRA rank（TTT） | 128 |
| LoRA rank（RL SFT） | 16 |
| ReSTEM^EM 迭代次數 | 2 |
| 每上下文 self-edit 樣本數 | 5 |
| 計算資源 | 2×H100 或 2×H200 |
| E-step（50 段落 × 5 完成 × 3 runs） | ~6 小時 |
