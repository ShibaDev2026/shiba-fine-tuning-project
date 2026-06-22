# GraphFlow: A Graph-Based Workflow Management for Efficient LLM-Agent Serving

> arXiv: https://arxiv.org/abs/2605.22566 ｜ html: https://arxiv.org/html/2605.22566 ｜ ICML 2026
> 作者: Ao Li, Shangpeng Yang, Fahao Chen, Tianheng Xu, Peng Li, Zhou Su｜ 2026-05
> ⚠ 後截止日論文（2026-05），本分析以 arxiv 全文內容為準。

## 關鍵詞
wGraph, atomic operation nodes, task-adaptive subgraph, topology-aware KV-cache reuse, LLM-agent serving

## 對應 Layer / Roadmap 階段
- **Roadmap P2/P4（serving 效率）** — GraphFlow 解「反覆執行的 agent workflow 怎麼省算」：原子操作合併成圖 + **KV-cache 跨 workflow 重用**。對應本專案「高頻重複指令任務」的本地執行成本（直連 P1 EV——重複才有重用價值）。

## 核心結論（帶實證數字）
1. **wGraph 統一原子操作**：把多 workflow 的 tool call/推理步/驗證模組合併成單一 DAG（顯式依賴）。
2. **task-adaptive 生成**：GNN encoder + MLP decoder 動態合成任務子圖（非取固定模板）；加 virtual task node 注入 query 語意。
3. **topology-aware KV-cache**：每操作 KV 拆「context-independent base + sparse topology-aware residual」→ 跨 workflow 重複操作免重複儲存。
4. **數字**：準確 +~4.95pt；記憶體 **~4×** 降；P90 延遲 12.25s vs baseline 14.06s（**Qwen-2.5-7B**＝本專案 base）。

## 速查（綁本專案具體設計決策）
| GraphFlow 機制 | 本專案落地 |
|---|---|
| **KV-cache 跨重複執行重用** | **直接服務 P1 EV**：指令任務重複頻率高才有重用價值；高頻模式的 KV 重用省本地推論——量化「重複」的回報。 |
| **原子操作合併成圖** | Library 的指令步可合併成共享原子節點（呼應 GoS [[paper-27]]）。 |
| **Qwen-2.5-7B 實測** | 本專案 base 上的 serving 數字可直接參考。 |

## 侷限 / 與本專案差異
1. **罕見路徑 fall back on-the-fly KV**：path pruning 靠執行統計，非典型序列受影響——對應本專案低頻模式無重用紅利。
2. 偏 serving/系統優化，非召回品質——P4 工程化階段才用。
3. domain：通用 agent serving；本專案 CLI workflow 的原子操作切分需設計（連 D4 exchange 邊界）。
