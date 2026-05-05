# Self-Evolving LLMs via Continual Instruction Tuning

> arXiv: https://arxiv.org/html/2509.18133v4

## Abstract

This research addresses catastrophic forgetting in large language models during continuous learning through a novel parameter-efficient adversarial Mixture of LoRA Experts framework called MoE-CL. The system employs dual-expert architecture: dedicated LoRA experts preserve task-specific knowledge while a shared LoRA expert facilitates cross-task knowledge transfer. A GAN-based task-aware discriminator suppresses task-irrelevant noise within the shared expert, enabling autonomous knowledge refinement. Validation on MTL5 and Tencent3 benchmarks demonstrates effectiveness, with real-world A/B testing showing "15.3% reduction in manual review costs" in content compliance applications.

## 1. Introduction

Industrial-scale LLM deployment demands self-evolution capabilities—autonomous adaptation to diverse tasks while retaining prior competencies without constant human intervention. Real-world scenarios like Tencent's content compliance ecosystem processing "over two hundred thousand daily text reviews" underscore this necessity.

The catastrophic forgetting problem remains a critical barrier. Parameter updates during new task training inadvertently disrupt neural representations acquired from prior tasks, causing "significant performance degradation on previously mastered tasks." Existing approaches reveal fundamental trade-offs:

- **Replay-based methods**: Preserve knowledge through historical data or synthetic samples but suffer from data contamination and computational overhead
- **Regularization techniques**: Protect important weights yet restrict specialization in new tasks
- **Parameter isolation**: Prevents inter-task interference but limits "cross-task knowledge transfer" and semantic pattern leveraging

MoE-CL addresses these limitations through an adversarial mixture of LoRA experts architecture designed specifically for industrial-scale self-evolving continual instruction tuning. The framework maintains parameter independence via dedicated experts while enabling controlled knowledge integration through shared experts enhanced by GAN-based adversarial training.

## 2. Related Work

### 2.1. Self-Evolution of LLMs

Self-evolution encompasses three capability categories:

1. **Autonomous Learning Mechanisms**: Enable self-improvement through self-generated supervision, internal feedback, or rewarding signals
2. **Dynamic Architecture Adaptation**: Focuses on structural optimization including modular design search and fine-tuning architecture design
3. **Knowledge Integration Frameworks**: Consolidate cross-task knowledge through memory management and tool evolution

Current research "lacks a solution that balances autonomous knowledge retention and adaptive transfer," which MoE-CL addresses through dedicated experts for knowledge preservation, shared experts for integration, and GAN-based discriminators for noise suppression.

### 2.2. Continual Learning

Continual learning enables incremental knowledge incorporation across evolving domains while maintaining foundational competencies. Three primary approaches exist:

- **Continual pre-training**: Enhances knowledge efficiency through incremental data incorporation
- **Continual fine-tuning**: Adapts LLMs to specific tasks while preserving prior expertise
- **External knowledge integration**: Bridges representation gaps via retrieval or tool-based methods

### 2.3. Continual Instruction Tuning

This paradigm dynamically adapts LLMs through sequential task-specific instruction tuning. The critical challenge involves balancing knowledge retention with new task adaptation. Existing approaches show limitations:

- **LAMOL** (replay-based): Suffers from data noise and computational overhead
- **ARPER** (regularization): Overly restricts model specialization
- **TPEM** (architecture-based): Isolated parameters limit cross-task transfer
- **MoCL** (SOTA): Balances task specificity with cross-domain generalization but has inherent limitations

MoE-CL integrates dedicated task-specific experts with shared experts, mitigating catastrophic forgetting through adversarial training.

### 2.4. Adversarial Learning with MoE

Generative Adversarial Networks train generator and discriminator models simultaneously to produce robust, invariant outputs. In recommendation systems, adversarial learning effectively addresses biases and separates shared from task-specific features—aligning with continual learning's core challenge of "balancing knowledge retention and adaptation."

Mixture-of-Experts architectures dynamically combine specialized and shared knowledge, proving successful in multi-task learning and LLM fine-tuning. MoE-CL pioneerly integrates adversarial MoE frameworks into LLMs' continual instruction tuning, leveraging both paradigms to enhance continuous learning capacity.

## 3. Preliminary

### 3.1. Continual Learning

Continual instruction tuning optimizes LLMs across task sequences {T₁,...,Tₙ}, where each task Tᵢ contains learning samples {(xᵢ,yᵢ)}. The objective minimizes average loss across all sequential tasks:

**Equation (1)**: min_θ (1/N) Σᵢ₌₁ᴺ ℒᵢ(θ)

This ensures strong performance on recent tasks while maintaining competence across all encountered tasks.

### 3.2. Instruction Tuning with LoRA

Parameter-Efficient Fine-Tuning through LoRA modifies FFN layers in Transformer blocks using low-rank decomposition. For linear layers:

**Equation (2)**: h = Wx + ΔWx = Wx + (α/r)BAx

