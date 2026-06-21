# Refiner 槓桿 no-regret 實驗 — 結果（2026-06-21）

## 動機
Yield 診斷定位 fine-tuning 真瓶頸＝抽出的 instruction→output 配對品質（非雜訊、非 eligibility）。
block1/block2 各僅 7 approved（需 30），且全是 `user_accepted` 強制覆蓋的低分樣本。
專案已有 `refiner_service.py`（Qwen 改寫不自足 instruction 成自包含版 `refined_instruction`，
judge 用 `COALESCE(refined_instruction, instruction)` 評）。本實驗驗：refiner 是否真能抬分過門檻。

## 方法
對 4 個真實失敗樣本實際呼叫 `refine_sample`（REFINER_MODEL=qwen3.6:35b-a3b-nvfp4，本地 Ollama）。
只讀 DB、不寫回。樣本涵蓋失敗模式②（不自足 NL）與①（雜訊 instruction）。

## 結果

| id | 原 score | input | refiner 產出 | 判定 |
|----|---------|-------|------------|------|
| 25 | 6.0 rej | 有 | 冗長真問題→漂亮自包含技術問題+expected_answer | ✓ 對「有上下文模糊 NL」有效 |
| 47 | 3.5 app | 有 | 「繼續 C.1」→自包含 commit/memory 指令 | ⚠ instruction 修好但 **output 是 GPU 檢查、仍不匹配** |
| 32 | 1.0 rej | 空 | 雜訊 `/model`→字面幻覺「說明 /model 指令」、與 output(grep) 不符 | ✗ 無上下文→幻覺不一致 |
| 52 | 1.0 rej | 有 | 雜訊 `/model`→**從 input 捏造** docker-compose commit 驗證問題 | ⚠⚠ 虛構訓練對（資料完整性風險）|

## 結論（部分推翻先驗）
1. **refiner 對「有 input 上下文的模糊真 NL」確實有效**（id=25/47 instruction 顯著改善）。
2. **但 refiner 不修 instruction↔output 不匹配**（id=47：改好 instruction，output 仍是無關的 GPU 指令）
   ——這是上游 **exchange 邊界 / 配對**問題（與 D4 branch over-merge 相關），refiner 結構上救不了。
3. **無 input 上下文時（53/61 v2 樣本是單 exchange、input 空）→ refiner 幻覺**（id=32 字面瞎猜）。
4. **⚠ 新風險：refiner 會把雜訊 instruction 捏造成貌似合理但虛構的訓練對**（id=52）——judge 看 coherent
   就可能放行，等於把幻覺資料餵進訓練。**這是跑滿 refiner 前必須讓 Shiba 定奪的資料完整性問題。**

## 決定性 re-grade（regrade.py，本地 3-judge panel，門檻 8.0）
對 5 個低分 real-NL v2 樣本，比較「原 instruction」vs「refined instruction」(output 不動) 的 panel 分數：

| id | blk | 原 re-grade | refined grade | Δ | 原 instruction（碎片性質）|
|----|-----|------------|--------------|---|------|
| 25 | 2 | 3.0 | 3.0 | +0.00 | 真問題但冗長 |
| 48 | 2 | 4.0 | 2.5 | **-1.50** | `2. 不處理`（選項回覆碎片）|
| 47 | 1 | 3.5 | 3.0 | -0.50 | `繼續 C.1…`（output 是無關 GPU 指令）|
| 46 | 1 | 3.0 | 2.0 | -1.00 | `各RC建議使用的/model與/effort`（碎片）|
| 51 | 2 | 3.0 | 2.5 | -0.50 | `1-2`（選項回覆碎片）|

**結論：0/5 跨過門檻 8.0；refined 與原 instruction 分數差落在 judge 雜訊內（不抬分）。**

> ⚠ judge 變異需誠實標注：id=25 同一 (instruction,output) DB 原存 6.0、本次 re-grade 3.0
> ——3 分擺盪、輸入零變化。故 Δ(−0.5~−1.5) 落在雜訊內，**不宣稱「refine 必然扣分」**；
> 站得住的是「refine 不抬分」+ 具體幻覺（id=48 `2.不處理`→虛構段落、id=51 `1-2`→虛構路徑問題）。

