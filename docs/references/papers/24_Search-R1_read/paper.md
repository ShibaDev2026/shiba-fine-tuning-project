# Search-R1: Training LLMs to Reason and Leverage Search Engines with Reinforcement Learning

> arXiv: https://arxiv.org/abs/2503.09516 ｜ html: https://arxiv.org/html/2503.09516
> 作者: Bowen Jin, Hansi Zeng, Zhenrui Yue, Jinsung Yoon, Sercan Arik, Dong Wang, Hamed Zamani, Jiawei Han｜ 2025

## 關鍵詞
RL for retrieval, PPO/GRPO, retrieved-token masking, interleaved search, outcome reward, Qwen2.5

## 對應 Layer / Roadmap 階段
- **Roadmap P5（fine-tune 後期）+ P2** — RL 教模型**自主在推理中交錯搜尋**,且 base 正是本專案的 **Qwen2.5-3B/7B**——P5 真要訓練「會召回的本地模型」時的直接配方。

## 核心結論（帶實證數字）
1. **RL（PPO/GRPO）優化交錯搜尋的 rollout**,把搜尋引擎當環境一部分。
2. **Retrieved-token masking**：對召回 token 做 loss masking,policy gradient 只算 LLM 自產 token——穩定訓練的關鍵 trick。
3. **多輪結構**：`<search></search>` 發查詢、`<information></information>` 回結果、`<think></think>` 推理。
4. **簡單 outcome reward**：只用最終答案 EM,無 neural reward model、無 format reward。
5. **數字**（base = Qwen2.5-3B/7B）：7B **+24%** 相對勝 RAG baseline、3B +20%、14B +41%（附錄）。benchmark：NQ/TriviaQA/PopQA/HotpotQA/2Wiki/Musique/Bamboogle。

## 速查（綁本專案具體設計決策）
| Search-R1 機制 | 本專案落地 |
|---|---|
| **base = Qwen2.5-3B/7B（本專案 training base）** | P5 若訓「會召回的本地模型」,此為直接配方,模型相容。 |
| **outcome reward 簡單（只 EM）** | 對應 manual-accept 飛輪：採納成功=reward,無需複雜 reward model;但本專案 reward 是「Shiba 採納」非 EM。 |
| **retrieved-token masking** | 訓練時不對召回的 Pattern token 算 loss——本專案 in-context 召回模式訓練的必要 trick。 |
| **多輪 search/think 結構** | Agentic 召回的 prompt 結構範本（與 IRCoT/Self-Ask 同向但 RL 內化）。 |

## 侷限 / 與本專案差異
1. **需 RL 訓練**：與「先零訓練、fine-tune 降 P5」一致——P2 階段不採,留 P5。
2. 搜尋限 Wikipedia;本專案召回源是 Pattern Library,環境不同。
3. RL 需大量 rollout + reward 樣本;本專案採納樣本稀缺（13% 天花板）→ RL 前置受 yield 限制（同 fine-tune 困局 [[project-finetune-yield-diagnosis]]）。