Where:
- x ∈ ℝᴵ encodes input information
- W ∈ ℝᴼˣᴵ represents pre-trained parameters
- A ∈ ℝʳˣᴵ and B ∈ ℝᴼˣʳ are low-rank matrices
- r << min(I,O)
- α determines scale of changes

Only matrices A and B require adjustment during fine-tuning, minimizing computational cost while maintaining learning capacity. In continual learning, each task receives an independent LoRA expert forming Mixture-of-Experts LoRA networks.

## 4. MoE-CL

### 4.1. Overview Architecture

MoE-CL employs an adversarial MoE-LoRA architecture adaptively combining task-specific and shared experts. Each task receives a dedicated LoRA expert learning task-specific knowledge with independently updated parameters, alleviating catastrophic forgetting. A shared LoRA expert extracts general cross-task knowledge, achieving high-quality knowledge transfer while minimizing irrelevant information interference.

### 4.2. Adversarial MoE-LoRA

MoE-CL employs a GAN with task classifier (task-aware discriminator) explicitly constraining shared LoRA expert parameters.

#### 4.2.1. The Generator in GAN

The generator transforms feed-forward layer outputs within transformer blocks into shared representations from the shared LoRA expert. These representations encapsulate common knowledge across tasks and deceive the task-aware discriminator. After training, the task-sharing LoRA expert learns high-quality cross-task information supporting subsequent task fine-tuning.

#### 4.2.2. Task-aware Discriminator

The task-aware discriminator identifies learning task labels. Given input vector zᵢ ∈ ℝᴴ from the i-th feed-forward layer:

**Equation (3)**: zₛ = ℱ_LoRA(zᵢ, θₛ)

**Equation (4)**: zₜ = ℱ_LoRA(zᵢ, θₜ)

Where ℱ_LoRA represents low-rank operations on frozen pre-trained LLM parameters, θₛ and θₜ represent learnable task-sharing and task-specific LoRA expert parameters.

The predicted task label becomes:

**Equation (5)**: l̂ₜ = ℱ(zₛ, φ)

Where ℱ applies softmax activation and φ represents task classifier learning parameters.

The GAN loss function compares ground truth and predicted labels:

**Equation (6)**: ℒ_GAN = ℱ_c(l̂ₜ, lₜ)

Where ℱ_c denotes cross-entropy loss.

### 4.3. Instruction Tuning Optimization

Post-instruction tuning predictions combine task-sharing and task-specific representations through weighted combination:

**Equation (7)**: z_{i+1} = βₛ·zₛ + βₜ·zₜ

Weight coefficients βₛ and βₜ derive from gating network 𝒢:

**Equation (8)**: βₛ, βₜ = 𝒢(zᵢ)

The representation z_{i+1} feeds into an MLP producing predictions. The prediction loss becomes:

**Equation (9)**: ℒ_SFT = ℱ_c(ŷₜ, yₜ)

Where yₜ and ŷₜ represent ground truth and predicted labels.

The final MoE-CL loss combines generative adversarial and prediction losses:

**Equation (10)**: ℒ = ℒ_SFT - α·ℒ_GAN

Where α ∈ [0,1] adjusts relative loss weighting. Ideally, the discriminator cannot distinguish task labels from shared representations, justifying the negative GAN loss in optimization.

## 5. Experiments

### 5.1. Experimental Setup

#### 5.1.1. Dataset

Experiments employ one public benchmark (MTL5) and one industrial dataset (Tencent3), tested across three training orders to assess task sequence sensitivity:

**MTL5 Benchmark**: A far-domain benchmark containing five text classification tasks across diverse domains. Selected tasks include:
- AGNews: 4-class topic classification
- Amazon: 5-class sentiment analysis
- DBPedia: 14-class topic classification
- Yahoo: 10-class Q&A

Base model: Llama 2

**Tencent3 Benchmark**: Real-world industrial dataset with 229,442 review samples from three business scenarios for content compliance review (binary classification):
- Task1: Review Channel
- Task2: Social Platform
- Task3: Official Content

Base model: Tencent Hunyuan

#### 5.1.2. Evaluation Metrics

Three continual learning evaluation dimensions:

1. **Accuracy (Acc)**: Primary performance indicator reflecting overall post-training performance. Higher values indicate superior comprehensive performance.

2. **Backward Transfer (BwT)**: Evaluates subsequent task impacts on previously learned tasks. Larger BwT (closer to or positive) indicates reduced catastrophic forgetting, crucial for knowledge retention.

3. **Forward Transfer (FwT)**: Measures prior task knowledge benefits to subsequent tasks. Larger FwT indicates more effective cross-task knowledge reuse and improved adaptation capacity.

#### 5.1.3. Compared Methods

- **Per-task FT**: Trains separate PEFT modules per task with no inter-task influence
- **Sequential FT-P**: Uses shared PEFT module trained according to predefined task sequence order
- **O-LoRA**: Learns tasks in orthogonal low-rank vector subspaces minimizing mutual interference
- **MoCL**: State-of-the-art method allocating dedicated PEFT modules per task with input-task similarity weights
- **MoE-CL**: Proposed adversarial MoE architecture using dedicated task LoRA experts and shared LoRA experts