## 最終結論（refiner 證偽為 yield 槓桿）
1. **refine instruction 不把分數抬向門檻** → refiner **不是** fine-tuning yield 的槓桿。
2. **真因＝instruction↔output 本質不匹配**：原 instruction 多是對話**回覆碎片**（`2.不處理`/`1-2`/`各RC…`，
   意義全靠前文），output 是助理對整段對話的回應。配對在 **exchange 邊界**就壞了。
3. refine 把碎片改寫成「貌似合理但虛構」的問題（id=48/51 幻覺）→ 資料完整性風險。
4. **base-assumption-first 驗證生效**：用 ~$0 / 20 分鐘證偽，**避免**建「雜訊 gate + 跑滿 refiner」
   的無用 pipeline。雜訊 gate 也無獨立價值（judge 已濾雜訊、非 binding constraint）。

## confound 調查（advisor 指出，已查 → 修正先前 over-claim）
疑慮：8.0 門檻是否本地裁判（2026-06-16 切換）根本給不出來？**查 score≥8 樣本的內容後發現：**
- 全部 48 個 score≥8 是 **`gatekeeper_golden_samples`**（Tier B 48 題親撰 gold）：`output` 全空、
  `session_id`/`source_exchange_ids` 皆 None、同一刻批次插入、分數是 **seed 填的非 judge 評**。
- **真實抽取配對（有 output + src_ex）只有 13 個，最高 6.0、avg 2.54、≥8 為 0、連 ≥6.67 都 0。**
- → **修正**：先前「本地裁判會給好配對 9+」**站不住**（那是 seed）。正確結論是：**本地 panel 切換後，
  沒有任何真實配對拿到過 approval 門檻 8.0。** 呼應 D3「panel 自然 approve 僅 1.4%」＝strict by design。

## 後續 D4 配對設計調查（2026-06-21，panel_ceiling.py + real_selfcontained.py）
為設計 D4 配對品質修法，做兩個決定性實驗：

**panel_ceiling.py — 分離「配對問題 vs 門檻問題」**：把 gatekeeper_golden_samples 的「手撰
instruction + expected_output」（已知良好配對）丟現行本地 panel 評 → **4/5 過 8.0（avg 8.5-9.0）**。
→ **本地 panel 確實獎勵好配對、8.0 可達；瓶頸 100% 是配對品質、非門檻校準。** refiner 失敗
（只修 instruction、不修 output）也由此解釋：gold 是 instruction＋output 兩邊都好才 9 分。

**[已撤回] real_selfcontained.py — 抽錯母體**（advisor 揪出）：誤抽 61 個*已抽出* v2 樣本（那個「幾乎沒跑」
的 pipeline 產物，43/9707 覆蓋），只 1 個符合 → 量到的是 extraction 選擇、非語料。據此推「語料缺 clean pair」
是 population mismatch 的錯誤結論，已刪該腳本。

**corpus_selfcontained.py — 修正母體（從 9716 eligible exchanges 直接抽）**：
- **乾淨自包含 instruction = 716 個**（>> 目標 60）→ **instruction 不缺、非語料稀缺、非前提受限。**
- 但真實乾淨對 + **真實 final output** 只 **1/8 過 8.0**（ex=4154 清楚問答 8.5✓；其餘 7 個 instruction 乾淨
  但 output 是對話中段分析/「已記錄」/給選項/岔題 → 2-4）。

## D4 配對設計的真問題：output 形狀（精準、tractable、非前提）
- exchange 切割器正確、panel 門檻可達、**自包含 instruction 不缺（716）** → 唯一卡點＝**真實 output 不是答案形狀**。
- `final_assistant_message_id` 在真實多輪協作裡常是中段備註/澄清/岔題，不是對開頭 instruction 的乾淨回答。
- **設計方向＝pair-coherence-gated extraction**：只留「乾淨自包含 instruction × output 真正回答它」的對。
  yield 概算：716 × ~12.5%(1/8) ≈ 90 對 ≈ 45/block（若均分）→ **plausibly 夠 30/block**（n=8 小、率區間寬，待擴樣）。
