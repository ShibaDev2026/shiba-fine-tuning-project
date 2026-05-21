# Plan：PR-N 系列 — Judge Noise 治理 + Golden Set 擴增

> ExitPlanMode 後將本 plan 檔搬移到 `docs/archive/plans/2026-05-21-pr-n-judge-noise-and-golden-set.md`（CLAUDE.md 規範：plan 檔一律放專案內 `docs/archive/plans/`）

## Context

PR-M Phase 4-5 完整驗證確認當前 RAG 評估的兩個根因瓶頸：

1. **LLM judge noise**：同條件重跑 mean_score 漂移 ~0.3 — 從 conditional expansion 的 −0.4458 拆解中估計，**約 −0.25 屬於 noise**（≈55%），訊號只剩 −0.19
2. **樣本量太小**：n=16 active 題，A/B 變動的可信賴下限約 Δ ≥ 0.5；任何 retrieval 改動（reranker/HyDE/query rewriting）的 A/B 都會被 noise band 吞沒

**意涵**：在治好評估基線前，做 #3-5 的 retrieval 改動是浪費 token — 我們會重演 PR-M 的「結果落 noise band、無法判讀」失敗模式。本計畫專注 #1+#2，建立可信賴評估基線，才有後續 retrieval/rewriter A/B 的基礎。

**Shiba 確認**（AskUserQuestion 2026-05-21）：範圍 = 先做 #1+#2，reranker/HyDE/rewriter 留 PR-N 完成後再個別評估。

---

## PR-N.1：Judge noise 治理

### 副作用注意（先 follow up）

`clients/anthropic/client.py:133` 的 `temperature=0.1` 是**所有 AnthropicClient.generate 共用**的硬寫常數。改成 0 會影響：
- ✅ evaluation 類（c2_e2e judge / golden_set_builder annotate / c1 expected_answer 生成）— 需要 deterministic
- ⚠ teacher_service 任務評分（multi_judge）— 需要 deterministic
- ⚠ 任何 chat / training data 生成類 caller — 可能希望保留多樣性

**正確做法**：把 temperature 提到 `generate()` 的 named parameter，預設 0（評估友善）。各 caller 不傳即用 0，需要多樣性者顯式傳 0.7~1.0。

### N.1.1：temperature 從常數提到 generate() 參數

| 檔案 | 改動 |
|---|---|
| `clients/anthropic/client.py:70` | `generate(...)` 簽名加 `temperature: float = 0.0` |
| `clients/anthropic/client.py:133` | body `temperature` 改用參數變數 |
| `clients/openai_compat/client.py`（檢查對等位置） | 同樣處理，保持 vendor client API 一致 |
| `clients/gemini/client.py`（檢查對等位置） | 同樣處理 |

驗收：所有現有 caller 不傳 temperature 即得 0；grep 所有 `.generate(` callsite 確認無例外。

### N.1.2：c2_e2e_evaluation.py 加 `--n-runs K` flag

| 檔案 | 改動 |
|---|---|
| `evaluation/c2_e2e_evaluation.py:164` | `_call_claude` 與 caller 加 `n_runs: int = 1` 參數 |
| 同檔案 score loop | K>1 時對每題跑 K 次 judge，取 mean 寫入 `evaluation_results.metric_value`，原始 K 個分數寫 `metadata.raw_scores: [s1, s2, ...]` |
| `--n-runs` argparse flag | 預設 1 保持向後相容 |

sleep 規則沿用 PR-M.4 動態 sleep `max(0.5, 4 - elapsed)`，每次 judge 之間。

### N.1.3：量化新 noise band

跑驗證指令（在 PR-N.1 commit 前後各跑一次對比）：
```bash
python -m evaluation.c2_e2e_evaluation \
  --model claude:claude-sonnet-4-6 \
  --rag-window 0 \
  --n-runs 3
```
- 對 16 active 題各跑 3 次 judge
- 計算每題的 std（K=3 樣本內）
- 16 題 std 平均值即為新 noise floor

### 驗收（PR-N.1）

新 noise floor ≤ **0.15**（從 PR-M Phase 4 觀察的 ~0.3 壓低一半以內）。
若仍 > 0.20 → 不通過，需追查 prompt 或 max_tokens 是否壓抑判斷品質。

### 估時：半天～1 天

---

## PR-N.2：Golden set 16 → 50+ 擴增

依賴 PR-N.1 通過（要先有可信 noise floor 才能驗證新題 baseline 是否合理）。

### 流程

