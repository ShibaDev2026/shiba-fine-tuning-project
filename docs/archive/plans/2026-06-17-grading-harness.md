# Grading Harness — Design Spec (v1)

- 日期：2026-06-17
- 狀態：設計已經 Shiba 口頭核准，待 spec review → 再進 writing-plans
- 來源脈絡：原 D3 judge 校準 / Top-5 換席驗證卡在「沒有 graded gold」；Shiba 指示用 **Claude（本 session，非付費 teacher API）+ 本地模型**當評分者，建持續迭代 harness 把 `golden_samples` 與 `training_samples` 評滿。

---

## 1. 目的

- **問題**：`golden_samples` 表 0 筆、`training_samples` 僅 3 approved；C 全量校準（裁判 vs ground truth 一致率）缺 gold ground truth，跑不起來。`router_decisions.user_accepted` 是二元且 session 級退化（可歸因單樣本僅 15 筆），不能當 gold。
- **解法**：建一個 **session 可續的評分 harness**，從乾淨來源挑批次 → 本地模型批量初評 → **Claude 權威評分** → Claude 權威分達標凍結進 `golden_samples` → 記錄進度，跨 session 接力，把 TS 評滿、gold 從 0 長出。

## 2. Scope

### In（v1）
- 來源：**29 pending `training_samples` + 48 題 question bank + 既有 chamber pipeline**（questions→responder→judge→training_samples）。
- 兩 tier 評分（見 §5）、PII gate（§7）、Claude-vs-local 一致量測、gold freeze、進度追蹤/續跑。

### Out（延後，gated）
- **exchange-mining（42,658 筆 exchanges）**：memory 標記**已證偽**路徑——13% 採納率、branch membership 錯亂、DAG 斷鏈。**DAG 斷鏈是資料完整性問題，評分濾不掉**。降級為 **tier 2，gated**：僅當 v1 的 gold 產出證明不足時才開。
- 理由：先建大 miner = 先建架構再回頭證明它有用，違反 base-assumption-first。

## 3. 完整度事實（驅動設計，已查 DB）

| 事實 | 數字 | 設計含義 |
|------|------|---------|
| pending `instruction` / `output` | 29 / 29 | reference-free 評分立即可行（judge 評 output 好壞，不需 expected）|
| pending `expected_answer` / `input` | 2 / 5 | gold tier 需 Claude **親手寫 expected_output** |
| pending `pii_scrubbed=1` | 14 / 29 | **15 筆未 scrub → PII gate 必要**（`messages.content` 明文含路徑/本機名/機敏 model row）|
| approved（expected/score/reason 全有）| 3 | 首批 gold 種子 |
| event_type 分布 | git_ops 24 … code_gen 2 | 選樣需平衡，否則 gold 偏斜 |

## 4. 架構（5 階段）

| 階段 | 做什麼 | 新 / 既有 |
|------|--------|----------|
| 1 選樣 | 從 pending + chamber 輸出挑批次，按 event_type 平衡 | 既有 chamber |
| 2 **PII gate** | 送 Claude 前 scrub 路徑/本機名/handle/機敏 model row，設 `pii_scrubbed=1`；本地模型看原文（本地推論不外流）| **新（窄）** |
| 3 評分 | 本地三裁判批量初評（reuse `teacher_service`）+ Claude 權威評分，Claude 分數寫 `frozen_at` → gold 跨 session 穩定 | 既有 + Claude 新介入 |
| 4 裁決/一致 | 算 Claude-vs-local 一致率（reuse `judge_agreement_logs` fleiss，並記、不 gate freeze）→ **Claude 權威分達標**即凍結進 `golden_samples`（reuse `modules/gatekeeper` writer）；分歧由 Claude 裁決 | 既有 |
| 5 **進度** | 追蹤每 event_type 評到哪、誰評過；session 可續；定義「評滿」 | **新（窄）** |

## 5. 兩個評分 tier（同一 harness）

- **Tier A — 評 `training_samples`**：補 `score` / `score_reason` / `status`。29 pending 立即可做 → 養 L3 訓練池（朝各 block ≥ 30 approved 觸發 fine-tune）。本地批量、Claude 抽查。
- **Tier B — 建 `golden_samples`**：Claude **親手寫 `expected_output`（gold 參考答案）** + 權威凍結分 → 校準 gold。本地寫不出好參考，這正是「用 Claude」的理由。Claude 全評、本地分數並記做校準。

