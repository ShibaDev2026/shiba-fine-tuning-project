# RepoCoder: Repository-Level Code Completion Through Iterative Retrieval and Generation

> arXiv: https://arxiv.org/abs/2303.12570 ｜ ar5iv: https://ar5iv.labs.arxiv.org/html/2303.12570 ｜ EMNLP 2023
> 作者: Fengji Zhang, Bei Chen, Yue Zhang, Jacky Keung, Jin Liu, Daoguang Zan, Yi Mao, Jian-Guang Lou, Weizhu Chen｜ 2023

## 關鍵詞
iterative retrieval-generation, generated-code-as-query, repository-level completion, RepoEval, propose-retrieve-refine

## 對應 Layer / Roadmap 階段
- **Roadmap P2（Agentic 召回，程式碼場景）** — RepoCoder 用「模型生成的程式碼當下一輪查詢回頭再檢索」，是 propose-retrieve-refine 的具體招式、零重訓——對應本專案 CLI/code 場景的迭代召回（與 HyDE [[paper-09]] 同理但迭代）。

## 核心結論（帶實證數字）
1. **迭代召回勝單次**（RepoEval，line + API 補全）：EM 較 In-File baseline +**>10%**、Edit Similarity +**>8%**；GPT-3.5-Turbo line completion **55.31% EM vs In-File 40.56%**。
2. **Iteration 2 穩定勝單次 RAG**。

## 方法機制拆解
- 第一輪用未完成程式碼當 query 檢索 repo 片段。
- **第 i 輪（i>1）用上一輪模型預測 Y^(i−1) 構造新 query** 再檢索——「未完成程式碼本身難代表要補什麼」，用預測回饋 bootstrap 更好的 context。

## 速查（綁本專案具體設計決策）
| RepoCoder 機制 | 本專案落地 |
|---|---|
| **生成物當查詢回頭再檢索** | 本地模型先草擬指令/程式碼 → 用草擬當 query 再召回 Library（HyDE 的迭代版）——補短查詢召回涵蓋率。 |
| **iteration 2 即顯著增益** | 不需多輪，2 輪即划算，控成本。 |
| **propose-retrieve-refine** | 與 Verifier 的 propose-check 結構共振。 |

## 侷限 / 與本專案差異
1. **★低重複度→增益小**：「repo 內程式碼重複少時 RepoCoder 提升不顯著」——**直接呼應本專案 P1 EV gate**：指令模式重複頻率低，迭代召回也救不了（同 ExpRAG 空 index [[paper-06]]）。
2. **iteration 數不穩 + 延遲**：多輪檢索-生成成本，real-time 受限。
3. domain：repo 程式碼補全；本專案 CLI 指令場景部分可遷移（檔案/repo 操作），但「程式碼補全」≠「指令模式召回」，招式（生成物當 query）可借、評測不可直接套。
