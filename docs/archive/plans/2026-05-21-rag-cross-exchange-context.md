# Plan：RAG 跨 exchange 上下文召回（macro-exchange context）

## Context

### 問題

Shiba 觀察到當前 RAG 召回品質受限於**單 exchange 粒度**：
- 一個任務通常橫跨 4-6 個 exchange：提案 → 接受（如「1=ok 2=可以」）→ 執行指令 → 工具結果 → 收尾
- `exchange_embeddings` 以單一 user 訊息為粒度做向量召回，召回時**孤立呈現一個 exchange**，前後因果斷裂
- Step 2 候選挖掘已驗證：撈出的 25 個 query 中 ~30% 是「1=可 2=可 3=ok」這類**單獨無意義、需上下文才有意義**的 ack-only message
- C.2/C.3 baseline 卡在 5.39 / 5.14，bge-m3 升級後召回指標小幅波動但 E2E 品質沒突破——疑似召回粒度是瓶頸

### 目標

在**不動 schema 大改、不破壞既有 baseline**前提下，驗證「召回時帶上 ±K 個鄰居 exchange」能否提升 C.2/C.3 E2E 品質。

### 對應前述討論

選項 3：純召回時聚合。**不**做選項 1（exchange_groups 顯式建模）和選項 2（parent_exchange_id 鏈）。先用最小成本驗證假設；若驗證有效再考慮持久化建模。

### Shiba 已確認的決策（2026-05-21）

- ✅ window_k 預設 = 2
- ✅ A/B 用 Claude judge
- ✅ Phase 4 雜訊範圍時保留 API 但預設 K=0

---

## 可行性評估

### ✅ 可行條件

| 條件 | 現況 | 是否已具備 |
|---|---|---|
| exchange 粒度資料 | `exchanges` 表（含 `branch_id`, `exchange_idx`, `user_text_preview`, `final_text_preview`） | ✅ |
| exchange 順序 | `exchange_idx` 0-based、`UNIQUE(branch_id, exchange_idx)` | ✅ |
| message 完整內容回取 | `exchange_messages` 橋接 + `messages.content` | ✅ |
| 召回 API 隔離 | 已有 `retrieve_for_eval` 與 `get_rag_context` 雙路徑 | ✅ |

### ⚠ 阻塞點

`exchange_embeddings` **沒有 `exchange_id` 外鍵**。
- Schema 第 202-211 行：只有 `(session_uuid, instruction, commands, embedding)`
- 召回後拿到 `(session_uuid, instruction)` → 要回找 `exchanges.id` 必須以 `user_text_preview` 模糊匹配
- 解法：加一欄 `exchange_id INTEGER REFERENCES exchanges(id)`，backfill 用 `(session_uuid, user_text_preview)` 對碰

### 🎯 風險與緩解

| 風險 | 機率 | 影響 | 緩解 |
|---|---|---|---|
| backfill 匹配失敗率 > 20% | 中 | 部分舊 embedding 沒鄰居可帶 | 失敗者 fallback 舊行為（單 exchange context），不阻塞 |
| 鄰居 exchange 過長爆 token budget | 中 | judge prompt 截斷 | 每個鄰居只取 `user_text_preview` + `final_text_preview` 前 200 字 |
| K 設太大反而稀釋 signal | 中 | C.3 baseline 下降 | A/B：K=1, K=2, K=3 三檔分別跑 baseline，挑最高 |
| 破壞既有 RAGAS / 訓練流程 | 低 | 全域影響 | 新增獨立 API `retrieve_for_eval_with_context(window_k=K)`，不動現有 `retrieve_for_eval` |

---

## 實作步驟

### Phase 1：Schema 補連結 + Backfill

**檔案**：`evaluation/migration_exchange_id_link.py`（新增）+ `layer_1_memory/db/schema.sql`（加欄）

1. `ALTER TABLE exchange_embeddings ADD COLUMN exchange_id INTEGER REFERENCES exchanges(id)`（idempotent，參考 `migration_is_active.py` 寫法）
2. 加 INDEX `idx_exchange_embeddings_exchange ON exchange_embeddings(exchange_id)`
3. Backfill：
   ```sql
   UPDATE exchange_embeddings
   SET exchange_id = (
     SELECT e.id FROM exchanges e
     WHERE e.session_id = (SELECT s.id FROM sessions s WHERE s.uuid = exchange_embeddings.session_uuid)
       AND substr(e.user_text_preview, 1, 100) = substr(exchange_embeddings.instruction, 1, 100)
     LIMIT 1
   )
   WHERE exchange_id IS NULL;
   ```
4. 報告匹配率（預期 > 80%）

**驗證**：`SELECT count(*), count(exchange_id) FROM exchange_embeddings;`

### Phase 2：新增召回 API

**檔案**：`layer_1_memory/lib/rag.py`

新增函式：
```python
def retrieve_for_eval_with_context(
    query: str,
    project_path: str | None = None,
    top_n: int = 3,
    window_k: int = 2,
) -> dict:
    """召回後對每個 hit 額外帶 ±window_k 個鄰居 exchange 的 user+final preview"""
```

實作流程：
1. 走原本 `_vector_search` 拿 top_n hits
2. 對每個 hit：
   - 用 `exchange_id` 查 `(branch_id, exchange_idx)`
   - SQL: `SELECT user_text_preview, final_text_preview, exchange_idx FROM exchanges WHERE branch_id=? AND exchange_idx BETWEEN ?-? AND ?+? ORDER BY exchange_idx`
   - 將鄰居按時序排列，產生 expanded context block
