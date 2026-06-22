# EV Gate 量測結果（Phase 1）

> 判決：**❌ FAIL**（門檻：≥20 patterns 頻率≥3 且覆蓋≥25%）

## 指標
- 清洗後 distinct task-pattern：124
- 總 occurrence（去 junk+去 D4）：146
- 合格 pattern（頻率≥3）：0
- 覆蓋率：0.0
- EV（可省 Claude 呼叫上界 @13%）：0.0

## 頻率直方圖
- 1（一次性）：102
- 2-4：22
- 5-9：0
- 10+：0

## Top 20 重複 pattern
- [2×] <command-name>{path}<{path}>
            <command-message>effort<{path}>
            <command-args>medium<{path}>
- [2×] 根因排序：                                                                                                                          
  1. DB 多處 page 損壞（主因）                                                                                                        
  2. busy_timeout=0（沒設，但這次不是 lock，是壞頁，次因）
- [2×] <local-command-stdout>Run {path} to apply plugin changes.<{path}>
- [2×] Step 2：DB 加 router_config 表 這裡只寫上模型 要如何映射到yaml檔？難不成前端切換時就直接讀取對應yaml?
- [2×] 執行 Step 1：model yaml schema + loader {file}-35B-A3B model 建立yaml
- [2×] 現在架構 要如何做到 彈性抽換模型 但保有訓練集資料 讓新模型可以快速學習
- [2×] 前端各頁面帶出[API 錯誤：500 Internal Server Error — Internal Server Error]
- [2×] 詢問[Fine-tuning]頁面顯示block1、block2 目前只有1有 2無 請推敲其功能頁面用途
- [2×] Here is grok suggestion, let thinking 哪些是可納入考量的建議內

重大缺點與風險（直白批評）：
•  目前幾乎沒有實證證據：Repo {path} 都是 0，上線時間很短（{file}.1 剛在 2026-04-29），沒有任何公開 benchmark、採納率數據、{path} 比較、用戶反饋。這類自我進化系統最難的是正向回饋循環是否真的收斂，而不是發散或產生模式崩壞（mode collapse）、重複性更高但品質更低的輸出。目前看來還停在「工程實現」階段，缺乏「它真的變得更好」的證明。
•  Judge 與資料品質風險極高：依賴外部閉源
- [2×] git commit and update changelog，先做A2結束後停止
- [2×] Implement the following plan:

# Teacher API 配額監控與管理

## Context
現有 `teachers` 表已有 `daily_limit`/`is_active` 欄位，`teacher_usage_logs` 有 `tokens_used` 欄位但全為 NULL（底層呼叫只取回文字，丟棄 API response 中的用量資訊）。目標：讓 token 數實際寫入 DB，並提供 {path} API 供監控與調整。

---

## Schema 異動（ALTER TABLE，DB 已存在）