## 6. 角色分離 = 同時解掉原本的 C

- **Claude = 權威 gold（凍結）**、**本地 = 被量測對象**。無循環（Claude 不是被校準的 judge，Claude 是 gold 本身）。
- 分歧權威序 **Shiba > Claude > local**（對齊現有 `user_accepted=1` 覆蓋規則）。
- **三產出**：① 評滿的 TS（餵 L3）② `golden_samples`（校準 ground truth）③ Claude-vs-local 一致數據（D3 校準 + 餵回 Top-5 換席決策）。

## 7. PII Gate（機敏防線）

- 送 Claude（Anthropic API）前，規則式 scrub：本機絕對路徑、本機名、Shiba handle、機敏自訂 model row、token/key 樣式 → 佔位符。設 `pii_scrubbed=1`。
- 本地三裁判看**原文**（本地推論，不外流）。
- 凍結進 `golden_samples` 的內容一律取 scrubbed 版。

## 8. 進度 / 續跑

- 追蹤 per event_type 已評 / 待評、誰評過（Claude / local / 兩者）。
- 「評滿」定義為可量測的停止條件（見 §9 旋鈕 1）。
- 每 session 啟動讀進度 → 接著跑未評批次。

## 9. 旋鈕（預設值，Shiba 可推翻）

1. **「評滿」定義**：每 event_type ≥ N 筆 gold 且分布平衡；N 先抓小（10–15）跑通再加。
2. **本地裁判角色**：Tier B Claude 全評 + 本地並記（不讓本地誤判污染 gold）；Tier A 本地批量 + Claude 抽查。
3. **gold freeze 門檻**：Claude 權威分 ≥ 8 即凍結（gold 要夠好）；一致率僅記錄、不當 freeze 條件（gold 由 Claude 定，不靠 local 同意）。

## 10. 新增 vs 重用（防止重造輪子）

- **新（窄）**：PII scrub gate、進度追蹤/續跑、Claude in-session 寫分介面。
- **重用**：chamber pipeline、`teacher_service`（本地三裁判）、`judge_agreement_logs`（fleiss）、`modules/gatekeeper`（gold freeze）。

## 11. 測試 / 驗收

- **單元**：PII scrub 規則（路徑/handle/機敏 row/token 樣式命中與佔位）、進度續跑（中斷後接力）、freeze 條件（Claude 分數門檻達標、一致率不 gate）。
- **整合**：29 pending 跑通 Tier A（status 由 pending→approved/rejected）；3–5 筆跑通 Tier B 並 freeze 進 `golden_samples`。
- **成功標準**：`golden_samples` 0 → 首批（每 event_type 有種子）；Claude-vs-local 一致數據可算；harness 可中斷續跑。
- 回歸：既有 `pytest tests/layer2/ -q` 不退（baseline 168 passed / 6 pre-existing fail）。

## 12. 風險與緩解

| 風險 | 緩解 |
|------|------|
| PII 漏 scrub → 機敏外流到 Anthropic | scrub gate + 白名單單元測試 + 批次送 Claude 前規則雙檢；漏判時 fail-closed（寧可不送）|
| Claude gold 偏差 | 定義上 Claude 即 ground truth；Shiba 可覆蓋（權威序最高）|
| event_type 偏斜（code_gen 2）| 平衡選樣；不足者接受小 N 或標記待補 |
| 重造 chamber/gatekeeper | §10 明列重用清單，新碼僅限三窄項 |

## 13. 建議 model / effort（進 writing-plans 後逐步切換）

- PII scrub 規則 + freeze 判準（核心、易錯）→ **Opus high**
- 進度表 / 選樣 / 整合既有 pipeline（樣板）→ **Sonnet medium**
- 測試撰寫 / 驗收跑分（收尾）→ **Haiku low**

---

## 待決（Shiba 審 spec 時確認）
- v1 scope 線（exchange-mining 延後）是否同意。
- §9 兩旋鈕預設值是否接受。
- commit 時機。
