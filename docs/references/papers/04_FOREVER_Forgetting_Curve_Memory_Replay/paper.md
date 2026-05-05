# FOREVER: Forgetting Curve-Inspired Memory Replay for Language Model Continual Learning

> arXiv: https://arxiv.org/html/2601.03938v1

## Abstract

Continual learning for large language models aims to enable sequential knowledge acquisition without catastrophic forgetting. Memory replay methods are widely used but typically rely on fixed, step-based heuristics that often misalign with the model's actual learning progress. Motivated by findings showing LLM forgetting mirrors the Ebbinghaus human forgetting curve, this paper proposes FOREVER, a novel continual learning framework that aligns replay schedules with **model-centric time** defined by parameter update magnitude rather than raw training steps. FOREVER incorporates a forgetting curve-based replay scheduler to determine **when to replay** and an intensity-aware regularization mechanism to adaptively control **how to replay**. Extensive experiments on three benchmarks with models from 0.6B to 13B parameters demonstrate consistent improvements in mitigating catastrophic forgetting.

## 1 Introduction

**核心問題**：Replay-based continual learning 的兩個根本設計問題：
1. **When to replay**（何時重播）
2. **How to replay**（如何重播）

**關鍵洞察**：現有方法用訓練步數（step count）代替「時間」，但相同步數在不同學習率/批次大小下造成的模型變化差異巨大 → 不可靠。

**FOREVER 的解法**：用**參數更新量（parameter update magnitude）**定義模型自身的「時間」，將 Ebbinghaus 遺忘曲線對齊到模型的實際學習動態。

## 2 Proposed Method: FOREVER

### 問題定式

任務序列 {T₁,...,Tₖ}，每次只能存取當前任務資料 + 記憶緩衝區 M（保留各過去任務最多 |M| 個樣本，通常為訓練資料的 2%）。

### 2.1 When to Replay：遺忘曲線啟發的重播排程器

#### 模型中心時間校準（Model-Centric Time）

**步驟 1 — 計算每步參數更新量**：

```
Δₜ = ||Θₜ - Θₜ₋₁||₂
```

（僅計算可訓練參數，即 LoRA 權重）

**步驟 2 — 累積模型時間**：

```
τₜ = Σᵢ₌₁ᵗ Δᵢ
```

每個新任務開始時重置為 0。

**步驟 3 — 校準虛擬模型「天」**：

```
τ_day = Σᵢ₌₁^S Δᵢ   （S = warm-up 視窗大小，預設 24 步）
```

**步驟 4 — 映射 Ebbinghaus 人類天數**：

```
D_human = {1, 2, 4, 7, 15, 30, ...}  （Ebbinghaus 間隔）
D_model = {d · τ_day | d ∈ D_human}   （對應的模型時間閾值）
```

**步驟 5 — 觸發重播**：當 τₜ ≥ D_model^(j) 時觸發第 j 次重播。

**直觀意義**：早期訓練時模型變化劇烈 → τₜ 增長快 → 頻繁觸發重播；訓練穩定後 → τₜ 增長慢 → 重播間隔自然拉長。

### 2.2 How to Replay：強度感知重播正則化

**目標**：模型變化劇烈時加強重播約束，學習穩定後放寬。

**計算不穩定性比率**：

```
μ₀ = (1/S) Σₜ₌₁^S Δₜ                        （基準強度，warm-up 期間）
μₜ = (1-λ)μₜ₋₁ + λΔₜ                        （指數移動平均，λ=0.05）
rₜ = μₜ / μ₀                                 （不穩定性比率）
```

**自適應正則化強度**：

```
βₜ = β_base · clip(1 + γ(rₜ - 1), g_min, g_max)
```

（β_base=10⁻³，g_min=0.5，g_max=3.0）

**重播目標函數**：

```
L_replay = L_task^(old) + βₜ Σⱼ ||Θⱼ - Θⱼ*||₂²
```

其中 Θ* 是上一個任務結束時的參數快照。

## 3 Experiments and Analysis

### 資料集（三個基準）