- 排除：純過濾(A) yield 夠但需加 output 維度；重構/合成(B/C) 偏離「學真實互動」+ fabrication 風險。

## Step 1 yield gate（step1_yield.py，n=50）— 方案 A **gate 失敗**
per-exchange 路徑（每乾淨自包含 exchange 自成一對，instruction/output 同 exchange）yield 驗證：
- 通過率 6/50 = **12%**（坐實先前 12.5%）。
- **致命：82% 重複**——716 乾淨自包含 instruction **unique 只有 132**。穩健估算：
  **132 unique × ~12% ≈ ~16 approved 總計 vs 需 60（30×2）**，且偏 block1。
  （不報 per-block 3/1 精度——「乾淨自包含」是中文關鍵詞啟發式：英文盲、排除 >200 字完整任務、
  漏掉 361「皆非」桶，低估約 2-3×；即使 3× 修正仍遠不足且偏 block1。）
- **結論：方案 A gate 失敗、不建**。716×12%≈87 是 82% 重複灌水的假象。
  base-assumption-first（先驗 yield 再建）擋下「ship 出只產 ~6 樣本的無用 pipeline」。
- **未測替代路徑**：`_extract_path_b`（error_repair：失敗工具→修復，錯誤訊息即 context、
  by construction 連貫自包含）是另一條 block1 yield 來源，本輪未評 → 下一個該 probe 的對象。

## ★ 主要發現（比方案 A 失敗更大）：語料被 D4 灌水 ~6.8×
- **9731 eligible exchange 只有 1429 distinct user_message_id → 每則訊息平均出現在 6.8 個 exchange。**
- 鐵證：某重複 instruction＝8 exchange / 1 user_message_id / 跨 8 branch（同一訊息被 branch 複製 8 份）。
- 主因＝**branch over-merge（D4）**：DAG 斷鏈 + branch membership 錯亂把同一訊息複製到多 branch。
- **意涵**：所有把語料當「~9700 exchange」的計數（yield / RAG / 一切）都 ~5-7× 灌水；真實 unique
  基礎遠更小。**D4 不是 pairing-input 的小麻煩，是整個資料基礎的上游前提**——修好前連「手上有多少」
  都數不準。這把「B/D4 日後做」重定為：**D4 可能是任何 yield 工作的前置條件，非並列選項。**
- ⚠ 不下「前提已死」結論：只測了 per-exchange clean-Q&A 一條路；error_repair 未測；去重後真實
  harvest 上限待 D4 修好後才能準確量。

## error_repair 路徑 probe（er_regrade.py，本地 panel 重評）— 也失敗
- 既有 55 個 error_repair 中 53 是 pre-cutover 舊付費裁判評的 → 本地 panel 重評 6 個求公平。
- **0/6 過 8.0**（avg 4.7-6.7），且本地分數≈舊付費分數（6.7→6.7/5.7→5.7）→ 非 provenance 假象。
- instruction 是 by-construction 自包含模板（好），但 **output 是凌亂分析**（「## Gemini 503 排查
  結論」「密碼被安全分類器擋下」）→ 非答案形狀 → ≤6.7。母體上限僅 ~63 有錯 session。

## ★★ 收斂結論：三條 harvest 路徑撞同一面牆＝output 不是答案形狀
| 路徑 | 本地 panel 上限 | 牆 |
|------|---------------|----|
| per-exchange clean Q&A | ≤6 | output 對話中段非答案 |
| error_repair | ≤6.7 | output 凌亂分析 |
| refiner（改 instruction）| 無提升 | 只修 instruction |
| **gold（手撰 in+out）對照** | **8.5-9 ✓** | 判官沒壞、門檻可達 |

