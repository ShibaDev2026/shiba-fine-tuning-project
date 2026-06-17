# Tier B 較難批次 21 gold — 本地三裁判獨立複評（補 canonical 之外缺口）

> **承接**：batch-1 複評（`2026-06-17-tierB-batch1-judge-reeval.md`）只驗證 6 筆 **canonical** 基礎題，
> 未驗證較難 / 刻意糾正前提的親撰 gold。本輪補這個缺口。
> **範圍**：architecture(108–114) + code_gen(92–98) + knowledge_qa(116–122) = **21 筆**（Shiba 指定納入 knowledge_qa）。
> **重點觀察**：4 筆「我刻意糾正題目錯誤前提」的判斷題（sid 113 / 116 / 121 / 122）會不會被「期待直接回答」的裁判扣分。
> **方法**：同 batch-1，`_call_openai_compat` 直呼避開 `output[:500]` 截斷、`max_tokens=2048`、thinking 關閉、judge-outer 序評（LM Studio JIT 僅 2 次換模）、單筆例外→score=None 不靜默吞票；**不改 gold / 不 freeze / 不 commit（繼續觀望）**。

## 判讀基準（呼叫前預先承諾，沿用 batch-1）
- 基準 = **Tier A 同一本地裁判分布（max 6.67）**，非我的自評 9.0–9.5（不同校準）。
- ✅ PASS：21 筆 panel-mean 全 ≥ 7.5（清楚分離於 6.67）。
- ⚠ 邊際：任一落 (6.67, 7.5)。
- ❌ 重新校準：任一 panel-mean ≤ 6.67（落入 Tier A 區間）。

## 結果

| 分層 | n | panel-mean | min | max | vs Tier A(6.67) |
|------|--:|----------:|----:|----:|----------------:|
| architecture | 7 | 9.33 | 9.33 | 9.33 | +2.66 |
| code_gen | 7 | 9.33 | 9.33 | 9.33 | +2.66 |
| knowledge_qa | 7 | 9.29 | 9.00 | 9.33 | +2.62 |
| **ALL** | **21** | **9.32** | **9.00** | **9.33** | **+2.65** |

裁判校準（看 rubber-stamp / 區辨度）：

| 裁判 | n | mean | 唯一值 | 角色 |
|------|--:|-----:|--------|------|
| Local Qwen3.5-35B-A3B | 21 | 8.95 | {8.0, 9.0} | **唯一有區辨**（僅 sid 121 給 8.0，其餘全 9.0） |
| Local GLM-4.7-Flash | 21 | 9.00 | {9.0} | 常數 9.0 |
| Local Gemma-4-e4b | 21 | 10.00 | {10.0} | 常數 10.0（天花板釘死，近橡皮圖章） |

**Gate**：clear(≥7.5)=21 / marginal=0 / below=0 / failed votes=0 → **VERDICT = ✅ PASS**

全 63 票中唯一偏離值：Qwen 在 sid 121 給 8.0（詳見下）。

## 判定：✅ PASS（但飽和）— 證明「floor-clearance / provenance」，**不**證明「逐筆品質 / 排序」

PASS 的可主張範圍要誠實切窄，否則是迎合性解讀：

**✅ 證明了（破循環的核心）**：grader=author 的循環疑慮是「我自撰又自評 9.0–9.5，標準是否自肥」。
本複評讓**同一批**把 Tier A 真實 model-output 評到 max 6.67 的本地裁判，獨立評我的 gold → 9.32（+2.65）。
獨立裁判在 grader≠author 下仍把我的 gold 評得遠高於 6.67，**循環在「越過地板」這個意義上已破**，與 batch-1 一致、且擴及較難批次。

> **+2.65 不可全歸功於撰寫品質（沿用 batch-1 confound #3，不可丟）**：6.67 是 Tier A **真實 session 雜訊捕獲**的地板，非「乾淨任務的 model floor」；
> 9.32 是「curated 乾淨題庫 + 親撰完整答案」。落差混了 (a) 撰寫品質 與 (b) 乾淨資料 vs 雜訊資料兩個因子。
> 誠實結論：本複評證「**從題庫親撰的 gold 越過地板**」，**不**證「我的內容普遍比 model 內容高 2–3 分」。

