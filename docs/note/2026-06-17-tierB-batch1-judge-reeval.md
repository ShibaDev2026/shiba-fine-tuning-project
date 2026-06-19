# Tier B batch 1 gold — 本地三裁判獨立複評（破 grader=author 循環）

> **目的**：6 筆 gold 由我（Claude 本 session）親撰+親評，grader=author 有循環。
> 本複評用 Layer 2 active 本地三裁判**獨立**評其訓練品質（0-10），看我的標準是否站得住。
> **方法**：`_call_openai_compat` 直呼、完整答案不截斷（3/6 gold > 500 字，避開生產路徑 `output[:500]`）、
> `max_tokens=2048`、thinking 關閉、judge-outer 序評；不改 gold/training_samples（繼續觀望）。

## 判讀基準（呼叫前預先承諾，非事後）
- 基準 = **Tier A 同一本地裁判分布（max 6.67）**，非我的自評 9.0–9.5（harsh panel，不同校準）。
- ✅ PASS：6 筆 judge-mean 全 >= 7.5（清楚分離）。
- ⚠ 邊際：任一落 (6.67, 7.5)。
- ❌ 重新校準：任一 judge-mean <= 6.67（落入 Tier A 區間）。

## 結果

| sid | event_type | 我自評 | Qwen3.5-35B-A3B | GLM-4.7-Flash | Gemma-4-e4b | judge-mean | vs Tier A(6.67) | 分類 |
|----:|------------|------:|------|------|------|----------:|---------|------|
| 75 | git_ops | 9.5 | 9.0 | 9.0 | 10.0 | 9.3 | +2.66 | 清楚↑ |
| 83 | terminal_ops | 9.0 | 8.0 | 9.0 | 10.0 | 9.0 | +2.33 | 清楚↑ |
| 91 | code_gen | 9.5 | 9.0 | 9.0 | 10.0 | 9.3 | +2.66 | 清楚↑ |
| 99 | debugging | 9.5 | 9.0 | 9.0 | 10.0 | 9.3 | +2.66 | 清楚↑ |
| 107 | architecture | 9.0 | 9.0 | 9.0 | 10.0 | 9.3 | +2.66 | 清楚↑ |
| 115 | knowledge_qa | 9.0 | 9.0 | 9.0 | 10.0 | 9.3 | +2.66 | 清楚↑ |

**Panel mean（6 筆 judge-mean 平均）**：9.3　｜　clear=6 / marginal=0 / below=0

## 判定：✅ PASS（可量產其餘 42）

6 筆 judge-mean 全 >= 7.5，清楚高於 Tier A 天花板 6.67，撰寫標準經獨立裁判確認。

## 批判性檢視（避免迎合性解讀）

**1. within-gold 分布扁平 → 只驗證「整批達標」，不細排序。** GLM 全 9.0、Gemma 全 10.0，
6 筆間幾乎無變異。這證明我的 gold **整批**落在明顯高於 Tier A 的 regime，但**不**能用來細排序 6 筆彼此高下。
Gemma-4-e4b（小模型）全給 10.0，近乎橡皮圖章、區辨力最低；最具資訊量的是 **Qwen3.5-35B**——唯一給出差異化票
（sid=83 給 8.0，理由具體：「要求一行指令卻給兩行」），證明大模型裁判確實在讀內容而非套版。

**2. 去掉 Gemma 仍 PASS。** Qwen mean=8.83、GLM mean=9.0，皆遠高於 6.67 → 結論不靠最弱的 Gemma 撐。

**3. 9–10 vs 6.67 的落差含兩個混淆因子（不可全歸功於撰寫品質）。**
(a) 我的撰寫品質；(b) 題庫是 curated 乾淨問題 + 親撰完整答案，Tier A 是真實 session 的雜訊捕獲。
誠實結論：**「我的撰寫標準經獨立裁判確認，適用於『從題庫撰寫 gold』」**，而非「我的答案普遍比真實資料高 2–3 分」。

**4. 驗證邊界。** 本複評驗證了「grader≠author 下我的 gold 仍獲獨立高分」→ 循環已破、可量產其餘 42；
但**未**驗證：(i) 6 筆間細緻品質排序；(ii) 困難/邊界問題上的標準（題庫偏 canonical 基礎題）。
量產 42 題時遇明顯較難的題，仍應逐題保留我自評理由供事後抽查。

## 逐筆裁判理由（散度細節）

### sid=75 ｜ git_ops ｜ 我自評=9.5
**Q：** 如何建立一個新 branch 並切換過去？

- **Local Qwen3.5-35B-A3B (LMS)** → 9.0：instruction 清晰，output 提供多種正確做法並包含詳細說明與驗證步驟，僅因未針對特定版本環境做更嚴謹的預設值假設而扣一分。
- **Local GLM-4.7-Flash (LMS)** → 9.0：instruction 清晰，output 包含多種情境說明且語法正確，具備實用性
- **Local Gemma-4-e4b (LMS)** → 10.0：指令清晰，輸出內容極為完整且專業，不僅提供了核心命令，還涵蓋了現代/舊版指令、多種做法以及後續的推送和驗證步驟，可直接用於訓練。

