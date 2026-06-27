# Agent Workflow Memory (AWM)

> arXiv: https://arxiv.org/abs/2409.07429 ｜ html: https://arxiv.org/html/2409.07429
> 作者: Zora Zhiruo Wang, Jiayuan Mao, Daniel Fried, Graham Neubig（CMU / MIT）｜ 2024

## 關鍵詞
workflow induction, agent memory, reusable routine, selective injection, web navigation agent, offline/online memory, Mind2Web, WebArena

## 對應 Layer / Roadmap 階段
- **Roadmap P1（Pattern Library + manual-accept 飛輪）** — AWM 是本專案 P1 的**學術原型**：從 agent 軌跡歸納「可重用例程（workflow）」→ 存入 memory → 選擇性注入引導後續任務。對應本專案「對話軌跡 →蒸餾驗證過的指令模式 → Pattern Library」。
- **Roadmap P2（Agentic 召回 + in-context 執行）** — AWM 的「選擇性注入 workflow 到 agent memory，再 in-context 生成動作」幾乎等同本專案「RAG 召回模式 → 本地 Qwen/GLM in-context 代理執行」。
- **Layer 1 RAG（Pattern Library 索引層）** — AWM 用輕量檢索把 workflow 拼進 prompt，呼應 bge-m3 + FTS5 召回 + 選擇性注入避免 context 爆掉。

---

## 核心結論（帶實證數字）

1. **歸納可重用 workflow（而非堆原始軌跡）在兩大 web 導航 benchmark 顯著贏 baseline**：
   - **WebArena**（GPT-4，812 任務，5 站台）：總成功率 **35.5%**，較 BrowserGym baseline 23.5% **相對 +51.1%**（絕對 +12.0 pt），且**步數更少**（5.9 vs ax-tree 7.9）。
   - **Mind2Web**（GPT-4，offline）：Step SR **45.1%**（MindAct baseline 36.2%）、Element Acc **50.6%**（baseline 41.6%）、Task SR **4.8%**（baseline 2.0%）。GPT-3.5 上 Step SR **34.6%**（Synapse 30.6%）。
   - 論文宣稱兩 benchmark「相對成功率分別提升 **24.6%** 與 **51.1%**」(Mind2Web / WebArena)。

2. **無人工監督卻贏人工撰寫 workflow**：AWM 35.5% 超過 **SteP（人工撰寫 workflow）的 33.0%**，相對 +7.6%，且「不為 WebArena 特製、零人工監督」。

3. **跨分布泛化是最大亮點，分布越遠增益越大**（Mind2Web 三 split，GPT-4）：
   - Cross-task Step SR: 36.2% → **45.1%**（+8.9 pt）
   - Cross-website: 30.1% → **33.9%**（+3.8 pt）
   - **Cross-domain: 18.6% → 35.5%**（+16.9 pt，最大增益）— online AWM 在最陌生領域增益最高。

4. **LM-based 歸納 > rule-based**：WebArena 持平（35.5% vs 35.6%），但 Mind2Web Step SR 45.1% vs 43.4%（+2.8 margin），因 LM 能做**範例特定值的抽象化**（如把 "dry cat food" 抽成 `{product-name}`）。

5. **品質指標佐證 workflow 不冗餘**：WebArena utility rate **0.94**（高度可用）、function overlap 僅 **0.08**（幾乎無重複）、每站台僅歸納 7.3–7.4 條 workflow。

---

## 方法機制拆解

### Workflow 的構成
每條 workflow `w = (d, P^d)`：
- **`d`**：自然語言描述（這條例程做什麼）。
- **`P^d`**：一連串 (observation, action, reasoning) 步驟構成的軌跡片段。
- 「Each workflow represents a goal with a common routine extracted from available action trajectories」——抽的是**跨多任務重複出現的子序列**（至少 2 步），且**把非固定元素參數化**（輸入文字、按鈕字串 → 描述性變數名）以提升泛化。

### 歸納模組（Induction）
- LM-based induction `I(ℰ) → 𝒲 = {(d_j, P_j^d)}`：餵一批經驗軌跡 `ℰ`，由 LM 抽出「跨任務重複的動作子集」。
- Prompt 明確指示：「find the repetitive subset of actions across multiple tasks…each workflow should have at least two steps…represent non-fixed elements with descriptive variable names」。

### Offline vs Online 雙模式
- **AWM_offline**：訓練時把某站台**所有訓練樣本**一次餵 LM 建一組靜態 workflow，測試時固定不變。
- **AWM_online**：**無訓練資料**也能跑。把測試 query 串流處理，每跑完一個 task 就做 `induce → integrate → utilize` 迴圈——用評判器 `L_eval(e^t) ∈ {0,1}` 判斷該軌跡是否成功，成功才歸納並 `M_t + {w^t} → M_{t+1}` 寫回 memory。**經驗隨任務累積、能力隨用越強**。