| Step | 動作 | 檔案 / 指令 |
|---|---|---|
| 1 | 盤點現況 | `sqlite3 data/shiba-brain.db "SELECT COUNT(*) FROM retrieval_golden_set WHERE is_active=1 AND expected_answer IS NOT NULL"` — 預期 16 |
| 2 | 補題候選 | `python -m evaluation.golden_set_builder --action annotate --n 40 --model claude-sonnet-4-6` — 預期生成 ~40 候選經 Claude 標註 → 25-30 筆通過 |
| 3 | C.1 expected_answer 生成 | `python -m evaluation.c1_generate_answers`（自動處理新題） — sleep 4s × N |
| 4 | Shiba 手動 review | 對新題的 expected_answer 標 `manual-by-shiba` notes；不合格手動修正或棄置 |
| 5 | 標記 is_active=1 | SQL 或 dashboard UI |
| 6 | 新基線 baseline | `c2_e2e_evaluation` 跑兩條：`--model claude:claude-sonnet-4-6` 與 `--model ollama:qwen3:30b-a3b`，run_id metadata 加 tag `n50-baseline` |

### 驗收（PR-N.2）

- `is_active=1 AND expected_answer IS NOT NULL` ≥ **50** 筆
- 新 baseline 與舊 16 題子集（subset 比對）的 mean_score 差 ≤ 0.5
  - 子集比對：先抽 16 題舊題在新跑次的分數 → 算 mean → 跟舊 baseline 7.13 (Claude) / 5.39 (Qwen) 對比
  - 若新跑 16 題子集已偏離 > 0.5 → 表示 N.1 noise floor 未達標或環境變數動了，需先 debug

### 估時：1-1.5 天

| 子工作 | 時間 |
|---|---|
| 補題腳本 + Claude 標註 | 30 min |
| C.1 expected_answer 生成（30 題 × 4s sleep × 1 次） | 30 min |
| Shiba review | 15 min |
| C.2/C.3 baseline 雙跑 | 2 hr |
| commit + 文件 + memory 更新 | 1 hr |

### Known confound（不在範圍處理）

- expected_answer 生成 teacher（Sonnet 4.6）= judge teacher（Sonnet 4.6），存在 self-preference 偏差
- 視為 baseline state，不在 PR-N.2 處理；後續若 #3-5 都跑完仍卡關，再考慮換 expected_answer teacher

---

## Critical Files

| Path | 角色 |
|---|---|
| `clients/anthropic/client.py:70-133` | temperature 參數化（N.1.1） |
| `clients/openai_compat/client.py` / `clients/gemini/client.py` | 同 N.1.1，保持 API 一致 |
| `evaluation/c2_e2e_evaluation.py:164` | `_call_claude` + score loop 加 n_runs（N.1.2） |
| `evaluation/golden_set_builder.py` | 重跑既有 annotate 流程（N.2.2） |
| `evaluation/c1_generate_answers.py` | 對新題跑 expected_answer（N.2.3） |
| `retrieval_golden_set` table | is_active / expected_answer 欄位（無 schema 異動） |

## Verification 順序

1. **N.1.1 後**：`grep -rn "AnthropicClient" --include='*.py' | grep -v test` 確認所有 caller 沒爆
2. **N.1.2 後**：`python -m evaluation.c2_e2e_evaluation --model claude:claude-sonnet-4-6 --rag-window 0 --n-runs 3` 跑 16 題 × 3 = 48 judge call，計算 std
3. **N.1.3 通過驗收後**：才開始 N.2
4. **N.2.6 後**：新 baseline 與舊 16 子集對比，差 ≤ 0.5 即過

## /model 與 /effort 切換建議

| 子工作 | 建議 |
|---|---|
| N.1.1 vendor client temperature 參數化 | Sonnet medium |
| N.1.2 c2_e2e n_runs 邏輯 | Sonnet medium |
| N.1.3 noise floor 統計分析 | Opus high — 結果判讀 |
| N.2.2-N.2.5 補題流程 | Sonnet medium |
| N.2.6 新 baseline 跑 + 子集比對 | Opus high |
| 收尾 commit / CHANGELOG / memory | Haiku low |

## 後續工作（**不在本計畫**，待 PR-N 完成後評估）

- #3 bge-reranker-v2-m3 Ollama 部署（Shiba 已確認偏好 Ollama）：
  - `ollama pull qllama/bge-reranker-v2-m3`
  - 驗證 API endpoint（可能不是 `/api/embeddings`，需查 Ollama reranker support）
  - rerank plug-in 點：`layer_1_memory/lib/rag.py:388`（_vector_search return 前）
- #4 Query rewriting：擴 `layer_0_router/classifier.py` 後加 `rewriter.py` 同級模組
- #5 HyDE / HyPE：架構改動較大，最後評估

---

## 副作用清單（總覽）

| 異動 | 副作用 | 緩解 |
|---|---|---|
| temperature 0.1 → 0（提到參數） | 所有 AnthropicClient caller | 提到 generate() 參數，預設 0；caller 不傳即拿 0；要多樣性者顯式傳 |
| `--n-runs K` flag | K>1 時 judge 呼叫量 × K，token 成本 × K | 預設 K=1，僅在驗證時用 K=3 |
| golden set 擴 50+ 題 | C.1/C.2/C.3 後續所有評估時間 × 3 | 接受；本來 16 題就太少 |
| run_id metadata tag `n50-baseline` | 與舊 16 題 run 共存 | 用 metadata 隔離，evaluation_runs 表不需 schema 異動 |
