# MemGPT: Towards LLMs as Operating Systems

> arXiv: https://arxiv.org/abs/2310.08560 ｜ ar5iv: https://ar5iv.labs.arxiv.org/html/2310.08560
> 作者: Charles Packer, Sarah Wooders, Kevin Lin, Vivian Fang, Shishir G. Patil, Ion Stoica, Joseph E. Gonzalez｜ 2023

## 關鍵詞
OS-inspired hierarchical memory, main vs external context, self-directed paging, function calls, event-driven control

## 對應 Layer / Roadmap 階段
- **Roadmap P2（in-context 執行）+ P3** — MemGPT 把 LLM context 視為「RAM（主脈絡）」、外部儲存視為「disk（外部脈絡）」，模型用 function call **自主決定何時把資料 page in/out**。對應本專案「Library（外部）↔ 本地模型 context（主脈絡）」的工作集管理。

## 核心結論（帶實證數字）
1. **Deep Memory Retrieval（對話一致性）**：GPT-4 baseline 32.1% → **MemGPT+GPT-4 92.5%**。
2. **Document QA**：文件數增加時 MemGPT 維持穩定，固定 context baseline 因截斷退化。
3. **Nested Key-Value 檢索**：MemGPT 跨 0–4 巢狀層維持穩定，baseline 3 層即 0%。

## 方法機制拆解
- **階層記憶**：main context（受限 LLM window）vs external context（無限儲存）。
- **自主分頁**：「用 function call，agent 可讀寫外部資料源、改自己的 context、決定何時回覆」。
- **事件驅動**：user 訊息/系統警示/排程任務觸發推論；function chaining 支援多步檢索。

## 速查（綁本專案具體設計決策）
| MemGPT 機制 | 本專案落地 |
|---|---|
| **main vs external context 分層** | Library（external）只在需要時 page 進本地模型 context（main）——直接服務 context 預算 + 13% 天花板。 |
| **自主分頁 via function call** | 本地模型可主動決定「召回更多 / 夠了」（呼應 Search-o1 uncertainty-triggered [[paper-22]]、Adaptive-RAG [[paper-16]]）。 |
| **事件驅動控制** | 對應本專案 hook 架構（UserPromptSubmit/Stop 觸發召回）。 |

## 侷限 / 與本專案差異
1. **retriever 依賴**：「常在窮盡 retriever 前就停止翻頁」，embedding 排序有雜訊時受限——本專案召回品質（cosine-bound）同樣是上游瓶頸。
2. **小模型 function calling 弱**：GPT-3.5 表現顯著退化——**本專案本地 Qwen/GLM 的 function calling 能力需實測**，是 MemGPT 式自主分頁的前提。
3. **複雜度高**：需精細 prompt engineering 管理 token。
4. domain：對話/文件 QA；本專案取其「分層記憶 + 自主分頁」骨架。