3. 失敗時（exchange_id NULL）退回原本單 exchange context
4. 回傳結構與 `retrieve_for_eval` 相容（多一個 `expanded` 標記欄）

### Phase 3：新增 evaluation runner flag

**檔案**：`evaluation/c2_e2e_evaluation.py`、`evaluation/ragas_runner.py`

新增 CLI flag `--rag-window K`（預設 0 = 不擴展、走舊路徑）：
- K=0：呼叫 `retrieve_for_eval`（baseline）
- K≥1：呼叫 `retrieve_for_eval_with_context(window_k=K)`

`evaluation_runs.metadata` 記錄 `rag_window` 值，方便後續對比。

### Phase 4：A/B 測試 + 決策

**Smoke**：
- `python -m evaluation.c2_e2e_evaluation --limit 3 --rag-window 2`，目視確認 context 結構合理、token 沒爆

**A/B baseline**：
- 在 active 16 題（`is_active=1 AND expected_answer NOT NULL`）跑 K=0/1/2/3 四檔
- 用 Claude judge
- 比較 mean_score 與分布

**決策矩陣**：

| K=2 vs baseline | 動作 |
|---|---|
| Δ ≥ +0.5 | 採納；考慮 Phase 5（持久化 macro-exchange） |
| +0.1 ~ +0.5 | 採納但維持 flag；macro-exchange 不急 |
| ±0.1（雜訊範圍） | 結論「召回粒度非瓶頸」；轉攻其他角度；API 保留但預設 K=0 |
| < -0.1 | 退回，分析是 token budget / 鄰居污染 |

### Phase 5：（條件性）持久化 macro-exchange

僅當 Phase 4 顯示 K≥1 有顯著提升才執行。詳細設計待結果出爐再寫。

---

## 關鍵檔案路徑

| 檔案 | 動作 |
|---|---|
| `layer_1_memory/db/schema.sql` | 加 1 欄 + 1 index |
| `evaluation/migration_exchange_id_link.py` | 新增 migration |
| `layer_1_memory/lib/rag.py` | 加 `retrieve_for_eval_with_context()`；複用既有 `_vector_search` |
| `evaluation/c2_e2e_evaluation.py` | 加 `--rag-window` flag |
| `evaluation/ragas_runner.py` | 加 `--rag-window` flag |
| `evaluation/c1_generate_answers.py` | **不動** |
| `evaluation/c4_weekly_ci.py` | **不動**（用 K=0 維持 anchor） |
| `evaluation/golden_set_builder.py` | **不動** |

---

## 重用既有實作

| 目標 | 既有可用 |
|---|---|
| Schema migration 模板 | `evaluation/migration_is_active.py`（`_column_exists` 寫法） |
| Vector search 主邏輯 | `layer_1_memory/lib/rag.py:201 _vector_search()`，不重寫 |
| Exchange 順序查詢 | `exchanges` 表已有 `UNIQUE(branch_id, exchange_idx)` |
| Eval runner 結構 | `evaluation/c2_e2e_evaluation.py` 既有 CLI flag pattern |
| 評估結果寫入 | `_write_eval_result`、`_write_run_summary` 已存在 |

---

## 驗證計畫

### 自動化

1. **Migration**：
   ```bash
   python -m evaluation.migration_exchange_id_link
   sqlite3 data/shiba-brain.db "SELECT count(*), count(exchange_id) FROM exchange_embeddings;"
   ```
   通過：匹配率 ≥ 80%

2. **單元 smoke**：
   ```bash
   python -c "from layer_1_memory.lib.rag import retrieve_for_eval_with_context; r=retrieve_for_eval_with_context('Phase A 驗證如何進行', top_n=2, window_k=2); print(len(r['retrieved_contexts']), [len(c) for c in r['retrieved_contexts']])"
   ```
   通過：context 數 ≤ top_n × (2K+1)，每段 ≤ 800 字

3. **C.2 A/B**：
   ```bash
   python -m evaluation.c2_e2e_evaluation --model claude-sonnet-4-6 --rag-window 0  # baseline
   python -m evaluation.c2_e2e_evaluation --model claude-sonnet-4-6 --rag-window 2  # treatment
   ```
   通過：treatment ≥ baseline - 0.1；目標 ≥ baseline + 0.3

4. **Token 監控**：
   - judge 輸入截斷率（context 長度 > 800 的比例）
   - 失敗率（exchange_id 為 NULL 退回單 exchange 的比例）

### 人工

從 16 題隨機抽 3 題，目視比較 K=0 / K=2 context 是否確實補上前後文、是否引入雜訊。

---

## 不在本計畫範圍

1. **substantive filter / is_substantive 欄位**：另一個獨立改善方向，平行進行
2. **Layer 0 router 降格成 substantive classifier**：依賴 1
3. **exchange_groups 顯式建模**：依賴本計畫 Phase 4 結果
4. **`exchange_embeddings.final_response` 配對召回**：本計畫 follow-up，先不疊加

---

## 估時與 model/effort

| Phase | 預估 | 建議 |
|---|---|---|
| Phase 1 (migration) | 30 min | Sonnet medium |
| Phase 2 (RAG API) | 1-1.5 hr | **Opus high**（核心演算法） |
| Phase 3 (CLI flag) | 30 min | Sonnet medium |
| Phase 4 (A/B 跑 + 分析) | 2-3 hr | Sonnet medium（執行）+ Opus high（分析） |
| **總計** | 4.5-5.5 hr 工程 + ~3 hr eval 等待 | — |
