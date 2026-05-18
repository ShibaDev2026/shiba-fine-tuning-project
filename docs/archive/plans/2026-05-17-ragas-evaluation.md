# RAGAS 導入評估與分階段實作計畫

建立日期：2026-05-17
最後修訂：2026-05-18（加註本地 judge 替代方案）
前置條件：PR2（stop_hook SAVEPOINT + multi_judge 外層事務）完成
評估器 LLM：**分階段選擇**（見下方「judge 模型選擇矩陣」）
- Phase A / B：本地 Ollama `qwen3:30b-a3b`（零成本，能力門檻達標）
- Phase C：保留商業 API 選項（fine-tune 前後對比需高一致性 judge）
- A.2 標註：Claude Pro 對話貼模式（一次性 30 筆，無需 API key）

---

## Context

**為何做這件事**
- Layer 1 已知痛點（`project_layer1_rag_concern.md`）：FTS5 中文語意召回有限，trigram tokenize 對子字串覆蓋不足；雖已回填 1523 筆 exchange_embeddings（cosine ≥ 0.35），但缺乏量化指標證明召回品質。
- Layer 2 `multi_judge.py` 三方投票機制上線後，**從未量化 judge 之間的一致性**（Fleiss' Kappa / 互評偏差），無法回答「2/3 approved 是真共識還是 judge 集體偏誤」。
- Layer 3 fine-tuning 一旦觸發（block1/2 ≥ 30 approved 樣本），需要客觀的 RAG 端到端指標來判斷模型是否進步，否則只能憑感覺。
- **無 evaluation harness**：tests/ 只覆蓋功能正確性，無品質回歸基線。RAGAS 是業界標準（v0.4.3, 13.9k stars, Apache-2.0），可離線跑、支援 Anthropic Claude 評估器、繁中靠自訂 prompt + Claude 達標。

**預期成果**
- 三階段建立量化評估基線：Layer 1 召回品質 → Layer 2 judge 可靠性 → End-to-end RAG 表現。
- 不動 hot path（stop_hook / multi_judge 寫入路徑），純加 read-only 評估模組與新增表。

---

## 前置條件（硬性）

按 Shiba 決策：**PR2 完成後才動本計畫**。

PR2 待辦（出自 `project_sqlite_race_hardening.md`）：
- Step 5：`stop_hook.py:165-269` SAVEPOINT 4 段拆解（Opus high）
- Step 6：`multi_judge.py:77-84` 包外層事務（Sonnet medium）

PR2 完成且觀察期過後，本計畫才啟動。

---

## 通用基礎設施（Phase 0，三階段共用）

### 0.1 依賴與套件
- `pip install ragas==0.4.3`
- 評估器 LLM 套件按 Phase 選擇：
  - Phase A / B：`langchain-ollama`（本地 qwen3:30b-a3b）
  - Phase C（如需 API）：`langchain-anthropic` 或 `langchain-google-genai`
- API key 沿用既有 Keychain 機制（`feedback_teacher_key_env_fallback.md`）
- Embedding：本地 Ollama `nomic-embed-text`（與 Layer 1 一致，避免雙系統漂移）

### 0.1.1 judge 模型選擇矩陣（2026-05-18 修訂）

**為何不一律用商業 API**：RAGAS judge 的能力門檻是「能拆 claim、能做 entailment、能輸出結構化 JSON」，本地 qwen3:30b-a3b（MoE 30B）已達門檻。商業 API 只在「需高一致性 + 跨家避免自評偏見」時才必要。

| Phase | 被評估對象 | judge 推薦 | 循環依賴 | 成本 |
|-------|----------|-----------|---------|------|
| A | Layer 1 FTS5 + 向量召回 | **本地 qwen3:30b-a3b** | ❌ 無（純 retrieval，無 generation） | $0 |
| B | multi_judge 三方投票（Gemini Flash + Flash-Lite） | **本地 qwen3:30b-a3b** | ❌ 異源（被評是 Gemini，judge 是 Qwen） | $0 |
| C.2-C.3 | Claude / Ollama 答案（E2E）| 商業 API（Gemini Pro 或 Claude）| ⚠️ Claude 評 Claude 有自評偏見，建議 Gemini Pro | ~$8-12 |
| C.4 | 週度 CI 自動採樣 | 商業 API（必須）| 同上 | ~$0.5/週 |

