# A-MEM: Agentic Memory for LLM Agents

> arXiv: https://arxiv.org/abs/2502.12110 ｜ html: https://arxiv.org/html/2502.12110
> 2025-02

## 關鍵詞
Zettelkasten, atomic notes, automatic tagging, dynamic link generation, memory evolution, token efficiency

## 對應 Layer / Roadmap 階段
- **Roadmap P1（Pattern Library 結構化）+ P2** — A-MEM 用 Zettelkasten 原子筆記把離散記憶組織成可導航互聯結構，對應本專案把零散指令模式組織成有 tag、有連結、會演化的 Library。

## 核心結論（帶實證數字）
1. **多跳與時序問答勝 MemGPT/LoCoMo baseline**（LoCoMo, GPT-4o-mini, F1）：Multi-Hop **27.02** vs MemGPT 26.65；**Temporal 45.85 vs 25.52**（時序推理大勝）。
2. **token 效率 85–93% 降**：~1,200 token vs 16,900——召回精準、不塞整個記憶庫。
3. DialSim F1 3.45（較 LoCoMo 2.55 +35%）。

## 方法機制拆解
- **Note Construction**：每筆記含原始內容、時間戳、**LLM 生成的 keywords/tags**、脈絡描述、連結記憶 + embedding。
- **Link Generation**：新記憶自動算相似度 → prompt LLM 分析潛在連結 → 建邊。
- **Memory Evolution**：新記憶加入時，**既有記憶的脈絡表徵/屬性可被觸發更新** → 網路持續精煉理解。
- **Retrieval**：cosine top-k。

## 速查（綁本專案具體設計決策）
| A-MEM 機制 | 本專案落地 |
|---|---|
| **原子筆記 + 自動 tag/keyword** | Library 每個指令模式存成原子筆記 + LLM 自動標 tag（event_type/工具/領域），免人工分類。 |
| **動態連結生成** | 指令模式間自動建關聯（類似 GoS 的圖 [[paper-27]] 但用相似度而非 schema）；對應本專案 memory 的 `[[name]]` 互聯機制。 |
| **memory evolution（既有記憶被更新）** | manual-accept 飛輪不只 +1 新模式，還可觸發既有模式精煉——比純 append 高階。 |
| **token 85–93% 降** | 精準召回服務 13% 天花板 + context 預算。 |

## 侷限 / 與本專案差異
1. **記憶組織品質受底層 LLM 能力影響**：本地小模型做 tagging/link 品質需實測。
2. **純文字、無多模態**：本專案 CLI 場景文字為主，影響小。
3. domain：對話記憶（LoCoMo）；本專案是指令模式，note 結構需對應（指令/工具鏈/前後置）。
4. 與 GoS（[[paper-27]]）取捨：A-MEM 用相似度連結（輕、無 schema）；GoS 用 typed 依賴圖（重、可回溯前置）——本專案可先 A-MEM 式輕連結，依賴關係明確再升 GoS。
