# Query Rewriting for Retrieval-Augmented Large Language Models (Rewrite-Retrieve-Read)

> arXiv: https://arxiv.org/abs/2305.14283 ｜ ar5iv: https://ar5iv.labs.arxiv.org/html/2305.14283
> 作者: Xinbei Ma, Yeyun Gong, Pengcheng He, Hai Zhao, Nan Duan｜ 2023
> （數字取自 ar5iv 渲染）

## 關鍵詞
query rewriting, rewrite-retrieve-read, trainable rewriter, PPO, reinforcement learning, black-box reader feedback

## 對應 Layer / Roadmap 階段
- **Roadmap P2（Agentic 召回）+ Layer 1** — 本專案查詢是 Shiba 的口語/縮寫指令，與 Library 索引措辭有落差（「inevitably a gap between input text and needed knowledge」）。可訓練 rewriter 把查詢改寫對齊 Library，且 **RL reward 可用 Shiba 的 manual-accept 當訊號**。

## 核心結論（帶實證數字）
1. **可訓練 rewriter（T5-large 770M + PPO）一致勝過 retrieve-then-read 與 few-shot LLM rewriter**（EM/F1）：
   - **HotpotQA**：retrieve-then-read 30.47 → LLM rewriter 32.80 → **trainable rewriter 34.38**（F1 45.97）。
   - **AmbigNQ**：45.80 → 46.40 → **47.80**（F1 60.71）。
   - **PopQA**：43.20 → LLM rewriter 46.00（trainable 45.72，此題 few-shot 略勝）。
2. **MMLU**：ChatGPT reader +1~3% EM；Vicuna-13B reader +2~4% EM（弱 reader 改善更大）。

## 方法機制拆解
- **Rewrite-Retrieve-Read** 取代傳統 retrieve-then-read：先由 rewriter 改寫 query → 檢索 → reader 生成。
- **可訓練 rewriter**：T5-large（770M）初始化，用 **PPO** 訓練，當 black-box LLM reader 的前置適配器。
- **Reward**：EM + F1 + Hit 組合，加 **KL 散度正則**防 policy 漂移。
- **Reader**：ChatGPT（gpt-3.5-turbo）與 Vicuna-13B（凍結、黑箱）。

## 速查（綁本專案具體設計決策）
| Query Rewriting 機制 | 本專案落地 |
|---|---|
| **可訓練小 rewriter 適配黑箱 reader** | 本地小模型（Gemma/Qwen）當 rewriter，把 Shiba 口語指令改寫對齊 Library 措辭，下游本地 reader 凍結——符合「不微調主模型」路線。 |
| **RL reward = reader 回饋** | **manual-accept 飛輪 = 天然 reward 訊號**：Shiba 採納改寫後召回的 pattern → +reward；回退 Claude → −reward。比論文的 EM/Hit 更貼真實效用（避開 auto 採納陷阱，見 [[project-finetune-yield-diagnosis]]）。 |
| **KL 正則防漂移** | rewriter 訓練必備護欄，避免改寫成 Library 偏好的怪異措辭而脫離 Shiba 原意。 |
| **弱 reader 改善更大** | 本地模型（< 雲端 reader）正是「弱 reader」，query rewriting 對本專案 EV 更高。 |

## 侷限 / 與本專案差異
1. **需要訓練 rewriter**：與本專案「先零訓練」路線略衝突——可先用 few-shot LLM rewriter（論文證實也有增益，HotpotQA 32.80）當零訓練版，待飛輪累積足夠 reward 樣本再考慮 PPO。
2. **RL 需足量回饋樣本**：13% 採納天花板下，manual-accept 樣本累積慢，PPO 訓練的資料前置與 fine-tune 同樣受 yield 限制。
3. domain：開放域 QA；本專案是指令檢索，改寫目標不同（對齊指令模式而非問句）。
4. 與 HyDE（[[paper-09]]）互補：HyDE 生成假設文件、本法改寫查詢，兩者都在縮 query-document gap，可 A/B 比較選一。