**A.2 標註器特殊處理**：Golden Set 建構（一次性 30 筆）走「Claude Pro 對話貼模式」— 由 Shiba 透過 claude.ai 或 Claude Code 對話介面分批貼 prompt，免 API key 免成本。詳見 A.2 章節。

### 0.1.2 Anthropic API effort 參數（2026-05-18 新增）

**已驗證**：Anthropic Messages API 支援 `output_config.effort` 控制 token 消耗與推理深度（非 OpenAI 的 `reasoning_effort`，是巢狀於 `output_config` 內）。

| effort | 適用 RAGAS metric | 預估成本/token 比 high | 理由 |
|--------|-----------------|----------------------|------|
| `low` | C.4 週度 CI 採樣（趨勢監控） | ~30-50% | 重複性高、不需深推理 |
| `medium`（API 預設推薦）| A.3 召回 Precision/Recall、C.4 部分指標 | ~60-70% | 二元判斷為主 |
| `high`（API 預設）| B.3 Faithfulness、C.2-C.3 Answer Correctness | 100% | claim 拆解 + entailment 需深思 |
| `max` | 不建議常用 | >100% | 評估場景無需 max |

**實作位置**：`layer_2_chamber/backend/services/teacher_service.py::_call_anthropic`（已實作，預設 `effort="medium"`，呼叫端可覆寫）。

**Phase C.4 排程時注意**：寫排程 script 時依 metric 動態指定 effort，避免一律走 high 燒不必要 token。

### 0.2 新增目錄
```
evaluation/
├── __init__.py
├── ragas_runner.py          # RAGAS 入口（含 Claude adapter）
├── schemas.py               # query/context/response 三元組
├── golden_set_builder.py    # 半自動建立 ground truth
└── reports/                 # 評估結果輸出（JSON + Markdown）
```

### 0.3 新增 DB 表（`migrations/` 新檔，遵循統一 PRAGMA from `shiba_db.py`）

```sql
-- 評估結果（三階段共用）
CREATE TABLE evaluation_results (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id TEXT NOT NULL,              -- UUID per run
  phase TEXT NOT NULL,               -- 'layer1' | 'layer2' | 'e2e'
  metric_name TEXT NOT NULL,         -- 'context_precision' 等
  metric_value REAL NOT NULL,
  sample_id INTEGER,                 -- 對應 training_samples.id / null（aggregate）
  evaluator_model TEXT NOT NULL,     -- 'claude-sonnet-4-6' 等
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  metadata JSON
);

-- Layer 1 retrieval ground truth
CREATE TABLE retrieval_golden_set (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  query TEXT NOT NULL,
  expected_session_uuids TEXT NOT NULL,  -- JSON array
  expected_exchange_ids TEXT,            -- JSON array
  annotator TEXT,                        -- 'shiba' / 'auto-by-claude'
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  notes TEXT
);

-- Judge 一致性紀錄（Phase B 用）
CREATE TABLE judge_agreement_logs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  sample_id INTEGER NOT NULL,
  votes_json TEXT NOT NULL,            -- 3 judges 完整分數+理由
  fleiss_kappa REAL,
  pairwise_disagreement TEXT,          -- JSON: which pairs disagreed
  ragas_faithfulness REAL,
  evaluated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (sample_id) REFERENCES training_samples(id)
);
```

**模型/effort：Sonnet medium**（migration 模板化）。

---

## Phase A：Layer 1 RAG 召回品質評估

### 目標
量化 FTS5 + 向量召回的 Context Precision / Recall，回答「中文召回是否足夠」這個歷史疑問。

### 關鍵檔案
- `layer_1_memory/lib/rag.py`（`retrieve_relevant_sessions:28-90`、`_vector_search:164-212`、`_build_exchange_context:215-227`）
- `layer_1_memory/db/schema.sql:202-213`（exchange_embeddings 表）

