# shiba-fine-tuning-project 議題佇列（research topic queue）

> `weekly-digest` skill 與每週排程的**議題來源**。每次執行挑一個議題搜尋，標記後輪轉，下次換下一個。
> 議題隨情境演進——手動增刪，或用下方「刷新」從專案 memory 補新題。

## 輪轉規則（skill 依此選題）
1. 取 **狀態=pending** 中編號最小者；
2. 若無 pending，取 **「上次跑」最舊** 者（同日取編號最小）；
3. 預設**一次跑一個議題**（`$ARGUMENTS` 可指定議題編號或 N 個）；
4. 跑完把該題 狀態→`done`、上次跑→今天。

## Queue
| # | 議題 | 檢索關鍵字 | 狀態 | 上次跑 |
|---|------|-----------|------|--------|
| 1 | HyDE / query rewriting（召回改善） | hyde, hypothetical document embeddings, query rewriting for retrieval | done | 2026-06-27 |
| 2 | embedding index 去污染 / 召回多樣性 | retrieval diversity, near-duplicate embeddings, deduplication RAG corpus, paraphrase augmentation pitfalls | pending | — |
| 3 | Agentic RAG 召回 | agentic rag, self-rag, corrective rag, adaptive-rag | pending | — |
| 4 | embedding 召回 / reranker | bge-m3, reranker, rankrag, hybrid retrieval fusion | pending | — |
| 5 | 記憶系統 / procedural memory | agent memory, procedural memory, memgpt, a-mem, hipporag | pending | — |
| 6 | Verifier / 安全工具使用 | verified code generation, safe tool use, llm-as-judge calibration | pending | — |
| 7 | local LLM serving | ollama, mlx, llama.cpp, quantization, nvfp4 | pending | — |
| 8 | fine-tune（LoRA / MLX）| lora fine-tuning, mlx lora, instruction tuning small models | pending | — |
| 9 | harness engineering / self-improving agents | agent harness, self-improving agents, eval harness, base-assumption testing | pending | — |

## 刷新（seed / 補新題）
- 主來源：專案 memory 索引 `~/.claude/projects/<本專案>/memory/MEMORY.md`（Active Plan + topic 連結，反映當前在討論什麼）
- 輔來源：repo `docs/roadmap/*`、`CLAUDE.md` roadmap 表
- 做法：讀上述 → 挑出**佇列裡還沒有的新興主題** → 以新列**提議**新增（不自動覆寫既有題、不自動刪題）→ 交 Shiba 確認後寫入