### 記憶整合與注入
- 注入即 prompt 拼接：`M + 𝒲 → M_w`，agent 以 `L(q, M_w, o_i) → a` 生成動作（query + memory含workflow + 觀測 → 動作）。
- 注入是 **selective**（只把相關 workflow 拼進 memory），非全量堆疊——這是控制 context 長度的關鍵。

---

## 速查（綁本專案具體設計決策）

| AWM 機制 | 本專案 P1/P2 對應落地 |
|---|---|
| **歸納 reusable routine 而非存原始軌跡** | Pattern Library 存**蒸餾後的指令模式**，不堆原始 Claude Code 對話。一條 pattern = 描述 `d`（中文：這個指令模式解什麼）+ 步驟序列（驗證過的指令/工具呼叫鏈）。 |
| **非固定值參數化**（`dry cat food`→`{product-name}`） | 蒸餾 workflow 時把專案路徑、檔名、分支名抽成 `{repo_path}` `{branch}` `{pr_id}` 等變數槽——提升跨任務召回命中率，避免「逐字具體」的死路（呼應 memory 記載的 RAG macro-exchange 教訓）。 |
| **selective injection（非全量）** | 召回層只注入 top-k 高相關 pattern（bge-m3 cosine + FTS5），**直接呼應 13% 採納天花板**：本地只接高信心模式、其餘優雅回退 Claude；同時避免 in-context window 爆炸（AWM 證實「合併 NL+HTML 反降 -0.8~-1.6 SR，因 context 變長」）。 |
| **offline + online 雙模式** | offline=從歷史對話批次預建 Library；online=Shiba 當下採納即時 `M_t+{w}→M_{t+1}` 寫回——**直接支撐 manual-accept 飛輪**（刻意採納 = +1 gold）。 |
| **`L_eval` 成功才寫回 memory** | 對應本專案 P3 Verifier（執行前安全閘）+ manual-accept：**只有驗證/採納通過的軌跡才進 Library**，AWM 用啟發式 `L_eval`，本專案用 Shiba 刻意採納（更高品質訊號，避開 auto-acceptance 陷阱——見 [[project-finetune-yield-diagnosis]] 的 auto vs manual 採納教訓）。 |
| **LM-based 抽象 > rule-based** | Pattern 蒸餾用 LM（本地 Qwen/GLM 或召回時的師父）做語意抽象化，而非純規則切割——AWM 證實抽象化帶 +2.8 SR。 |
| **online 在陌生分布增益最大（+16.9 cross-domain）** | 飛輪價值最高在**新指令類型**：當 Shiba 開始一個沒見過的任務族，online 累積最能補上能力——支撐「持續累積驗證模式」的長期 EV。 |

**P1 飛輪設計直接採用 AWM 閉環**：對話軌跡 →[LM 歸納+參數化] Pattern →[L_eval / Shiba 採納] 寫回 Library →[bge-m3 selective top-k] 注入 → 本地 in-context 執行 → 結果回饋。

---

## 侷限 / 與本專案差異

1. **AWM 用啟發式 `L_eval` 判成功；本專案用 Shiba 刻意採納當 gold**——後者品質訊號更乾淨。本專案 [[project-finetune-yield-diagnosis]] 已實證 auto-acceptance（「下一則含同意詞」啟發式）會灌出假採納（109 筆全 auto、manual 僅 3），故**不照搬 AWM 的自動 L_eval，改 manual-accept**。

2. **環境動態變化時 workflow 會失效**：論文自承（Fig 7 訂機票例）「workflow actions do not always lead to task success」當環境狀態改變，需「real-time state access / dynamic execution loops」。對應本專案 → **Verifier（P3）的 propose-check-execute 不可省**：召回的 pattern 是提案不是保證，執行前須驗。

3. **agent 對新動作類型有抗性**：擴展 action space（AWM_AS）時 agent 僅 18.5% 任務真的用 workflow action，增益僅 +1.3 SR。啟示：**注入格式要貼近模型既有習慣**（本專案注入「指令模式」而非新工具 API，摩擦更低）。

4. **domain 落差**：AWM 任務是 web 導航（DOM/HTML 觀測、點擊/輸入動作）；本專案是 CLI/code agent（bash/git/檔案操作）。歸納範式（induce→integrate→utilize）可移植，但**觀測/動作表徵需重設計**（本專案無 DOM，改 shell 指令鏈 + 工具呼叫）。

5. **檢索是輕量字串匹配；本專案用 bge-m3 語意召回**——AWM 證明即使輕量檢索也夠（utility 0.94），但本專案中文 + 語意變體多，dense 召回更穩（呼應 paper 03 HippoRAG 方向）。

6. **Task SR 絕對值仍低**（Mind2Web 4.8%、WebArena 35.5%）——workflow memory 是**增益放大器非萬靈丹**，底層 agent 能力仍是天花板。對本專案的誠實 gate：Pattern Library 提升的是「已會的任務做更穩」，不是「不會的任務變會」。
