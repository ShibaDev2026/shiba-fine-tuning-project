# DICE: Dynamic In-Context Example Selection

> arXiv: https://arxiv.org/abs/2507.23554 ｜ html: https://arxiv.org/html/2507.23554
> 2025｜ 收錄賽道：A（framing=P1 transferability 軸）+ B（framing=P2 example selection），本檔合併兩視角。

## 關鍵詞
in-context example selection, transferable knowledge, causal decomposition, information-theoretic criterion, InfoNCE, training-free plug-in, stepwise vs taskwise, ReAct/Reflexion/LATS

## 對應 Layer / Roadmap 階段
- **Roadmap P1（Pattern Library）— transferability framing** — DICE 用「可遷移性」軸在 cosine 之上做二次篩選，正交於相似度，能剔除會誤導的 spurious 模式。對應 Library 收錄/排序時「哪些模式真的可遷移到當前任務」。
- **Roadmap P2（Agentic 召回 + in-context 執行）— example selection framing** — in-context 執行時動態挑對 demonstration（stepwise）餵本地模型，避免 spurious 範例帶歪本地 Qwen。
- **Layer 1 RAG** — 直擊本專案痛點：**golden set 是 cosine-bound、無法評「打敗 cosine 的召回法」**；DICE 是「在 cosine 召回之上加正交篩選軸」的具體解。

---

## 核心結論（帶實證數字）

1. **在三種 agent 框架上一致增益（zero-training plug-in）**：
   - **HotpotQA**（多跳推理，500 題，EM）：ReAct 32.1% → **41.4%（+9.3pt）**；Reflexion 51.6% → 58.9%（+7.3）；LATS 63.3% → 71.4%（+8.1）。
   - **Webshop**（互動購物，500 任務）：ReAct 成功率 28.0% → 35.0%（+7.0）。
   - **AlfWorld**（embodied，134）：ReAct 57.5% → 67.9%（+10.4）；Reflexion 74.6% → 82.1%（+7.5）。

2. **動態（stepwise）勝靜態（taskwise）**：HotpotQA stepwise **41.4%** vs taskwise 36.3% — 證明「每步重選範例」比「任務起點選一次」好（與 ExpRAG dynamic 結論部分呼應，見 [[paper-06]]）。

3. **贏過相似度型與訓練型 selector，且免訓練**：DICE 41.4% > **KATE（kNN-based）34.7%** > **EPR（trained selector）36.5%**（Table 4）——關鍵：**不需訓練就贏過要訓練的 EPR**。

4. **效率：少範例打平多範例**：「DICE 用 3 個精選範例 = 標準 ICL 用 6 個隨機範例」的效能 → 直接省 context budget。

---

## 方法機制拆解

### Transferable Knowledge 分解（核心）
把一個 demonstration 的知識用因果分析拆兩塊：
- **TK（Transferable Knowledge）**：真正與當前決策相關、有益的資訊。
- **ϵ_D, ϵ_t（non-transferable）**：任務專屬 / spurious 知識，會引入不該有的相關性（帶歪模型）。

### 選擇準則（Eq. 1）
```
arg min_{d_i ∈ D} J_i,  J_i = I(d_i; TK_{d_i}) − β·I(TK_{d_i}; A_t)
```
- 懲罰「攜帶過多任務專屬細節」（第一項），鼓勵「TK 與下一步動作 A_t 互資訊最大」（第二項）。
- 即：選**其可遷移知識最能預測下一步正確動作**的範例，而非表面最像的。

### 實作元件
- **Knowledge Retriever = gemma-2-2b-it**（預訓練小模型）抽 TK 表徵 — 小到可本地常駐。
- **InfoNCE 下界**估互資訊。
- 仍用 **cosine** 算 `I(TK_d, TK_t)`，但作用在「抽取後的 TK 表徵」上，**非 raw demonstration**。

### 與 cosine 召回的本質差異
| | cosine 召回 | DICE |
|---|---|---|
| 比對對象 | raw 輸入表面表徵 | 抽取後的 TK 表徵 |
| 準則 | 表面相似度 | 資訊論 + 因果（濾 spurious） |
| 時機 | 靜態（任務起點） | 動態（每步） |

---

## 速查（綁本專案具體設計決策）

| DICE 機制 | 本專案落地 |
|---|---|
| **TK 軸正交於 cosine、可在其上二次篩選** | **直接破解本專案 golden set cosine-bound 困局**（memory: reranker 因 gt 抽自 bi-encoder 無法贏 cosine）：DICE 不跟 cosine 比排序，而是換軸——「可遷移性」是 cosine 測不出的維度，繞開「grader=author 陷阱」。 |
| **濾掉 spurious / 任務專屬細節** | 本專案蒸餾的指令模式常帶具體 repo 路徑/檔名（spurious），DICE 的 TK 抽取 = 把這些 down-weight，只留可遷移的指令結構——呼應 AWM 的參數化（[[paper-05]]）但用資訊論而非規則。 |
| **gemma-2-2b-it 當 retriever** | 本專案本地棧已有 Gemma，可當 in-context 選擇器；2B 級小模型常駐成本低，符合「本地 in-context 執行」約束。 |
| **3 精選 = 6 隨機（效率）** | 直接服務 **13% 採納天花板 + context 上限**：少而精的注入既省 context 又維持效能，比無腦擴 top-k（ExpRAG 證會爆 context）更貼本專案約束。 |
| **stepwise > taskwise** | P2 in-context 執行可考慮每步重選，但⚠ 需權衡 ExpRAG 的 ScienceWorld −9.3 教訓（dynamic 任務相依）。 |
| **免訓練贏過 trained EPR** | 符合本專案「先 RAG/in-context、fine-tune 降 P5」路線：不訓練就能提升選範例品質。 |

---

## 侷限 / 與本專案差異
1. **需預建「成功軌跡池」**：DICE 從成功 demonstration 池選——這正是本專案 **Pattern Library 要先建起來**的前提（空池 DICE 無從選，呼應 ExpRAG 空 index 崩盤）。P1 EV gate 仍是前置。
2. **作者只實作單一 instantiation**：未試可訓練 encoder 捕捉 latent TK，留未來。本專案採用時即用其 training-free 版本。
3. **domain 差異**：實驗在 HotpotQA/Webshop/AlfWorld；本專案是 CLI/code agent，TK 抽取的 prompt 需針對「指令模式」重設計。
4. **TK 抽取依賴 retriever 模型品質**：gemma-2-2b-it 對中文指令語料的 TK 抽取能力需本地實測（base-assumption-first：採用前先小實驗驗中文場景有效）。