### A.1 結構化召回三元組擷取（Sonnet medium）
- 在 `rag.py` 加 read-only API：`retrieve_for_eval(query) -> {query, retrieved_contexts: list[str], retrieved_session_uuids: list[str]}`
- 不動原 `retrieve_relevant_sessions` 的 Markdown 輸出，新增結構化平行版本
- 避免 hot path 改動 → stop_hook 注入路徑不受影響

### A.2 Golden Set 建構（Opus high，需 Shiba 人工標註）

**2026-05-18 設計調整**（plan 原假設與實際資料不符）：
- ❌ Plan 原計：「從 100 個 session 摘要挑 5 個最相關」
- ❌ 實際：`sessions.context_summary` 全部 NULL（200 個 sessions 無摘要）
- ✅ 改用：`exchange_embeddings.instruction`（1133 個 distinct，已正規化）作為 query 與候選池來源

**修訂後流程**：
1. **Query 抽樣**：從 `exchange_embeddings.instruction` 抽 30 筆（長度 8-50 字、去重、排除黑名單如「ok」「繼續」、排除高發散 instruction）
2. **候選池建構**：對每個 query 跑 `_vector_search` top 15 + FTS5 top 5（hybrid），合併去重後得 6-20 個候選
3. **標註模式**：**Claude Pro 對話貼**（Shiba 無 Anthropic API key，且僅 30 筆一次性 → 不需自動化）
   - 流程：`golden_set_builder.py --action preview` 生 30 個 prompt → 分批 5-10 個貼進 Claude 對話 → Claude 回 JSON → `--action import-json` 寫回 DB
   - 標註器 annotator 欄位記 `claude-pro-chat-sonnet-4-6`
4. **Shiba 人工複核**：列出 auto-annotated 項目，Shiba 確認後改 annotator 為 `shiba`

**實作位置**：`evaluation/golden_set_builder.py`（已建立 sample / preview / annotate / review 四個 action；annotate action 暫不使用 API，預留供未來改造）

- 為何 Opus high：標註 prompt 設計（判斷標準、寧缺勿濫原則、JSON 結構）決定 Phase A 全部品質基線

### A.3 RAGAS Runner（Sonnet medium）
- `evaluation/ragas_runner.py::run_layer1_evaluation()`
- 套用指標：**Context Precision、Context Recall、Context Entity Recall**
- 評估器 LLM：Claude Sonnet 4.6
- 結果寫入 `evaluation_results`，並輸出 `evaluation/reports/layer1_YYYY-MM-DD.md`

### A.4 基線與目標（Haiku low，純報告）
- 跑首輪 baseline，記錄當前指標
- 設目標：Context Recall ≥ 0.7（業界 RAG 起點），Precision ≥ 0.6
- 若不達標 → 觸發後續優化（換 embedding 模型 / 調 cosine threshold / 加 hybrid rerank）

### A.5 驗證
```bash
# 1. unit test: structured retrieval API
pytest tests/memory/test_rag_eval.py -v

# 2. 跑 baseline evaluation
python -m evaluation.ragas_runner --phase layer1 --sample-size 30

# 3. 檢查報告
cat evaluation/reports/layer1_$(date +%Y-%m-%d).md

# 4. 檢查 DB 寫入
sqlite3 data/shiba-brain.db "SELECT metric_name, AVG(metric_value) FROM evaluation_results WHERE phase='layer1' GROUP BY metric_name"
```

---

## Phase B：Layer 2 Judge 可靠性評估

### 目標
量化三方投票的內部一致性（過去從未測過），找出哪類 sample judge 容易意見分歧。

### 關鍵檔案
- `layer_2_chamber/backend/services/multi_judge.py:30-92`
- `layer_2_chamber/backend/services/teacher_service.py:26-89`（`_SCORE_PROMPT`）