**根因（3 路徑 + gold 對照收斂、非 n=1 臆測）**：真實助理 output 是帶專案脈絡的多段分析，不是乾淨
答案。instruction 怎麼修都無效，牆在 output 側。**harvest 真實對話到 30/block 在現行 8.0 門檻下不可行。**

## 選項 2（user_accepted）gate 量測（2026-06-21，Shiba 定「先2後1+D4」）
router_decisions.user_accepted=1 的 (prompt→local_output) 配對＝Shiba 採納的本地回應：
- **109 非測試 accepted 決策**；instruction 還原（hash 比對 sha256[:12]）**74/109=68%**（32% prompt
  不在 messages，疑 RAG 改寫/專案名 fallback）；unique 74 對。
- **output=local_output 是乾淨結構化答案**（「結論：…理由：…」）+ **user_accepted 強制 approved
  →繞過 judge 與 output 形狀牆**（唯一做到的路徑）；零 fabrication、對齊「學真實互動」前提。
- ⚠ **當前 volume 短**：74 unique、block1≈11-15/block2≈6-10（neither 53 多為碎片「1.同意」/system-reminder）
  → **現在 <30/block、無法立即觸發訓練**。
- ⚠ `local_output` 存檔截斷 500 字元（不完整）；instruction 含碎片/雜訊需過濾。
- **與前三條的差別**：#2 不是撞牆，是 volume 不足、會隨使用累積。

### ★ #2 前提崩塌（advisor load-bearing check）：user_accepted 全是 auto-heuristic 非 manual
- 查 `acceptance_source`：那 109 筆 **全部 'auto'**；全 DB 僅 3 'manual'（且無 output/測試）。
- `user_accepted=1` 由 `infer_acceptance_from_text` 啟發式設（下一則訊息含「同意/好/ok」→ 自動推定），
  **非 Shiba 對 local output 品質的判斷**。「1.同意 2.同意」被採納正因字面含「同意」（循環誤判：
  Shiba 同意的是下一步、非認可 output）。
- **結論：#2「倚重 Shiba 採納當 gold」前提在現有資料上不存在**（manual≈0）。force-approve 這些＝
  拿 auto 弱標籤訓練，正是 judge 該擋的。**不建 user_accepted backfill。**
- **#2 要成真需前置**：改 workflow 讓 Shiba **刻意 manual 採納**好的 local output（→ 真 gold →
  force-approve 才有意義）。這是 UX/機制改動，非抽取路徑；且仍需累積 volume。

## 30/block 的戰略選項（Shiba 決策）
1. **output-reshaping**：LLM 把真實分析 output 重格式化成乾淨答案（保留真實內容、比 refiner 改
   instruction 的幻覺風險低，因 output 本含正解）→ 最有望的 harvest 救援。
2. **倚重 user_accepted**：現有 approved 全是 user_accepted 覆蓋（~3-6 分）；Shiba 手動採納當訓練信號、繞過 judge。
3. **手撰/seed gold**（如 48 Tier B）：可靠 9 分但人工、非 harvest。
4. **接受 L3 維持 gated 實驗**（D1 已決的預設）。
- 正交前置：**D4 修好**才能準確量任何 yield（語料 ~6.8× 灌水）。

## 對 30/block 的意涵（binding constraint 雙因，未分離）
yield 卡關 = **(a) 有機對話配對不一致（exchange 邊界，連 D4）× (b) 嚴格本地 panel vs 8.0 高門檻**。
兩者疊加 → 真實配對 ~0% 自然過關。**證偽 refiner、排除雜訊**後，剩餘槓桿候選（皆 hypothesis、未證實）：
1. 修配對品質（B / D4）——但真實配對目前頂 6.0，修好配對能否到 8.0 未知；
2. 對有機資料調 approval 門檻（但與 D3「不放水」張力）；
3. 倚重 `user_accepted` 覆蓋路徑當主要 approve 信號（現 7+7 approved 即此來源）；
4. 給 gold seed 補 output 當合成訓練資料。
**A 以決定性負結果完成；捷徑（48 block=None）證實為 gold seed 紅鯡魚、非訓練資料。**