| 基準 | 任務數 | 特性 |
|------|--------|------|
| Standard CL | 5 | 文字分類任務 |
| Long Sequence | 15 | 長序列知識累積 |
| SuperNI | 15 | 多樣化 NLP 生成任務 |

每任務 1,000 訓練實例，每類 500 評估實例。

### 評估指標

```
OP  = (1/K) Σᵢ aᵢ,ₖ          （整體效能，所有任務訓練完後的平均）
BWT = (1/(K-1)) Σᵢ (aᵢ,ₖ - aᵢ,ᵢ)  （後向遷移，負值越小越好）
```

### 主要結果

**Qwen3-0.6B 基準**：

| 方法 | OP | BWT |
|------|-----|-----|
| SSR（最強 replay 基準） | 58.7% | — |
| AIMMerging | — | -4.9% |
| VBM（Ebbinghaus step-based） | OP-1.2% | BWT-0.9% |
| **FOREVER** | **61.5%** | **-4.2%** |

**LLaMA3.1-8B**：

| 方法 | OP | BWT |
|------|-----|-----|
| VBM | 49.0% | -2.9% |
| **FOREVER** | **50.6%** | **-2.1%** |

FOREVER 在 0.6B → 13B 所有模型尺寸上一致優於基準。

### 消融研究

#### 重播排程策略比較

| 策略 | 描述 | 效果 |
|------|------|------|
| Fixed-interval (+FIR) | 固定間隔 | 最差 |
| Reversed (+RR) | 遞減間隔 | 差 |
| End-only (+ER) | 只在任務結束後重播 | 差 |
| **Ebbinghaus-inspired** | 早密後疏 | **最佳** |

#### 模型時間 vs 步數時間

模型中心時間校準比步數校準平均改善：+1.2% OP、+1.1% BWT。

#### 強度感知正則化

移除 IAR 導致明顯效能下降；與 EWC 參數重要性正則化（PIR）相比效果相當，但無需儲存重要性分數。

### 可視化

訓練期間：
- 早期 Δₜ 大 → τₜ 快速增長 → 頻繁觸發重播
- 後期 Δₜ 小 → τₜ 緩慢增長 → 重播間隔自然延長

重播觸發步數在不同任務間差異顯著，證明 FOREVER 根據模型內在學習進度決策，而非固定步數。

## 4 Related Work

### Continual Learning for LLMs 三大類

1. **正則化方法**：依重要性分數約束參數更新（EWC 等），LLM 規模下計算成本高
2. **架構方法**：任務專用 adapter、正交子空間、MoE 模組，減少干擾但需 task identifier
3. **重播方法**：結合 LoRA 效果最佳，但依賴啟發式排程 — FOREVER 解決此問題

### Forgetting Dynamics

LLM 遺忘呈現類人類記憶衰減模式：早期快速下降後緩慢退化。VBM 等方法已引入 Ebbinghaus 概念但仍用步數計時 → FOREVER 改用參數更新動態。

## 5 Conclusion

FOREVER 的核心貢獻：
1. **模型中心時間定義**：用參數更新量而非步數衡量「時間」
2. **Ebbinghaus-aligned 重播排程**：早密後疏，與模型學習動態對齊
3. **強度感知正則化**：自適應調整重播強度

在 3 個基準 × 4 個模型（0.6B-13B）上一致改善。

### 限制

1. **間接遺忘代理**：參數更新量是遺忘的間接指標，非直接任務效能退化
2. **固定 Ebbinghaus 間隔**：預定義模式可能非最優，未來可考慮從資料學習間隔模式

## Implementation Details

| 超參數 | 值 |
|--------|---|
| Warm-up 視窗 S | 24 步 |
| EMA 平滑係數 λ | 0.05 |
| 基礎正則化係數 β_base | 10⁻³ |
| 強度敏感度 γ | （論文附錄） |
| 裁剪範圍 [g_min, g_max] | [0.5, 3.0] |
| 記憶緩衝區大小 | 訓練資料的 2% |
| 評估模型 | Qwen3-0.6B/4B, LLaMA3.1-8B, LLaMA2-13B |
| 每組實驗重複次數 | 3 次獨立運行取平均 |
