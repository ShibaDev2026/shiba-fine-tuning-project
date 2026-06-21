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

## 對 30/block 的意涵（binding constraint 雙因，未分離）
yield 卡關 = **(a) 有機對話配對不一致（exchange 邊界，連 D4）× (b) 嚴格本地 panel vs 8.0 高門檻**。
兩者疊加 → 真實配對 ~0% 自然過關。**證偽 refiner、排除雜訊**後，剩餘槓桿候選（皆 hypothesis、未證實）：
1. 修配對品質（B / D4）——但真實配對目前頂 6.0，修好配對能否到 8.0 未知；
2. 對有機資料調 approval 門檻（但與 D3「不放水」張力）；
3. 倚重 `user_accepted` 覆蓋路徑當主要 approve 信號（現 7+7 approved 即此來源）；
4. 給 gold seed 補 output 當合成訓練資料。
**A 以決定性負結果完成；捷徑（48 block=None）證實為 gold seed 紅鯡魚、非訓練資料。**
