# Memory for Autonomous LLM Agents: Mechanisms, Evaluation, and Emerging Frontiers (Survey)

> arXiv: https://arxiv.org/abs/2603.07670
> 作者: Pengfei Du｜ 2026-03
> ⚠ 後截止日論文（2026-03），本分析以 arxiv 全文內容為準。

## 關鍵詞
write-manage-read, memory taxonomy, temporal scope, control policy, evaluation gaps, forgetting

## 對應 Layer / Roadmap 階段
- **賽道 D 地圖（全線）** — 提供 agent 記憶的統一框架與詞彙，用來**定位本專案 Pattern Library 在記憶設計空間的座標**，並其評估 gap 直接呼應本專案 golden set 困局。

## 核心結論（框架 + 分類）
### Write-Manage-Read 迴圈
每步：讀記憶 ℛ → policy π 產動作 → 更新 𝒰。**𝒰 非單純 append**——含摘要、去重、優先評分、矛盾解決、選擇性刪除。

### 三正交分類軸
| 軸 | 類別 |
|---|---|
| **Temporal Scope** | working / episodic / **semantic** / **procedural** |
| **Representational Substrate** | context-text / **vector-indexed** / **structured(SQL/KG)** / **executable(code/tools)** |
| **Control Policy** | heuristic（hard-coded top-k）/ **prompted self-control** / learned(RL) |

### 評估 gap（呼應本專案）
- 「classical retrieval metrics fall short」for agentic（＝本專案 golden set cosine-bound 的更廣版）。
- forgetting 評估「largely unexplored」；跨 session coherence underexplored。
- benchmark：LoCoMo/MemBench/MemoryAgentBench/MemoryArena（高分 LoCoMo 模型在 MemoryArena 掉到 40–60%）。

## 速查（綁本專案具體設計決策）
| Survey 框架 | 本專案定位 |
|---|---|
| **temporal scope** | Pattern Library = **procedural + semantic memory**（可重用指令模式 + 抽象知識）。 |
| **substrate** | 本專案 = vector(bge-m3) + structured(SQLite) + executable(指令)——多 substrate 混合。 |
| **control policy** | 本專案目前 = **heuristic**（top-k + 規則 gate）→ roadmap 往 **prompted self-control**（模型決定召回）演進（呼應 Self-RAG/Adaptive-RAG/MemGPT）。 |
| **𝒰 非 append（去重/矛盾/刪除）** | manual-accept 飛輪的 Update 要含去重+矛盾解決+deprecate（呼應 Memp [[paper-28]]）。 |
| **評估 gap：classical metrics fall short** | 背書「不能只用 cosine recall 評」；需 task-effectiveness + memory-quality + efficiency + governance 四層（接 SoK 分層 [[paper-26]]）。 |

## 侷限 / 與本專案差異
1. Survey 無實證；價值在框架詞彙與評估清單。
2. 偏通用 agent 記憶；本專案 CLI 特化，executable substrate 比重高。
3. 「learning to forget」「principled consolidation」前沿對應本專案 memory consolidation 機制。
