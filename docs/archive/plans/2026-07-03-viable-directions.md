# 2026-07-03 可作方向計畫（業界對標後篩選）

> 依據：2026-07-02 資料流盤點 + 業界做法對標（author / curate / eval / route）。
> 篩選標準：成本有界、有明確 gate、正負結果都有行動意義。
> 不列入：召回側任何新工程（上位前提未證）、cascade 架構重構（定位調整即可，不需 build）、L3/fine-tune（已證死）。

## Task 1 — 糾正頻率 probe（唯讀，~2–3h）

**內容**：一次性唯讀腳本掃 `messages`（role=user，全 574 session），偵測「糾正/偏好型」訊息（「不要…」「改用…」「我說過…」「以後都…」等 + 語意判讀），distinct-session 計頻。母體＝糾正類，**非**任務指令（keystone/EV 量過的是後者）。
**產出**：`experiments/2026-07-03_correction_freq/RESULT.md`（頻率分布 + freq≥3 清單逐筆 audit，防 artifact——沿用 keystone 的教訓：slash echo / harness 噪音要濾）。
**Gate**：freq≥3 的真實糾正存在？
- PASS → 人工 curate 進 CLAUDE.md（不自動產規則），並定義後續極輕節奏（每月一次重跑腳本即可）。
- FAIL → 結案：CLAUDE.md 純靠當下手感維護，連這個訊號都不建。
**副作用**：零 production code、零 DB 寫入。
**模型/effort**：Opus high（糾正語意判讀 + artifact audit 是核心難點）。

## Task 2 — 專案定位收束改寫（doc-only，~1h）

**內容**（Task 1 結果出來後一起改，一個 commit）：
1. `CLAUDE.md` + `docs/roadmap/`：P2「召回餵本地 in-context 執行」正式除名；本地模型定位改「窄車道」（分類/路由/抽取/壓縮，L0 現行角色即正解；13% 是水位不是 bug）。
2. `CLAUDE.md` 加一條 authoring 習慣規則：「同類事第二次覺得煩 → 花 10 分鐘寫成 skill」（由上而下 authoring 取代 mining，頻率牆不適用於人工判斷）。
3. Roadmap 主軸改寫為四件事：author（skills）/ curate（CLAUDE.md）/ eval（Task 3）/ route（L0 維持）。
**Gate**：Shiba 過目後 merge。
**副作用**：改專案憲法文件，影響後續所有 session 的行為基準（這是目的）。
**模型/effort**：Sonnet medium。

## Task 3 — 個人評測集 v1（Phase 2，需 Shiba 參與，~半天分兩次）

**內容**：從真實 session 抽 20–30 題建固定評測集（題目+人工 pass 標準）。**題目獨立人工挑，不從召回候選抽**（避 grader=author / cosine-bound 舊陷阱）。配一支最小跑分腳本（沿用 RAGAS 基礎設施可沿用的部分，但 ground truth 獨立標註）。
**第一個用途**：A（模型+CLAUDE.md+需求）vs B（+召回）對照——一次把召回前提定生死；之後每逢新模型/CLAUDE.md 修剪/任何「值不值得」都是一次跑分。
**Gate（啟動前提）**：Task 1、2 完成後，且 Shiba 確認願意投人工標註時間才開跑；B 沒贏 A → 召回線正式結案。
**副作用**：需 Shiba 人工定 pass 標準（無法委託模型，否則重蹈 judge 污染）。
**模型/effort**：題庫設計 Opus high；跑分腳本 Sonnet medium。

## Task 4 —（選配）系統清帳落檔（~1h）

**內容**：2026-07-02 資料流盤點落 `docs/` 一頁（active/dormant/deprecated 標記）；dormant 流只標記不刪 code（`finetune_runs` 讀空、decay 輸入半死、`schema_core.sql` 未接線、L3 daemon 不裝）。
**Gate**：無；純認知負擔止血。可無限期擱置。
**模型/effort**：Haiku low。

## 執行順序與切換時機

1. Task 1（Opus high）→ gate 判定 → 2. Task 2（切 Sonnet medium）→ Shiba 過目 merge → 停，等 Shiba 決定是否啟動 3. Task 3（題庫 Opus high / 腳本 Sonnet medium）→ 4. Task 4 隨時可插（Haiku low）。
每個 task 獨立 commit、驗證過才進下一個；完成驗證後刪本 plan 檔。
