# Self-RAG: Learning to Retrieve, Generate, and Critique through Self-Reflection

> arXiv: https://arxiv.org/abs/2310.11511 ｜ html: https://arxiv.org/html/2310.11511v1
> 作者: Akari Asai, Zeqiu Wu, Yizhong Wang, Avirup Sil, Hannaneh Hajishirzi｜ 2023（ICLR 2024 Oral）

## 關鍵詞
reflection tokens, adaptive retrieval, self-critique, on-demand retrieval, IsRel/IsSup/IsUse, controllable generation

## 對應 Layer / Roadmap 階段
- **Roadmap P2（Agentic 召回）+ P3（Verifier）+ Layer 0 路由** — Self-RAG 的「Retrieve token 決定要不要檢索」對應本專案 L0 路由 + 已建的查詢側 gate（`is_short_query`/`is_low_signal_query`）；「IsSup/IsUse 自我批判」對應 P3 Verifier 的 propose-check。

## 核心結論（帶實證數字）
1. **Self-RAG 7B/13B 全面勝 Llama2-chat 與標準 RAG**（accuracy）：
   - PopQA 54.9/55.8、TriviaQA 66.4/69.3、PubHealth 72.4/74.5、ARC-Challenge 67.3/73.1、Biography FactScore 81.2/80.2。
   - 「非專有 LM 中所有任務最佳」。
2. **勝 ChatGPT**：PubHealth、PopQA、biography、ASQA fluency 均超越 ChatGPT；唯 citation precision ChatGPT 領先（70.3 vs 65.1）。
3. **adaptive 檢索**：按需決定要不要檢索，而非無腦固定取 K 篇——降雜訊、省 context。

## 方法機制拆解
### 四種 reflection token（Table 1）
- **Retrieve**：{yes, no, continue} — 要不要檢索。
- **IsRel**：{relevant, irrelevant} — 檢索段落是否相關。
- **IsSup**：{fully / partially / no support} — 段落是否支撐生成內容。
- **IsUse**：{5,4,3,2,1} — 整體輸出有用度。
### 訓練
1. critic 模型生成 reflection token 標註訓練資料；
2. generator 在標註資料上訓練，學會同時產 regular token + reflection token → 推論期可控。

## 速查（綁本專案具體設計決策）
| Self-RAG 機制 | 本專案落地 |
|---|---|
| **Retrieve token（要不要檢索）** | 對應本專案已建的查詢側 gate（[[project-rag-injection-transparency]] 的 `is_short_query`/`is_low_signal_query`/`is_system_meta_query`）——本專案用「結構性規則」做 adaptive retrieval 決策，Self-RAG 用「學到的 token」。可借鏡：把 gate 從規則升級為輕量學習信號。 |
| **IsRel（段落相關性）** | 召回後過濾低相關 pattern，呼應 DICE 的 spurious 濾除（[[paper-07]]）。 |
| **IsSup（支撐度）+ IsUse** | **P3 Verifier 的核心**：召回的 pattern 是否真支撐當前任務、本地模型用它產出的提案有用度——propose-check-execute 的 check 階段可直接用 IsSup/IsUse 形式。 |
| **可控生成（推論期）** | 本地模型在 in-context 執行時自評，低 IsUse 則優雅回退 Claude——直接服務 13% 採納天花板的「高信心才接手」。 |

## 侷限 / 與本專案差異
1. **需訓練 critic + generator**：本專案路線是不微調主模型 → 可先用 prompt-based 自評（讓本地模型輸出 IsSup/IsUse 結構化判斷）當零訓練版，避開訓練前置。
2. **citation precision 輸給 ChatGPT**：自我批判非萬靈丹。
3. **小模型有時勝 13B**（因傾向更短、精確接地的輸出）——啟示本專案本地模型不必追求大，精確接地更重要。
4. domain：開放域 QA/長文生成；本專案是指令執行，reflection token 的語義需映射到「指令是否安全/正確」（接 P3 Verifier）。