```sql
-- teachers 表
- [2×] Claudest有可以參考的做法嗎
- [2×] Implement the following plan:

# 計畫：Claudest Repo 索引 .md

## Context

Claudest repo 已下載至 `{path}`。需要在該目錄下建立一份索引 .md，方便後續快速取用，不需每次重新閱讀原始碼。

## 目標

建立 `{path}`，涵蓋：
- Plugin 清單與版本
- 每個 plugin 的 {path} 速查
- 與本專案（shiba-fine-tunin
- [2×] 根據你的對話

  現在：先做 trigram（選項 A），一次 schema migration，立刻改善中文召回，風險低。

  Layer {path} 穩定後：加 nomic-embed-text + sqlite-vec（選項 B），才是根本解法。

  兩套不是指兩個完全獨立系統，而是 SQLite 儲存 + 向量索引共存，同一份資料，兩種查法。 回頭調整
- [2×] 四份論文與Claudest內有值得參考、改善或借鏡的地方嗎
- [2×] FTS5 MATCH的機制是引用哪裡的參考資料
- [2×] 這個驗證已經通過 Step 1：確認 FTS 現有狀態（改前基線）
  ! sqlite3 ~{path} \
    "SELECT session_uuid, substr(content_summary,1,80) FROM sessions_fts LIMIT 5;"

  Step 2：重跑 stop_hook 觸發一次新寫入

  直接結束這個 session 再開新 session 即可（Stop Hook 會自動觸發）。
  或手動用上一次真實的 session JSONL 觸發：
  ! tail -1 ~{path}
- [2×] Implement the following plan:

# Plan：修復 FTS5 內容為空導致 RAG 無效

## Context

Phase 1 驗證發現：stop_hook 寫入 sessions_fts 時，`content_summary` 全為空字串。
根因：`_build_fts_summary()` 只取 `msg.content`（純文字），但 terminal_ops 等 session
的訊息幾乎全是工具呼叫，`content` 欄位為空。
FTS5 無可搜尋內容 → RAG 回傳 3 筆空殼記憶 → session_start_hook 注入無意義內容。
- [2×] echo '{"session_id":"test","cwd":"{path}","prompt":"terminal bash"}' \| {path} \{path} 2>{path}
{"session_id":"test","cwd":"{path}
- [2×] 開PR push and merge main

## 解讀（人工全量 sanity-pass：freq-1 尾巴 + 漏斗 + 發散濾殺名單）

**判決：FAIL 穩健（robust）。base-assumption-first 觸 STOP——不建 Pattern Library。**
前提「Shiba 夠常重複同型原子指令任務、足以撐 Library」**不被資料支持**。

### 證據漏斗（raw → 最終）
- raw 2578 rows / 1155 distinct instruction
- 發散濾（一句對 ≥3 commands）殺 1092 rows（僅 76 distinct）→ 餘 1486
- junk 閘殺 644 rows（43%）→ 餘 842
- (session,commands) 去 D4 灌水：842 → 146（5.8× 壓縮）
- 最終：124 distinct patterns / 146 occurrence；頻率天花板 = **2×**；合格(≥3)=**0**

### 三項判讀（皆已實證、非臆測）
1. **無 PASS 方向 regex artifact**（advisor 主風險未觸發）：天花板 2×，無 pattern 因
   {path}/{file} 貪婪併接虛胖過門檻。
2. **freq-1 尾巴（102 筆）真異質**：逐筆掃過為各自不同的一次性設計/除錯/前端提問；
   僅極小數措辭叢集（prompt-injection 疑慮 ~4、續接摘要雜訊 ~2、effort echo ~3），
   且多屬雜訊。**無**被弱歸併藏起的重複原子任務群——完美語意歸併也到不了 20×(≥3)。
3. **發散濾殺的是雜訊不是任務**：被殺 top 是 harness/控制詞（`/model` 150r、
   `<local-command-caveat>` 132r、`go` 75r、`/effort` 70r、`Set model to…` echo、`ok` 37r、
   `<bash-input>`、skill dir header），非重複原子任務（「開PR push and merge main」反而存活、
   出現在保留集 freq-2）。故濾器未藏重複。

### 為何「資料未就緒」不成立（修正先前過寬讀法）
去噪只會從**分母**移除雜訊，**不會製造** freq-3 重複。語料最高頻字串本身就是
harness 噪音與控制詞（go/ok/繼續/`/model`），非 Shiba 的工程任務 → 即便修好
ingestion 原子化，重複頻率仍上不去。

### 殘留誠實 caveat（不改判決方向）
- `instruction` 欄確含非原子大塊（整份 plan 貼上、grok dump）與漏過 junk 的系統雜訊。
- 發散濾確實連帶殺掉少數真實 step-control（「先做A4結束後停止」型）。
- 兩者皆真，但即使全額補回也跨不過 2×→20×(≥3) 的鴻溝 → FAIL 方向不變。

### Gate 後路徑（plan §決策）
FAIL（穩健）→ 高價值負結果：省下 Phase 2+ Library build。退路＝**不建 Library、
改純查詢側召回改善（HyDE）**，回 advisor 校準；或重新定義「pattern」單位
（非逐字指令，而是更高階任務類型）再量——但那是新前提，需另證。
