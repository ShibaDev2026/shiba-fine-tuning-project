# shiba-fine-tuning-project 議題佇列（research topic queue）

> `weekly-digest` skill 與每週排程的**議題來源**。每次執行挑一個議題搜尋，標記後輪轉，下次換下一個。
> 議題隨情境演進——手動增刪，或用下方「刷新」從專案 memory 補新題。

## 輪轉規則（skill 依此選題）
1. 取 **狀態=pending** 中編號最小者；
2. 若無 pending，取 **「上次跑」最舊** 者（同日取編號最小）；
3. 預設**一次跑一個議題**（`$ARGUMENTS` 可指定議題編號或 N 個）；
4. 跑完把該題 狀態→`done`、上次跑→今天。

## Queue（2026-07-03 改組：四題對準現行主軸四軌 author/curate/eval/route）
| # | 議題（對應軌） | 檢索關鍵字 | 狀態 | 上次跑 |
|---|------|-----------|------|--------|
| 1 | 新模型發布追蹤（eval 軌：新 frontier/本地模型 → 重跑個人評測集 `experiments/2026-07-03_personal_eval_v1/`） | new llm release, claude, qwen, gemma, open weights model release, coding benchmark | pending | — |
| 2 | Claude Code harness / skills 實務（author 軌：手寫 skill 的模式與案例） | claude code skills, agent harness, slash commands, hooks workflow automation, agentic coding practices | pending | — |
| 3 | local LLM serving（route 軌：本地窄車道模型運維） | ollama, mlx, llama.cpp, quantization, nvfp4, speculative decoding | pending | — |
| 4 | 個人 AI 記憶 / 指令檔 curation 實務（curate 軌：CLAUDE.md/memory 維護法） | claude.md best practices, agent memory curation, instruction file maintenance, context engineering | pending | — |

## 已除役（2026-07-03，主線收束 author/curate/eval/route 後死線題不再蒐集）
> 除役依據：召回線 A-vs-B 實測 FAIL 結案（2026-07-03）、fine-tune 廢止、Pattern Library/Verifier 廢止擱置。若日後重啟對應線，重開新題重搜（情報會貶值，不預囤）。

| 原# | 議題 | 除役原因 | 最後跑 |
|-----|------|---------|--------|
| 1 | HyDE / query rewriting | 召回線結案（HyDE 前置 gate 未跑即失去標的） | 2026-06-27 |
| 2 | embedding index 去污染 / 召回多樣性 | 召回線結案（本期產出留作日後施工圖） | 2026-07-03 |
| 3 | Agentic RAG 召回 | 召回線結案 | — |
| 4 | embedding 召回 / reranker | 召回線結案＋reranker PoC 已擱置 | — |
| 5 | 記憶系統 / procedural memory | 併入新 #4（縮窄為 curation 實務，系統型記憶研究與主線無接點） | — |
| 6 | Verifier / 安全工具使用 | P3 隨 P2 廢止擱置 | — |
| 8 | fine-tune（LoRA / MLX） | fine-tune 廢止 | — |
| 9 | harness engineering / self-improving agents | 併入新 #2（縮窄為 Claude Code skills/harness 實務） | — |

## 刷新（seed / 補新題）
- 主來源：專案 memory 索引 `~/.claude/projects/<本專案>/memory/MEMORY.md`（Active Plan + topic 連結，反映當前在討論什麼）
- 輔來源：repo `docs/roadmap/*`、`CLAUDE.md` roadmap 表
- 做法：讀上述 → 挑出**佇列裡還沒有的新興主題** → 以新列**提議**新增（不自動覆寫既有題、不自動刪題）→ 交 Shiba 確認後寫入