### sid=83 ｜ terminal_ops ｜ 我自評=9.0
**Q：** 如何用一行指令找出目錄下所有超過 100MB 的檔案？

- **Local Qwen3.5-35B-A3B (LMS)** → 8.0：指令正確且解釋詳盡，但 instruction 要求「一行指令」，輸出卻提供了兩行不同功能的選項（僅列出檔案 vs. 列出並排序），未嚴格遵守單一行的限制。
- **Local GLM-4.7-Flash (LMS)** → 9.0：instruction 清晰，output 提供了多種解決方案且詳細解釋了參數語意，具備實用性與教育價值
- **Local Gemma-4-e4b (LMS)** → 10.0：指令清晰，output 不僅提供了正確的命令，還提供了兩種不同用途（基礎查找與可排序、人類可讀）的高級解決方案，並附帶了極為詳細且技術上精確的解釋。

### sid=91 ｜ code_gen ｜ 我自評=9.5
**Q：** 寫一個 Python context manager 來計算程式區塊的執行時間。

- **Local Qwen3.5-35B-A3B (LMS)** → 9.0：提供兩種實作方式且邏輯正確，但輸出包含大量非程式碼的解釋文字與註解，略影響純代碼輸出的簡潔性。
- **Local GLM-4.7-Flash (LMS)** → 9.0：Instruction 清晰，Output 提供了兩種實作方式（裝飾器與 Class），並詳細說明了關鍵細節（如使用 perf_counter、finally 確保計時、回傳值處理），品質優良且具參考價值。
- **Local Gemma-4-e4b (LMS)** → 10.0：完美範例。不僅提供了兩種實現方式（decorator 和 class），還詳細解釋了技術細節，如使用 perf_counter 的原因、finally/__exit__ 的作用以及例外處理機制，內容完整且極具教學價值。

### sid=99 ｜ debugging ｜ 我自評=9.5
**Q：** SQLite OperationalError: database is locked 如何診斷與修復？

- **Local Qwen3.5-35B-A3B (LMS)** → 9.0：診斷邏輯清晰完整，修復方案涵蓋設定調整與程式設計最佳實踐，但缺少具體的 Python/SQL 代碼範例。
- **Local GLM-4.7-Flash (LMS)** → 9.0：診斷步驟清晰，修復方案由輕到重且具體，包含預防措施，實務性極高
- **Local Gemma-4-e4b (LMS)** → 10.0：指令清晰，輸出內容極為完整且專業，涵蓋了錯誤的定義、多層次的診斷步驟（從應用到系統級）、由輕到重的修復方案和預防措施，可直接用於訓練。

### sid=107 ｜ architecture ｜ 我自評=9.0
**Q：** SQLite 與 PostgreSQL 在 multi-process 寫入場景下如何選擇？

- **Local Qwen3.5-35B-A3B (LMS)** → 9.0：回答精準且結構清晰，準確對比了 SQLite 與 PostgreSQL 在 multi-process 寫入場景下的核心差異（單寫者 vs 多寫者），並提供了具體的選型判準與 YAGNI 建議，僅因缺少輸入數據而無法評估針對性，但不影響通用指導價值。
- **Local GLM-4.7-Flash (LMS)** → 9.0：Instruction 與 Output 高度相關，結構清晰，涵蓋核心差異、選擇條件及實務建議，品質優良
- **Local Gemma-4-e4b (LMS)** → 10.0：指令清晰，輸出內容極為完整且專業，提供了深入的技術比較、使用場景判斷和決策流程，可直接用於訓練複雜的架構選型推理能力。

### sid=115 ｜ knowledge_qa ｜ 我自評=9.0
**Q：** MLX 的 unified memory 架構與傳統 GPU 記憶體的差異是什麼？

- **Local Qwen3.5-35B-A3B (LMS)** → 9.0：instruction 清晰且輸出內容準確完整，深入解析了 MLX 統一記憶體與傳統 GPU VRAM 在架構、數據傳輸及實務影響上的核心差異。
- **Local GLM-4.7-Flash (LMS)** → 9.0：instruction 清晰，output 完整且精確地解釋了 unified memory 架構的核心差異與實務影響
- **Local Gemma-4-e4b (LMS)** → 10.0：指令清晰，輸出內容專業、結構完整，精確且全面地比較了兩種記憶體架構的技術差異與實務影響，可直接用於訓練。

## 附記：生產評分路徑的長樣本截斷（reframe）
- 生產 `_call_teacher` 對 `output[:500]` 截斷 → 本批 3/6 gold（sid 91=1003 / 99=561 / 115=568 字）若走生產路徑只被評前 500 字。
- 這是**評分路徑對任何長樣本的共通行為**（Tier A 亦適用），非「gold 下游半截」；本複評刻意繞過以公平評完整答案。
- 待決（與本複評獨立）：是否為長 gold 提高評分截斷上限，或約束 gold <= 500 字。