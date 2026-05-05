# 資料流梳理執行計畫（A1+A2+A3）

## Context

Shiba 對 shiba-fine-tuning-project 完整資料流梳理後，分類出 A 級資料契約斷點 5 項、B 級靜默失效 7 項、C 級效能 6 項。

**本輪執行範圍（A3 結束後停）：A1 → A2 → A3 + 未追蹤檔案處理。** A4/A5/B/C 留下輪。

決策依據：
- A3 採用「更新 spec 接受寬鬆實作」（保留 block1+block2 全橋，CLAUDE.md spec 同步更新）
- A4 留待下輪：建議保留三方投票、刪 `score_sample` 死碼、配 C1 early exit
- 未追蹤檔案：`docs/` 納入 git track；`AGENTS.md` 保留（Codex agent 用）

---

## A1 — router_decisions / finetune_runs 補正式 schema migration

**問題**：兩表目前由 layer_2_chamber 啟動時動態 CREATE TABLE，全新 DB 部署在 Layer 2 啟動前若 Layer 3 先呼叫會 crash。

**改動**
1. 將兩表完整定義（含 index、外鍵）寫入 `layer_1_memory/db/schema.sql`
2. `layer_2_chamber/backend/app/config.py` 啟動時的 idempotent CREATE 改為 `CREATE TABLE IF NOT EXISTS` 兜底（保留動態建表，作為舊 DB 升級路徑）
3. 確認 `router_decisions` 欄位涵蓋 Layer 0 telemetry 寫入需求（classification、user_accepted、created_at 等）

**關鍵檔案**
- `layer_1_memory/db/schema.sql`
- `layer_2_chamber/backend/app/config.py`（既有動態 CREATE 邏輯）
- `layer_0_router/telemetry.py`（router_decisions 寫入端）
- `layer_3_pipeline/runner.py`、`server.py`（finetune_runs 寫入/讀取端）

**驗證**
```bash
rm -f /tmp/test_shiba.db
sqlite3 /tmp/test_shiba.db < layer_1_memory/db/schema.sql
sqlite3 /tmp/test_shiba.db ".tables" | grep -E "router_decisions|finetune_runs"
```

---

## A2 — exchange_embeddings 寫入/讀取格式對齊

**問題**：寫入用 `json.dumps(list[float])`（`layer_1_memory/lib/db.py::upsert_exchange_embedding`），讀取在 `layer_3_pipeline/trigger_policy.py::_signal_distribution_drift` 用 `np.frombuffer(blob, float32)`，格式不一致 → Signal C drift 永遠失真。

**改動**：trigger_policy.py 讀取端對齊 JSON 解析（已有部分 `json.loads(r[0])` 邏輯，需確認所有讀取點）

**關鍵檔案**
- `layer_3_pipeline/trigger_policy.py`（_signal_distribution_drift 讀取邏輯，L188-200）
- `layer_1_memory/lib/db.py`（upsert_exchange_embedding 寫入邏輯）

**驗證**
- 跑現有 trigger_policy 相關 unit test
- 補一個 round-trip test：`upsert_exchange_embedding` 後 `_signal_distribution_drift` 能正確還原 vector

---

## A3 — bridge event_types：spec 與 code 對齊

**問題**：CLAUDE.md L64-65 寫 `event_type ∈ {git_ops, terminal_ops, code_gen}` + `has_tool_use=true`，但 `pipeline.py:29-33` 的 `_BRIDGE_EVENT_TYPES = _BLOCK1_EVENT_TYPES | _BLOCK2_EVENT_TYPES` 共 7 種。spec 是早期單一 LoRA 時代寫的，雙 LoRA 拆分後沒同步更新。

**決策**：更新 CLAUDE.md spec 接受寬鬆實作（block1+block2 全橋）。理由：
- Block2（debugging/architecture/knowledge_qa/fine_tuning_ops）的 LoRA 已在「兩個 LoRA Adapter」段定義，若嚴守舊 spec block1-only，**Block2 永遠湊不到 30 approved 樣本**
- v2 已改用 `exchanges.has_final_text` / `has_error` 過濾（比 has_tool_use 更準確），spec 的 has_tool_use 條件也過時

**改動**
1. 更新 `CLAUDE.md` L62-65「Layer 1 → Layer 2 自動橋接條件」段落，反映 v2 實作：
   - event_type ∈ {block1 + block2 共 7 種}
   - exchange.status='clean' AND has_final_text=1 AND has_error=0
   - exchange_count ≥ 2
2. 同步刪除 `_extract_path_a` v1 死碼（pipeline.py L120-175）與 `run_extraction()` L93 呼叫端（合併 A5），避免雙路徑共存產出 `source='layer1_bridge'` 舊樣本

**關鍵檔案**
- `CLAUDE.md`（spec 段落）
- `layer_2_chamber/backend/extraction/pipeline.py`（刪 v1 + 確認 run_extraction 只剩 v2 路徑）

**驗證**
- `grep -rn "_extract_path_a\b" layer_2_chamber/` 應只剩函式定義以外的 zero hits（或全部移除）
- 跑 `tests/layer2/test_pipeline*` 確認 v2 路徑全綠
- DB 抽查：新樣本 `source` 欄位應全是 `layer1_bridge_v2`，無 `layer1_bridge`

---

## 未追蹤檔案處理

- `docs/` 納入 git track（已有 references-blog/git/paper/superpowers 子目錄，視為知識庫）
- `AGENTS.md` 保留（Codex agent 規範，與 CLAUDE.md 並存）
- `2026-04-25_codex_suggestion.md` 移至 `docs/reviews/` 保存
- `data/shiba-brain.db?immutable=1` 不納入 git（DB 檔，加入 .gitignore 若尚未排除）

---

## 後續輪次（本輪不做）

- **下一輪**：A4（multi_judge spec 對齊 + 刪 score_sample）+ A5 收尾（若 A3 未順帶刪完）+ C1（multi_judge early exit）
- **B 級**：B1 驗證 / B2 dataset 邊界 / B4 縮 try-except / B5 冷壓縮條件 / B6 exchanges transaction / B7 alert
- **C 級**：C2 排程時序 / C3 extraction error filter / C4 acceptance heuristic / C5 排程序列化 / C6 keychain_ref schema

---

## /model 與 /effort 切換點

| 階段 | /model | /effort | 切換時機 |
|------|--------|---------|----------|
| A1 schema 設計 | Opus 4.7 | high | router_decisions / finetune_runs 完整欄位設計 |
| A1 落地 + A2 修正 | Sonnet 4.6 | medium | schema 寫入 + JSON↔JSON 對齊 |
| A3 spec 改寫 + v1 死碼移除 | Sonnet 4.6 | medium | 文件對齊 + grep 確認 + 刪除 |
| 驗證收尾 | Haiku 4.5 | low | sqlite3 .tables / pytest / grep 驗證 |

切換口令：A1 設計階段結束時提醒「schema 確定後切 Sonnet medium」；A3 文件改寫完成提醒「全部驗證切 Haiku low」。
