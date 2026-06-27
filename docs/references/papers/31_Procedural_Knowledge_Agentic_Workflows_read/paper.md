# Procedural Knowledge Improves Agentic LLM Workflows

> arXiv: https://arxiv.org/abs/2511.07568 ｜ 2025-11
> 作者: Vincent Hsiao, Mark Roberts, Leslie Smith
> （/html 暫無，內容取自 arxiv /abs 摘要級——數字僅相對比較、無逐項 benchmark）

## 關鍵詞
procedural knowledge, hierarchical task network (HTN), hand-coded vs LLM-created, small-model uplift, implicit planning

## 對應 Layer / Roadmap 階段
- **Roadmap 主線理論背書（P1）** — 本篇直接支持本專案重定向核心命題：「**用程序知識（Pattern Library）讓小模型勝過大模型，不靠權重（fine-tune）**」。

## 核心結論（帶實證數字）
1. **HTN 程序知識讓小模型超大模型**：hand-coded HTN 「可大幅提升 LLM agentic 表現」，使 **20B 或 70B 模型勝過大很多的 120B baseline**。
2. **hand-coded HTN > LLM-created HTN**：人工編的 HTN 增益顯著；LLM 自生成的 HTN 也有提升但較少。
3. ⚠ 摘要無逐項數字/benchmark 名，只有相對比較（要 driving 須回核全文）。

## 方法機制拆解
- 把程序知識形式化為 **HTN（hierarchical task network）**——任務階層分解的程序模板。
- 整合進 agentic LLM workflow，補「需隱性規劃」的任務。
- 兩種來源比較：hand-coded（人工專家）vs LLM-created。

## 速查（綁本專案具體設計決策）
| 本篇結論 | 本專案落地 |
|---|---|
| **程序知識讓小模型勝大模型** | **本專案「Pattern Library + 本地小模型」路線的直接背書**：不微調、靠 in-context 程序知識補能力（呼應重定向，見 [[project-finetune-yield-diagnosis]]）。 |
| **hand-coded HTN > LLM-created** | **支持 manual-accept 飛輪**：Shiba 親自策展/採納的模式（≈hand-coded）品質勝自動蒸餾（≈LLM-created）——印證「人工採納 > auto 啟發式」。 |
| **HTN 階層分解** | Pattern Library 可組織成階層任務模板（呼應 GoS 依賴圖 [[paper-27]] + Memp script [[paper-28]]），非扁平模式列表。 |

## 侷限 / 與本專案差異
1. **hand-coded HTN 成本高**：人工編 HTN 費工——本專案靠 Shiba 自然採納累積（低摩擦），非預先大量手編。
2. 摘要級分析、無逐項數字：採用前回核全文 benchmark。
3. domain：HTN 傳統用於明確規劃領域；本專案 CLI 任務的 HTN 模板化需設計（哪些指令任務可階層分解）。