#### 5.1.4. Implementation Details

All methods implemented in PyTorch within 8-GPU H20 environment. Grid search determined optimal hyperparameters:
- Learning rates: 0.0001-0.001 (0.0001 stepping)
- LoRA matrix ranks: {2, 4, 8, 16, 32}

Selected configurations for MTL5 and Tencent3:
- Learning rate: 0.0002
- LoRA matrix rank: 8
- Balance weight α: 0.1

Hidden representation dimension H matches FFN output layer size: 4096

### 5.2. Main Results

**Table 2: Tencent3 Benchmark Results (Tencent Hunyuan)**

| Metric | Order | Per-task FT | Sequential FT-P | O-LoRA | MoCL | MoE-CL |
|--------|-------|-------------|-----------------|--------|------|--------|
| Accuracy (↑) | Avg | 0.5334 | 0.6071±0.0220 | 0.5950±0.0122 | 0.5918±0.0293 | 0.6342±0.0074 |
| | 1 | 0.5334 | 0.6365 | 0.5901 | 0.5764 | 0.6446 |
| | 2 | 0.5334 | 0.6012 | 0.6118 | 0.6328 | 0.6280 |
| | 3 | 0.5334 | 0.5836 | 0.5832 | 0.5663 | 0.6299 |
| BwT (↓) | Avg | -0.1593 | -0.0300±0.0324 | -0.0223±0.0024 | -0.0485±0.0249 | -0.0349±0.0168 |
| FwT (↑) | Avg | 0.0562 | 0.0578±0.0287 | 0.0106±0.0078 | -0.0139±0.0052 | 0.0573±0.0159 |
| Latency (ms/sample) | - | 4.5ms | 9.4ms | 4.6ms | 4.7ms | 6.3ms |

**Table 3: MTL5 Benchmark Results (Llama 2)**

| Method | Avg | Order 1 | Order 2 | Order 3 |
|--------|-----|---------|---------|---------|
| Sequential FT-P | 26.7±0.91 | 28.8 | 27.4 | 26.6 |
| Per-task FT | 76.6±0.00 | 76.6 | 76.6 | 76.6 |
| O-LoRA | 76.1±0.52 | 76.8 | 75.7 | 75.7 |
| MoCL | 78.2±0.33 | 78.4 | 77.7 | 78.4 |
| MoE-CL | 80.5±1.50 | 81.1 | 81.9 | 78.4 |

**Key Observations**:

1. MoE-CL demonstrates "remarkable improvements in average accuracy" with minimal variance, highlighting superior generalization and robust stability across task complexities.
2. Sequential FT-P shows inconsistent cross-benchmark performance: worst MTL5 accuracy due to parameter-sharing exacerbating catastrophic forgetting on heterogeneous tasks; second-best Tencent3 performance on homogeneous content compliance tasks.
3. MoE-CL achieves fewer subsequent task negative effects than MoCL (BwT) with superior stability compared to Sequential FT-P.
4. Task sequence order significantly impacts performance. MoE-CL demonstrates superior cross-order stability through explicit shared/task-specific expert separation.
5. Inference latency: 6.3ms per sample (300-token average), "within the range imperceptible to humans and acceptable in real industrial scenarios."

### 5.3. Ablation Study

Removing the GAN component (w/o GAN variant) reveals GAN contribution:

- **Accuracy**: Higher overall task scores with GAN
- **Backward Transfer**: Less negative values (reduced new task interference on old tasks)
- **Forward Transfer**: Higher values (improved cross-task knowledge reuse)

The GAN-based architecture prevents catastrophic forgetting by localizing task-specific information within dedicated experts and suppressing irrelevant noise in shared experts.

### 5.4. Offline A/B Testing

**Table 4: Offline A/B Testing Results (Stripping Rate)**

| Method | Video Platform SUM | Social Platform SUM |
|--------|--------------------|---------------------|
| Online | 13.5% | 34.2% |
| MoE-CL | 28.8% | 37.4% |
| Gain | +15.3% | +3.2% |

MoE-CL achieved 15.3% improvement on Video Platform, directly reducing manual-review manpower costs.

## 6. Conclusion

MoE-CL represents a novel Mixture of LoRA Experts architecture effectively addressing catastrophic forgetting while enabling robust knowledge transfer during LLM continual instruction tuning. By integrating:
- Dedicated LoRA experts for task-specific knowledge retention
- Shared LoRA experts enhanced by GAN-based task-aware discriminators

MoE-CL balances prior task performance preservation with new task knowledge incorporation while fostering autonomous adaptation to sequential tasks without heavy external intervention.

## References

50 referenced works from 2014-2025 covering continual learning, parameter-efficient fine-tuning, adversarial learning, and self-evolving LLM methodologies.
