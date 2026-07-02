# 資料流現況盤點（2026-07-02，code-level + live DB row 數佐證）

> 一頁清帳：每條資料流的寫入點 → 表 → 讀取者，標注 active / dormant / deprecated。
> 佐證方式：全 repo code 追蹤 + live DB 唯讀查 row 數（非憑 flag 推論）。
> 對應決策：2026-07-03 主軸再定位（author/curate/eval/route），見 `AGENTS.md`「主軸」節。

## 總覽事實（三條）

1. **所有 active 資料流的終端讀者都是人、無一是模型**：`feed_model=false`（`layer_1_memory/config.yaml`）→ 召回不注入 Claude；Layer 0 `route()` 每 prompt inline 跑但只寫遙測；`finetune_runs`=0（本 DB 從未記錄任何訓練 run）。系統唯一 consumer＝Shiba 本人。
2. **Working tree＝production**：hooks 註冊在全域 `~/.claude/settings.json`（`Stop`／`UserPromptSubmit`），從 checkout 的 branch 執行。切 branch＝切生產行為。
3. **系統真實身分＝個人工作語料庫＋遙測**（31k messages／47k exchanges 含工具呼叫），非模型工廠。

## 資料流圖

```
[UserPromptSubmit] hooks/session_start_hook.py                      [ACTIVE]
  ├─ gate 鏈（is_system_meta → is_short → is_low_signal）
  │   └─ _vector_search ─reads→ exchange_embeddings(772, 771 有 answer)
  │       └─ 空則 fallback ─reads→ sessions_fts(578)
  ├─ Layer0 route() ─writes→ router_decisions(1808)   ※僅遙測，草稿不注入
  ├─ 召回結果 ─(feed_model=FALSE)─X→ Claude context（不注入）
  ├─ writes→ .remember/rag_echo.md ─read→ statusLine + 人
  ├─ writes→ recall_logs/<date>.txt（cause）+ .pending_*
  └─ branches.access_count UPDATE（僅 FTS5 fallback 路徑）             [半死]

[Stop] hooks/session_stop_hook.py（parse .jsonl）                    [ACTIVE]
  ├─ writes→ projects(11)/sessions(579)/messages(31k)/tool_executions(8.8k)/
  │          branches(5292)/branch_messages/sessions_fts
  ├─ writes→ exchanges(47k)/exchange_messages(500k)
  ├─ writes→ exchange_embeddings（含 answer；純問答不再丟）
  ├─ UPDATE→ router_decisions(採納)/training_samples.weight
  └─ writes→ recall_logs（補答案）+ 清 .pending_*

[Layer 2 chamber] FastAPI + APScheduler                             [DORMANT]
  server 手動起（uvicorn/docker）才活；hook 不觸發。
  reads exchanges/messages → writes training_samples(123)/teacher_usage_logs(2275)

[Layer 3 training] launchd daemon 設計                               [DORMANT]
  可裝未裝；finetune_runs=0 ＝從未跑過。
```

## 孤兒流 / 半死流（清帳標記，不刪 code）

| 項目 | 現況 | 判定 |
|------|------|------|
| `finetune_runs` | 讀取者眾（Layer2 drift／trigger_policy）但 0 列，恆讀空 | dormant（L3 從未運行的直接證據） |
| `branches.access_count/last_accessed` | 只在 FTS5 fallback 路徑更新，主 vector 路徑不更新 → decay 輸入半死 | 半死（decay 機制實質停擺） |
| `exchange_embeddings.source_instruction` | 全 NULL（paraphrase flag off） | dormant 欄位 |
| `config/db/schema_core.sql` | 無 runtime caller（只有 tests 用）；live DB＝layer1 schema.sql + layer2 schema_layer2.sql + module SQL 拼成 | 純文件／驗證參考 |
| `recall_logs/<date>.txt` | 兩 hook 都寫、無任何程式讀 | 設計如此（人工稽核通道） |
| `deprecated_exchange_embeddings_old`(2615)、`golden_samples`、`retrieval_golden_set`、`evaluation_results` | 改名/重建前舊表，無現行讀取者 | deprecated 殘留 |
| feature 表（`gatekeeper_golden_samples`(48)／`ragas_*`(1169/111)／`evaluation_runs`(31)） | 有資料但對應 flag 全 `false`——由 script/實驗建立，生產 hook 鏈不讀寫 | 手動工具用 |
| `layer_1_memory/db/schema.sql` 頂註 `~/.local-brain/` | 過時路徑註解（實際 `data/shiba-brain.db`） | 待順手修 |

## 維護面積結論

有真實讀者的流只有一條：**hooks 對話入庫 + recall_logs/rag_echo 人讀稽核**。Layer 2/3 維持 dormant 不投維護；decay／paraphrase／schema_core 不修復（無下游需求）；deprecated 表保留（回滾保險），備份 `data/shiba-brain.db.bak-pre-rename-20260628-195924` 在。