**❌ 沒證明（飽和的代價）**：panel 在頂端壓縮（21 筆有 20 筆 panel-mean=9.33、1 筆=9.00），
**無法解析 9.0–9.5 的細緻品質差異、也無法給出正確排序**。換言之：
- 一份**較弱**的 gold 同樣會通過這道 gate——gate ≥7.5 對「Claude 親撰內容」近乎恆真（near-tautological）。
- 本複評是**provenance / 地板驗證**，不是**逐筆品質驗證**。要逐筆排序需要更利的裁判或 pairwise，本 panel 做不到。

## 4 筆前提糾正：被裁判**理由背書**，非被扣分

動機問題（裁判會不會因為「答非所問、先糾正前提」而扣分）**實證為否**：

| sid | 糾正內容 | panel | Qwen | GLM | Gemma |
|----:|---------|------:|----:|----:|------:|
| 113 | MoE 省的是算力非記憶體；有限記憶體靠 mmap/offload | 9.33 | 9.0 | 9.0 | 10.0 |
| 116 | `--mmap` 預設開、非主角；可行性=量化+mmap+MoE 稀疏 | 9.33 | 9.0 | 9.0 | 10.0 |
| 121 | Gemma3 無 thinking 模式→`think:false` 無作用；關 thinking 參數隨 runtime 不同 | 9.00 | 8.0 | 9.0 | 10.0 |
| 122 | ada-002 是雲端 API 非本地→比較不對稱；中文 bge-m3 更佳 | 9.33 | 9.0 | 9.0 | 10.0 |

- **premise-fix mean 9.25　vs　一般題 9.33　→ 差值 −0.08。**
  這個 −0.08 **不承重**：在頂端飽和的 panel 下，它只表達「沒有被懲罰」，不表達「品質略低」。
  真正的訊號在**理由**——Qwen（唯一有區辨的裁判）把糾正本身點名為**優點**：
  - sid 113：「成功釐清 MoE 節省的是計算量而非記憶體的原則，並補充 mmap/量化等關鍵機制」
  - sid 116：「成功釐清 --mmap、量化與 MoE 稀疏性在低記憶體環境下的協同機制，邏輯嚴謹」
  - sid 122：「精準澄清了 Ada-002 無法本地部署的前提」
  → 裁判不但沒因「先糾正前提」扣分，反而把糾正視為技術深度。動機顧慮排除。

## sid 121：唯一的事實爭點 — claim vs counter-claim + 外部查證

這是全 63 票唯一偏離值，也是本輪**資訊量最高**的一票（panel 唯一一次浮現事實爭議）：

- **我的 gold（claim）**：Gemma 3 沒有原生 thinking 模式，故 `think:false` 對它是 no-op；關 thinking 的參數隨 runtime 不同（Ollama `think:false` vs LM Studio `reasoning_effort`）。
- **Qwen 8.0（counter-claim）**：「對 Gemma3 是否原生支援思考模式…可能存在技術細節上的不確定性（Gemma 2/3 通常需特定配置或版本才支援 thinking），導致部分論述略顯武斷。」

**外部查證（不自我背書，2026-06 web search）**：
- Google AI for Developers 官方文件與多來源一致：**Gemma 3 無原生 thinking/reasoning，模型直接作答**；內建 thinking 模式（`<|think|>` token）是 **Gemma 4** 才加入的特性。
- 社群可用 fine-tuning（Unsloth GRPO）**外加**推理能力到 Gemma 3，但那是再訓練、**非 stock 模型的開關**。

**裁定：gold 正確，Qwen 屬過度保守（over-caution），非抓到真錯。**
Qwen 的 hedge「需特定配置/版本」勉強碰到「社群可 fine-tune 外加」這個與本專案部署無關的旁支；
但專案實際情境是「stock `gemma3:4b` 經 Ollama、設 `think:false`」——stock 模型確實無 thinking 模式，旗標確為 no-op，gold 站得住。

