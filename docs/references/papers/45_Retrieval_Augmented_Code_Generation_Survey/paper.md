# Retrieval-Augmented Code Generation: A Survey with Focus on Repository-Level Approaches

> arXiv: https://arxiv.org/abs/2510.04905
> 作者: Yicheng Tao, Yuante Li, Yao Qin, Yepang Liu｜ 2025-10（v3 2026-05）

## 關鍵詞
RACG taxonomy, control regime (passive/active/agentic), graph-based code retrieval, adaptive retrieval policy, necessity boundary

## 對應 Layer / Roadmap 階段
- **賽道 D 地圖（程式碼檢索）+ Roadmap P2** — 提供 code-retrieval 分類，其「control regime」分級對應本專案召回強度選擇（被動→主動→agentic），與 roadmap P0→P2 演進同構。

## 核心結論（分類，非 benchmark）
### Control Regime（自主程度三級）
- **Level 0 非 agent**：靜態 pipeline，單次 retrieval+generation 無回饋。
- **Level 1 部分 agent**：迭代迴圈，中間輸出（程式碼/執行訊號）精煉後續決策，但無自主規劃（＝RepoCoder [[paper-36]]）。
- **Level 2 全自主**：目標導向 + 規劃 + 多步推理 + 工具互動。
### Retrieval Substrate
- **非圖**：扁平文字（BM25/embedding/hybrid）。
- **圖**：edge=Contain/Import/Inherit/Invoke/Data Flow/Control Flow；node=Directory/Module/Class/Function/Line。
### 核心技術
- **retrieval content（檢索什麼）**：query 重組、AST chunking、API 動態擴充。
- **retrieval strategy（何時/如何）**：adaptive policy（**LinUCB bandit**、necessity-aware filtering）、Shapley 選擇、static analysis、**command-driven context（LLM 指揮終端探索）**。

## 速查（綁本專案具體設計決策）
| Survey 概念 | 本專案落地 |
|---|---|
| **control regime 三級** | 本專案 roadmap = Level 0（現 hook 召回）→ Level 1（草擬回饋再召回，RepoCoder 式）→ Level 2（Agentic）。明確的演進階梯。 |
| **necessity-aware / LinUCB adaptive 召回** | 升級本專案查詢側 gate（is_short_query 等）為學習式「該不該召回」（呼應 Adaptive-RAG [[paper-16]]）。 |
| **command-driven context（LLM 指揮終端）** | 與本專案 CLI agent 場景高度契合——LLM 主動探索終端取脈絡。 |
| **graph edge 類型（Invoke/Data Flow）** | 若 Library 建圖，可借鏡程式碼依賴邊型別。 |

## 侷限 / 與本專案差異
1. Survey 無實證；價值在分類詞彙。
2. **necessity boundary 挑戰**：「何時 retrieval 必要 vs long-context 足夠」——本專案本地模型 context 有限，retrieval 仍必要，但仍須量。
3. graph 建構依賴語言特定 parser（可移植性差）——本專案 bash/混合語言場景受限。
