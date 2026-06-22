# Memp: Exploring Agent Procedural Memory

> arXiv: https://arxiv.org/abs/2508.06433 ｜ html: https://arxiv.org/html/2508.06433
> 2025-08

## 關鍵詞
procedural memory, Build-Retrieve-Update, trajectory vs script granularity, memory deprecation, cross-model transfer

## 對應 Layer / Roadmap 階段
- **Roadmap 主線最貼合（P1+P2+P4）** — Memp 的 **Build-Retrieve-Update 迴圈**＝本專案「蒸餾 → 召回 → manual-accept 飛輪更新」的學術對應，且雙粒度（trajectory/script）直接指導 Library 該存原始軌跡還是蒸餾腳本。

## 核心結論（帶實證數字）
1. **程序記憶顯著提升成功率並減步數**（Proceduralization vs 無記憶）：
   - GPT-4o **71.93%→79.94%**、步數 17.84→14.62；Claude 63.49%→65.46%；Qwen2.5-72B 56.57%→63.82%。
2. **跨模型可遷移**：GPT-4o 的程序記憶轉給 **Qwen2.5-14B** → +5% 完成率、−1.6 步（本專案本地小模型受惠的直接證據）。
3. **召回數 plateau ~5**：召回記憶越多越好，約 5 筆後 plateau、再多反降——top-k 設計參考（呼應 ExpRAG/RankRAG）。

## 方法機制拆解
- **Build**：雙粒度——**Trajectory**（逐步軌跡 verbatim）/ **Script**（從軌跡蒸餾的高階抽象）/ **Proceduralization**（兩者並用）。
- **Retrieve**：向量相似——Query-based（任務描述語意）/ AveFact（關鍵詞抽取+平均相似）。
- **Update**：`M(t+1)=U(M(t),E(t),τ)`＝`Add(new) ⊖ Del(obs) ⊕ Update(est)`；validation 過濾（只留成功）/ reflection（對失敗召回做錯誤校正）/ **deprecate 舊記憶**。

## 速查（綁本專案具體設計決策）
| Memp 機制 | 本專案落地 |
|---|---|
| **Build-Retrieve-Update 迴圈** | ＝本專案主線閉環；Update 的 Add/Del/**Deprecate** 給 Library 生命週期管理（過時模式要 deprecate，呼應 memory「project 型記憶定期清理」）。 |
| **雙粒度 trajectory/script** | Library 同時存「蒸餾腳本（泛化）+ 少量原始軌跡（具體）」；script 對應 AWM description [[paper-05]]。 |
| **跨模型遷移（→Qwen2.5-14B）** | 大模型蒸餾的程序記憶可餵本地小模型——支撐「雲端蒸餾、本地執行」。 |
| **validation 只留成功** | ＝manual-accept（Shiba 採納=成功訊號），但 Memp 靠 benchmark reward、本專案靠人工採納（更乾淨）。 |

## 侷限 / 與本專案差異
1. **只用向量相似召回、未納 BM25**：作者自承可加更精確的 lexical——正是本專案 sparse/FTS5 arm 的機會（[[paper-12]][[paper-19]]）。
2. **依賴明確 reward 訊號、無法判真實世界稀疏 reward 的成功**：**本專案 manual-accept 飛輪正補此洞**（Shiba 採納＝真實 reward）。
3. domain：ALFWorld/TravelPlanner；本專案 CLI 任務，proceduralization 的腳本格式需重設計。