### B.1 votes 持久化擴充（Sonnet medium）
- `multi_judge.py:46` votes list 蒐集後，新增 `_log_judge_agreement(conn, sample_id, votes)` 寫入 `judge_agreement_logs`
- **不動現有 multi_judge_score 主流程**，只在 commit 前追加 log（避免影響 PR2 剛穩定的事務）

### B.2 Fleiss' Kappa 計算（Sonnet medium）
- `evaluation/agreement.py::compute_fleiss_kappa(votes_json) -> float`
- 三 judge × 二元分類（≥8 vs <8）→ kappa
- 同時記錄 pairwise disagreement（哪兩位 judge 不合）

### B.3 RAGAS Faithfulness 套用（Sonnet medium）
- 對每筆 training_samples（instruction + output）跑 RAGAS Faithfulness
- 評估器：Claude Sonnet 4.6
- 比對「judge 給 ≥8」與「RAGAS Faithfulness ≥ 0.8」的一致率
- 找出 judge 過寬 / 過嚴的盲區

### B.4 報告與決策（Haiku low）
- 輸出：`evaluation/reports/layer2_judge_reliability.md`
- 觸發決策：若 Fleiss' Kappa < 0.4（poor agreement），檢討 `_SCORE_PROMPT` 校準範例

### B.5 驗證
```bash
# 1. 跑 100 筆既有 training_samples 的 judge 一致性
python -m evaluation.ragas_runner --phase layer2 --limit 100

# 2. 查 kappa 分佈
sqlite3 data/shiba-brain.db "SELECT ROUND(fleiss_kappa,1) k, COUNT(*) FROM judge_agreement_logs GROUP BY k ORDER BY k"

# 3. 查 judge vs RAGAS 衝突 sample
sqlite3 data/shiba-brain.db "SELECT sample_id, fleiss_kappa, ragas_faithfulness FROM judge_agreement_logs WHERE ragas_faithfulness < 0.5 AND fleiss_kappa > 0.7 LIMIT 10"
```

---

## Phase C：End-to-End RAG 表現

### 目標
量化「Claude / Ollama 收到 Layer 1 注入 context 後的回答品質」，建立 fine-tuning 前後對比基線。

### 前置
Phase A 的 `retrieval_golden_set` 須擴充為「query + expected_answer」（Phase A 只標 session，C 要加標準答案）。

### C.1 Golden Q&A 擴充（Opus high）
- 在 `retrieval_golden_set` 新增 `expected_answer TEXT` 欄位（migration）
- 對 30-50 筆 query，由 Shiba 人工撰寫標準答案（或 Claude 草稿 + 人工複核）

### C.2 End-to-End Pipeline（Sonnet medium）
- `evaluation/ragas_runner.py::run_e2e_evaluation()`
- 流程：query → Layer 1 retrieve → 注入 prompt → 呼叫 Claude / Ollama → 收 response → RAGAS 評估
- 指標：**Faithfulness、Answer Relevancy、Answer Correctness、Answer Semantic Similarity**

### C.3 雙模型基線（Sonnet medium）
- 同時跑 Claude（baseline）和 Ollama qwen3:30b-a3b（當前主力）
- 對比指標差距 → 量化「Ollama 還差多少」
- 未來 Layer 3 fine-tuned 模型上線後，可用同一套 golden set 跑回歸

### C.4 CI 採樣機制（Haiku low）
- 每週日晚跑 batch 10 筆（成本 ~$0.2/週）
- 結果寫 `evaluation_results`，超出閾值降幅觸發 alert（重用既有 `services/alerts.py` 機制，若存在）

### C.5 驗證
```bash
# 1. 跑端到端 baseline（Claude vs Ollama）
python -m evaluation.ragas_runner --phase e2e --models claude,ollama-qwen3-30b

# 2. 查模型差距
sqlite3 data/shiba-brain.db "SELECT evaluator_model, metric_name, AVG(metric_value) FROM evaluation_results WHERE phase='e2e' GROUP BY evaluator_model, metric_name"

# 3. 報告
cat evaluation/reports/e2e_baseline_$(date +%Y-%m-%d).md
```