> **方法論收穫**：飽和的 panel 仍能**偶發**浮現一個事實爭點（這就是 sid 121），但**無法自行裁定**——
> 需外部查證才能 resolve。這同時是 panel 的價值（會 flag）與其上限（不能 adjudicate）。
> → 量產時，凡裁判給出**差異化票 + 具體事實質疑**者，一律外部查證，不靠 panel 多數決放行。

## 批判性檢視（飽和 caveats，避免迎合性解讀）

1. **Gemma 釘死天花板、GLM 釘死 9.0 → 只有 Qwen 有區辨。** Gemma-4-e4b 全 10.0、GLM 全 9.0，
   對「逐筆排序」零資訊。可信的差異化全來自 Qwen，而 Qwen 在 21 筆裡只動了 1 筆。
2. **去掉 Gemma 仍 PASS。** Qwen mean=8.95、GLM mean=9.00，皆遠高於 6.67 → 結論不靠最弱的 Gemma 撐。
3. **Qwen 的 9.0 是「具體扣 1 分」而非套版。** 一般題的扣分理由都點名具體缺口，證明它在讀內容：
   - sid 94：「實作正確…但輸出混入非程式碼說明文字，略影響純代碼純粹性」
   - sid 112：「技術要點準確…但未含程式碼或具體數據引用，略少於完美」
   - sid 119：「清晰區分記憶體/速度/品質…但缺具體數據佐證使完美度略減」
   → 飽和是真的，但裁判不是橡皮圖章；它有一致 rubric、會刻意保留第 10 分。
4. **驗證邊界。** 本複評證「grader≠author 下，較難批次的 gold 仍越過 Tier A 地板」→ 缺口補上；
   但**未**證：(i) 21 筆細緻品質排序；(ii) gold 的事實正確性（panel 飽和，弱 gold 同樣會過，唯一靠外部查證擋下的是 sid 121 類事實爭點）。
5. **覆蓋率（已補滿 48/48）**：batch-1（6 canonical，每 type 各 1）+ 本輪 21（arch/code_gen/knowledge_qa 全批）+ 補一輪 21（git_ops/terminal_ops/debugging 各餘 7）= **48 / 48 gold 全獨立複評**。
   **更正**：原稿此處誤稱有 fine_tuning_ops gold——題庫實際只涵蓋 **6 個 event_type × 8 筆 = 48**，無 fine_tuning_ops，故無該型「缺口」。
   補一輪同樣 ✅ PASS（21/21 panel=9.33），且**更扁**——Qwen 本輪零偏離（全 9.0），再次印證頂端飽和（區辨力來自題目本身而非 gold 差異）。

## 後續處置（2026-06-17 Shiba 裁定「1.可 2.補一輪 3.可」，已執行 + 驗證）
- **#3 sid 121 polish ✓**：gold 加註「社群可 fine-tune（GRPO）外加推理、但非 stock 開關，對部署的 gemma3:4b 仍 no-op」，堵 Qwen 過度保守 hedge。636→767 字，fail-closed 防重覆套用。
- **#2 補一輪 ✓**：git_ops/terminal_ops/debugging 餘 21 筆獨立複評 = PASS（21/21 panel=9.33）→ **48/48 全覆蓋**。
- **#1 Freeze ✓**：48 gold 全凍入 `gatekeeper_golden_samples`（8×6 type、score 9.0–9.5、無重複、含已 polish 的 sid 121）。
  > **凍結性質提醒**：這是「越過 Tier A 地板」綠燈下的決定，建立的是 gatekeeper 參照基準（provenance / floor-clearance），**非逐筆品質保證**。
  > 飽和 panel 無法逐筆排序，frozen set 的細緻品質仍以撰寫＋外部查證（如 sid 121）為憑，而非裁判分數。