---

## 成本與風險

### 成本估算（2026-05-18 修訂：本地 judge 為主）
| Phase | 樣本數 | judge | 預估成本（一次） |
|-------|--------|-------|----------------|
| A.2 標註 | 30 queries | Claude Pro 對話貼 | $0（訂閱內含） |
| A.3 評估 | 30-50 × 3 metrics | 本地 qwen3:30b-a3b | $0（本地 GPU） |
| B | 100 samples × Faithfulness | 本地 qwen3:30b-a3b | $0 |
| C.2-C.3 | 50 Q&A × 4 metrics × 2 models | 商業 API（建議 Gemini Pro）| ~$5-10 |
| **首輪總計** | | | **~$5-10**（原估 $15-20）|
| C.4 CI 週度採樣 | 10 筆/週 | 商業 API | ~$0.5/週 |

**節省關鍵**：A + B 全部走本地 Ollama，僅 C 需 API。前置不需先儲值 API key，可在 A + B 跑完並驗證 RAGAS 機制可行後，再決定 C 是否啟動 + 採購 key。

### 風險清單
1. **繁中評估精度**：RAGAS prompt 原生英文，需自訂繁中 prompt template；若 Claude 評分對繁中有 bias，需用「Claude vs 人工複核」校準前 20 筆
2. **Golden set 標註人力**：A.2 + C.1 需 Shiba 投入 ~3-4 小時人工
3. **評估漂移**：Claude 模型版本升級可能讓歷史 baseline 失準 → `evaluation_results.evaluator_model` 欄位已記錄，可分版本比對
4. **不可動 hot path**：B.1 votes log 寫入需用 try/except 包住，失敗不能炸 multi_judge_score 主流程

---

## 模型 / effort 切換建議

| Phase | 步驟 | /model | /effort | 理由 |
|-------|------|--------|---------|------|
| 0.2-0.3 | 基礎設施 | Sonnet | medium | 模板化工作 |
| A.1 | 結構化召回 API | Sonnet | medium | 既有函式擴充 |
| A.2 | Golden set 建構 | **Opus** | **high** | 標註策略與 prompt 設計需深思 |
| A.3 | Layer 1 runner | Sonnet | medium | 直接呼叫 RAGAS |
| A.4 / B.4 / C.4 | 報告與決策 | Haiku | low | 純整理輸出 |
| B.1-B.3 | Judge 一致性 | Sonnet | medium | 統計與整合 |
| C.1 | E2E Golden Q&A | **Opus** | **high** | 標準答案的撰寫品質決定整個 Phase C 的基線 |
| C.2-C.3 | E2E pipeline | Sonnet | medium | pipeline 黏合 |

---

## 完成後動作（出自全域 CLAUDE.md）

1. 驗證通過 → 刪除本 plan 檔（移到 `docs/archive/plans/` 後也一併清除草稿）
2. 更新 CHANGELOG.md（SemVer：v1.6.0 minor，新增 evaluation harness）
3. 更新 `MEMORY.md`：新增 `project_ragas_evaluation.md`，記錄首輪 baseline 數值
4. 退場條件：Layer 3 fine-tuning 第二輪迭代後，若 RAGAS 指標連續 3 週無變化趨勢，重新檢討 metric 選用

---

## 切勿做的事

- ❌ 跳過 PR2 直接動本計畫（Shiba 已明確指示時機）
- ❌ 把 RAGAS 評估同步嵌入 stop_hook / multi_judge_score 主流程（會放大 latency 並引入新事務）
- ❌ 把 ground truth 自動由 Claude 全權生成而不經 Shiba 複核（Garbage In, Garbage Out）
- ❌ 改 `multi_judge.py:77-84` 主事務（PR2 才剛穩定下來）
- ❌ Phase A / B 一律預設用商業 API（本地 qwen3:30b-a3b 已達 judge 門檻，先試本地再評估是否升級）
- ❌ Phase B judge 用 Gemini 系（被評對象 multi_judge 用 Gemini Flash + Flash-Lite，會循環依賴）
