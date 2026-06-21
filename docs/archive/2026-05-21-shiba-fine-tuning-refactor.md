# shiba-fine-tuning-project — 核心瘦身與功能模組化重構 Spec

> 對應討論：2026-05-21
> 目標：把已開發的「研究/實驗」功能從核心 phase 0-3 抽離，做成可由 config 開關的獨立模組，並讓 DB schema 對應解耦（核心 schema 不引用 feature 表；feature 表加模組前綴）。
> 同時為未來「新模型上線後快速接管既有訓練資料」鋪路（前端模型切換 + 每模型獨立 yaml，已有 `model_registry`，本次不重做）。

---

## 1. 目標 / 非目標

### 1.1 目標
- **G1**：把「核心 phase 0-3」（最小閉環：Hook → Bridge → Scoring → Trigger → Update）與「新功能模組」明確劃分，主幹只留閉環必要程式。
- **G2**：全域 `config/shiba.yaml` 新增 `features:` 區塊，每個新功能一個布林開關，預設全 `false`。
- **G3**：每個 feature 的 DB schema 獨立成檔，表名加模組前綴；核心 schema 不依賴 feature 表（單向：feature → core 可，反向禁止）。
- **G4**：消除目前已盤點到的 5 條反向耦合（見 §3.2）。
- **G5**：研究方向（gatekeeper / ebbinghaus / ragas / multi-judge v2 / paraphrase / advanced compressor / golden retention）各自獨立資料夾，便於日後直接 archive 或 spin-off。

### 1.2 非目標（本次不做）
- 不重寫 `model_registry`、不改前端模型切換 UX（已有設計，待新模型上線時依需求微調 yaml）。
- 不引入 HippoRAG / 知識圖譜（純規劃，無現存 code）。
- 不訂「7/14/30 天」時程表（工作節奏不固定）；改以 **PR 依賴序** 推進。
- 不採納「建議注入以外」的進階模式（先記錄，本階段不考慮）。

---

## 2. 模組分類

### 2.1 核心 phase 0-3（保留在主幹）

| Layer | 檔案 / 模組 | 核心 DB Tables |
|---|---|---|
| **0 Router** | `layer_0_router/{classifier,router,telemetry}.py` + `compressor.py`（**basic 分支**） | `router_decisions` |
| **1 Memory** | `layer_1_memory/hooks/session_stop_hook.py`、`lib/{parser,db,exchanges,rag,embedder}.py` | `projects / sessions / branches / messages / tool_executions / exchanges / exchange_messages / exchange_embeddings / sessions_fts` |
| **2 Chamber** | `extraction/{pipeline,dataset_formatter}.py`、`services/{teacher_service,refiner_service}.py`、`services/multi_judge.py`（**basic 三方多數**）、`api/*` | `teachers / question_sets / questions / training_samples / teacher_usage_logs / ai_api_call_logs / model_registry` |
| **3 Pipeline** | `runner.py / mlx_trainer.py / gguf_converter.py / ollama_updater.py / server.py` + `trigger_policy_basic`（**固定 approved≥30**） | `finetune_runs` |
| **共用** | `shiba_config.py / shiba_db.py / clients/* / config/models/*` | — |

### 2.2 新功能模組（搬入 `modules/<topic>/`，feature flag 控制）

| Flag | 模組目錄 | 主要程式來源 | 專屬 DB Tables（前綴） |
|---|---|---|---|
| `shadow_gatekeeper` | `modules/gatekeeper/` | `layer_3_pipeline/gatekeeper.py` | `gatekeeper_golden_samples`（合併 retention） |
| `ebbinghaus_trigger` | `modules/ebbinghaus_trigger/` | `layer_3_pipeline/trigger_policy.py` | （無新表，純讀核心） |
| `ragas_eval` | `modules/ragas/` | `evaluation/*`（全 11 檔）+ `com.shiba.ragas-c4.plist` + `setup_c4_launchd.sh` | `ragas_runs / ragas_results / ragas_golden_set` |
| `multi_judge_v2` | `modules/multi_judge_v2/` | 從 `services/multi_judge.py` 抽出進階分支（vendor 多樣強制 / Fleiss kappa / 寫 log） | `multi_judge_v2_agreement_logs` |
| `paraphrase_service` | `modules/paraphrase/` | `services/paraphrase_service.py` + `evaluation/backfill_bge_m3.py` 內的 paraphrase 段 | `paraphrase_variant_sources`（FK → `exchange_embeddings.id`） |
| `advanced_compressor` | `modules/advanced_compressor/` | `compressor.py` 內的進階分支 | — |
| `golden_retention` | （併入 `modules/gatekeeper/`） | gatekeeper 子能力 | 共用 `gatekeeper_golden_samples` |

> **依賴關係（解耦後）**：
> - `gatekeeper` 依賴：核心 `finetune_runs / messages / training_samples`（單向 ✓）
> - `ebbinghaus_trigger` 依賴：核心 `finetune_runs / router_decisions / exchange_embeddings / training_samples`（單向 ✓）
> - `ragas` 依賴：核心 `training_samples / exchanges`、可選依賴 `multi_judge_v2_agreement_logs`（off 時降級為單 judge 數據）
> - `multi_judge_v2` 依賴：核心 `training_samples / teachers`
> - `paraphrase` 依賴：核心 `exchange_embeddings`
> - `advanced_compressor` 依賴：核心 `clients/ollama/`
> - **核心不引用任何 module 表或 module 函式**（單向強制）

### 2.3 預期刪除 / Archive

| 路徑 | 處理 |
|---|---|
| `evaluation/migration_evaluation.sql` | 拆為 `modules/ragas/db/ragas.sql` 與 `modules/multi_judge_v2/db/multi_judge_v2.sql` 後刪 |
| `evaluation/` 整批 | 搬至 `modules/ragas/`；原目錄移除 |
| `layer_2_chamber/backend/core/config.py` 內 `golden_samples` migration 區段 | 移至 `modules/gatekeeper/migrations.py` |
| `frontend/_legacy_react_cdn/` | 已被 `frontend-vue/` 取代；本 PR 序末段獨立 PR archive |

---

## 3. 現有耦合違規與解耦動作

### 3.1 違規盤點（grep 實證）

| # | 違規描述 | 證據位置 |
|---|---|---|
| V1 | 核心 `multi_judge.py` 直接 INSERT `judge_agreement_logs`（feature 表） | `layer_2_chamber/backend/services/multi_judge.py:115` |
| V2 | 核心 `exchange_embeddings` 表含 paraphrase 專屬欄位 `source_instruction` | `layer_1_memory/db/schema.sql:206` |
| V3 | 核心 `lib/db.py` 與 `scripts/backfill_embeddings.py` 讀寫 `source_instruction` | `layer_1_memory/lib/db.py`、`scripts/backfill_embeddings.py` |
| V4 | RAGAS 模組碰 Paraphrase 欄位 | `evaluation/backfill_bge_m3.py`、`evaluation/migration_exchange_id_link.py` |
| V5 | 核心 `core/config.py` 在 startup migration 建 `golden_samples`（feature 表） | `layer_2_chamber/backend/core/config.py` |
| V6 | `finetune_runs` DDL 同時出現在 `layer_1_memory/db/schema.sql:247` 與 `layer_3_pipeline/server.py`（雙重來源） | 兩處 `CREATE TABLE finetune_runs` |

### 3.2 解耦動作對照

| 違規 | 解耦動作 |
|---|---|
| V1 | `services/multi_judge.py` 留 v1（單純三方多數，不寫 log）；vendor 多樣 / Fleiss kappa / log 寫入搬到 `modules/multi_judge_v2/judge_v2.py`，由 flag on 時注入 |
| V2 / V3 | `exchange_embeddings.source_instruction` 欄位拆出，改建 `paraphrase_variant_sources(id, embedding_id FK, source_instruction)`；核心 `lib/db.py` 不再認識此欄位 |
| V4 | `modules/paraphrase/backfill.py` 接管同義變體 backfill；`modules/ragas/backfill_bge_m3.py` 只處理 embedding 升級，不碰變體 |
| V5 | `core/config.py` 不再 migrate `golden_samples`；改由 `feature_registry` 在 `shadow_gatekeeper=true` 時套 `modules/gatekeeper/db/gatekeeper.sql` |
| V6 | 統一 `finetune_runs` DDL 至 `config/db/schema_core.sql`；`server.py` 內重複 DDL 移除 |

---

## 4. Feature Flag 規範

### 4.1 yaml 區塊（新增至 `config/shiba.yaml`）

```yaml
features:
  shadow_gatekeeper:      false   # Layer 3 A/B 守門（依賴 golden_retention，需共開）
  ebbinghaus_trigger:     false   # Layer 3 動態觸發；off=固定 approved≥30
  ragas_eval:             false   # 全套評估框架（含 weekly CI launchd）
  multi_judge_v2:         false   # off=三方多數投票無 log
  paraphrase_service:     false   # off=不建 paraphrase_variant_sources 表
  advanced_compressor:    false   # off=Layer 0 直接 truncate
  golden_retention:       false   # 必須與 shadow_gatekeeper 同時 on（registry 強制檢核）
```

### 4.2 `shiba_config.py` 對應擴充

```python
@dataclass(frozen=True, slots=True)
class Features:
    shadow_gatekeeper: bool
    ebbinghaus_trigger: bool
    ragas_eval: bool
    multi_judge_v2: bool
    paraphrase_service: bool
    advanced_compressor: bool
    golden_retention: bool
```

`CONFIG.features.<name>` 全部 frozen，runtime 不可變；缺鍵 fail fast。

### 4.3 Feature Registry（新增 `core/feature_registry.py`）

每個模組註冊：
```python
register(
    name="gatekeeper",
    flag="shadow_gatekeeper",
    schema_files=["modules/gatekeeper/db/gatekeeper.sql"],
    depends_on=["golden_retention"],   # 必須同時 on
    init_fn=lambda conn: ...,           # 套 schema + 註冊 API route
)
```

啟動流程（在 `layer_2_chamber/backend/main.py` lifespan）：
1. 讀 `CONFIG.features.*`
2. 拓撲序檢查依賴；違反 → fail fast
3. 對 flag=on 的模組：執行 `init_fn`（套 schema、註冊 router、啟 background job）
4. 對 flag=off：不 import 任何 module code（避免副作用），不套 schema

**SOLID 對應**：OCP — 新增 feature 不改主幹，僅新增 module 與 registry entry；DIP — 主幹依賴 registry 抽象，不依賴具體 feature 實作。

---

## 5. 目錄重組

### 5.1 重組後結構

```
shiba-fine-tuning-project/
├── core/                              # ← 新增：跨 layer 共用基礎
│   ├── feature_registry.py            # 新增
│   ├── (shiba_config.py 暫不搬，避免大規模 import 影響)
│   └── (shiba_db.py 暫不搬)
├── config/
│   ├── shiba.yaml                     # +features: 區塊
│   ├── db/
│   │   ├── schema_core.sql            # ← 整併 layer_1/2 schema + finetune_runs
│   │   └── schema_model_registry.sql  # 既有
│   └── models/                        # 既有
├── layer_0_router/
│   ├── classifier.py
│   ├── compressor.py                  # 只留 basic；advanced 抽離
│   ├── router.py
│   └── telemetry.py
├── layer_1_memory/
│   ├── hooks/
│   ├── lib/                           # db.py 移除 source_instruction 認知
│   └── (db/schema.sql 刪除，集中至 config/db/schema_core.sql)
├── layer_2_chamber/
│   └── backend/
│       ├── extraction/
│       ├── services/
│       │   ├── multi_judge.py         # v1 basic
│       │   ├── teacher_service.py
│       │   └── refiner_service.py     # (paraphrase 搬走)
│       ├── api/                       # 既有
│       └── core/
│           └── config.py              # 拆掉 golden_samples migration
├── layer_3_pipeline/
│   ├── runner.py
│   ├── mlx_trainer.py
│   ├── gguf_converter.py
│   ├── ollama_updater.py
│   ├── server.py                      # 移除重複的 finetune_runs DDL
│   ├── trigger_policy_basic.py        # ← 抽出固定門檻版
│   └── (gatekeeper.py / trigger_policy.py 搬走)
├── modules/                           # ← 新增頂層
│   ├── gatekeeper/
│   │   ├── __init__.py
│   │   ├── service.py                 # 原 gatekeeper.py
│   │   ├── db/gatekeeper.sql          # gatekeeper_golden_samples
│   │   ├── migrations.py              # 從 core/config.py 搬入
│   │   └── tests/
│   ├── ebbinghaus_trigger/
│   │   ├── service.py                 # 原 trigger_policy.py
│   │   └── tests/
│   ├── ragas/
│   │   ├── (evaluation/* 整批搬入)
│   │   ├── db/ragas.sql               # ragas_runs/ragas_results/ragas_golden_set
│   │   └── launchd/
│   │       ├── com.shiba.ragas-c4.plist
│   │       └── setup_c4_launchd.sh
│   ├── multi_judge_v2/
│   │   ├── judge_v2.py                # vendor 多樣 / Fleiss / 寫 log
│   │   ├── db/multi_judge_v2.sql      # multi_judge_v2_agreement_logs
│   │   └── tests/
│   ├── paraphrase/
│   │   ├── service.py
│   │   ├── backfill.py
│   │   └── db/paraphrase.sql          # paraphrase_variant_sources
│   └── advanced_compressor/
│       └── compressor_advanced.py
├── tests/                             # 核心 layer 測試保留主幹
├── scripts/
├── tools/
├── docs/
├── data/                              # 既有
├── docker-compose.yml
└── README.md
```

### 5.2 表名前綴對照

| 現名 | 重構後 |
|---|---|
| `golden_samples` | `gatekeeper_golden_samples` |
| `evaluation_runs` | `ragas_runs` |
| `evaluation_results` | `ragas_results` |
| `retrieval_golden_set` | `ragas_golden_set` |
| `judge_agreement_logs` | `multi_judge_v2_agreement_logs` |
| `exchange_embeddings.source_instruction`（欄位） | `paraphrase_variant_sources`（**獨立表**） |

> **migration 策略**：每個改名走 `CREATE new + INSERT...SELECT + DROP old`（不 RENAME，避免 FTS5/索引狀態問題）。每次只動一張表，逐 PR 驗證。

---

## 6. PR 依賴序（每 PR 一件小事）

> 命名遵循專案規範：`pr-o-<slug>`（o = Refactor「**O**rganize Modules」）。Commit 風格不變。

### 6.0 每個「模組搬遷 PR」的 Definition of Done（強制）

> 適用於 PR-O-3 / -4 / -5 / -6 / -7 / -8（任何把功能搬到 `modules/` 的 PR）。
> **未通過下列兩階段測試，不得合併。**

**Stage A — 全關回歸**：
```yaml
# config/shiba.yaml
features:
  <all>: false
```
- 跑核心閉環 smoke test（Hook → Bridge → Score → Trigger → Update）
- 跑 `tests/` 既有測試全綠
- DB 啟動時不得建任何 `modules/` 表（`sqlite3 data/shiba-brain.db ".tables"` 結果不含 module 表）
- `import` 不得載入任何 `modules/<topic>/` 路徑（用 `sys.modules` 斷言）

**Stage B — 單一啟用隔離測試**：
```yaml
features:
  <本 PR 對應 flag>: true   # 只開這一個
  <其他全部>:          false
```
- 該模組單元 + 整合測試全綠
- 核心閉環 smoke test 仍綠（**確認本模組沒污染核心路徑**）
- 跑 grep 規則驗證（§11）：feature 表名只出現在 `modules/` 與 `data/shiba-brain.db`，不出現在核心 layer 目錄
- 該模組關閉後重跑 Stage A，DB 內 module 表保留（不誤刪），但程式碼路徑不再 import

**測試 artifact 落地**：每個 PR 在 `modules/<topic>/tests/verify_isolation.py` 留一支腳本，未來 regression 時可重跑。



### PR-O-1：基礎設施（前置）
- 新增 `core/feature_registry.py`（空 registry + lifecycle hook）
- 新增 `config/db/schema_core.sql`（先複製 `layer_1_memory/db/schema.sql` + `layer_2_chamber/backend/db/schema_layer2.sql` 內**僅核心表**）
- `shiba_config.py` 新增 `Features` dataclass + yaml `features:` 區塊（全 false）
- **此 PR 不刪舊檔**；雙寫並存，由後續 PR 切換
- **/model: sonnet　/effort: medium**

### PR-O-2：解 V6（`finetune_runs` 雙重 DDL）
- 移除 `layer_3_pipeline/server.py` 內 `CREATE TABLE finetune_runs`
- 移除 `layer_1_memory/db/schema.sql:247-271` 對應段
- 統一由 `config/db/schema_core.sql` 提供
- **/model: haiku　/effort: low**　（可委派 `Agent: general-purpose` 處理）

### PR-O-3：抽出 gatekeeper 至 `modules/gatekeeper/`
- 搬 `layer_3_pipeline/gatekeeper.py` → `modules/gatekeeper/service.py`
- 新增 `modules/gatekeeper/db/gatekeeper.sql`（`gatekeeper_golden_samples`，附 migration `INSERT...SELECT FROM golden_samples`）
- 解 V5：`backend/core/config.py` 移除 golden migration
- registry 註冊 `shadow_gatekeeper + golden_retention` 同時 on 才生效
- 更新 `tests/layer3/test_gatekeeper_retention.py` import 路徑
- **/model: sonnet　/effort: medium**

### PR-O-4：抽出 ebbinghaus trigger
- 新增 `layer_3_pipeline/trigger_policy_basic.py`（核心固定 approved≥30 + Ebbinghaus 信號 A 簡化版可保留 / 或全拿掉，由 Shiba 決）
- 搬 `layer_3_pipeline/trigger_policy.py` → `modules/ebbinghaus_trigger/service.py`
- `runner.py` 改依 `CONFIG.features.ebbinghaus_trigger` 選 basic / v2
- **/model: sonnet　/effort: medium**

### PR-O-5：拆 multi_judge_v2（解 V1）
- `services/multi_judge.py` 留 v1（三方多數，不寫 log）
- 抽 vendor 多樣強制 / Fleiss / `INSERT judge_agreement_logs` 至 `modules/multi_judge_v2/judge_v2.py`
- 新增 `modules/multi_judge_v2/db/multi_judge_v2.sql`，建 `multi_judge_v2_agreement_logs`（INSERT...SELECT 自舊 `judge_agreement_logs`）
- 注入點：teacher_service 呼叫 judge 時，依 flag 走 v1 或 v2 strategy（DIP — 主幹依賴 `JudgeStrategy` 介面）
- **/model: opus　/effort: high**　（介面設計 + strategy 抽象核心）

### PR-O-6：搬 ragas 至 `modules/ragas/`
- `evaluation/*`、`com.shiba.ragas-c4.plist`、`setup_c4_launchd.sh` 整批 `git mv` 至 `modules/ragas/`
- 拆 `migration_evaluation.sql` 為 `ragas.sql`（拿掉 `judge_agreement_logs`）
- 表名加 `ragas_` 前綴（INSERT...SELECT 改名）
- `c4_weekly_ci.py` 內 launchd 路徑同步更新
- **/model: sonnet　/effort: medium**　（含改名範圍大，建議分 6a/6b：6a 純搬遷，6b 改表名）

### PR-O-7：解 V2 / V3 / V4（paraphrase 完全解耦）
- 新增 `modules/paraphrase/db/paraphrase.sql` 建 `paraphrase_variant_sources(id, embedding_id FK exchange_embeddings(id), source_instruction TEXT)`
- migration：`INSERT INTO paraphrase_variant_sources SELECT id, source_instruction FROM exchange_embeddings WHERE source_instruction IS NOT NULL`
- 搬 `services/paraphrase_service.py` → `modules/paraphrase/service.py`，改讀新表
- 核心 `lib/db.py` / `scripts/backfill_embeddings.py` 移除 `source_instruction` 認知
- `evaluation/backfill_bge_m3.py` paraphrase 段移到 `modules/paraphrase/backfill.py`
- **最終 migration**：`ALTER TABLE exchange_embeddings DROP COLUMN source_instruction`（SQLite 3.35+ 支援）
- ⚠ 違反 SRP 風險最高的 PR，建議獨立驗證 2-3 個 RAGAS run 後才 DROP COLUMN
- **/model: opus　/effort: high**

### PR-O-8：advanced_compressor
- 抽 `compressor.py` 內進階分支至 `modules/advanced_compressor/`
- 核心 compressor 留 basic（直接 truncate 或單純 prompt）
- **/model: haiku　/effort: low**　（可委派 Agent）

### PR-O-9：清理舊路徑
- 刪除 `layer_1_memory/db/schema.sql`、`layer_2_chamber/backend/db/schema_layer2.sql`、`evaluation/migration_evaluation.sql`
- 刪除 `frontend/_legacy_react_cdn/`
- 更新 README / CHANGELOG / docker-compose 路徑（如有）
- **/model: haiku　/effort: low**

### PR-O-10：feature flag 文件與驗證
- `docs/features.md`：每個 flag 用途 / 依賴 / 開啟後副作用
- 整合測試：分別跑 all-false（純核心）、all-true、典型組合三套
- **/model: sonnet　/effort: medium**

---

## 7. 推薦 /model 與 /effort 切換時機

| 階段 | 工作型態 | /model | /effort | 備註 |
|---|---|---|---|---|
| 設計階段（本 spec） | 架構審視、依賴推演 | **opus** | **high** | SOLID 邊界 / 反向耦合判定 |
| PR-O-1, -2, -8, -9 | 樣板 / git mv / DDL 整併 | **sonnet** 或 **haiku** | medium / low | 可委派 Agent（`general-purpose`）執行 + 自驗 |
| PR-O-3, -4, -6, -10 | 模組搬遷 + flag 接線 | **sonnet** | **medium** | 含 import 路徑大改 |
| PR-O-5, -7 | strategy 介面 / schema 拆欄位 | **opus** | **high** | 高風險：介面設計、SQLite ALTER 不可逆 |
| 收尾 / commit / changelog | 文件整理 | **haiku** | **low** | — |

---

## 8. Agent / Plugin / Skill 使用建議

- **PR-O-2 / -8 / -9**：可委派 `Agent: general-purpose` 在 worktree 內執行（純檔案移動 + grep 替換）。Shiba 只 review diff。
- **PR-O-5 / -7**：opus high 親自設計介面與 migration SQL；不委派。
- **跨 PR 驗證**：用 `Agent: pr-review-toolkit:silent-failure-hunter` 掃 feature flag off 路徑是否有 fallback 默默吞錯。
- **Skill 使用**：
  - 每個 PR 起手 → `superpowers:writing-plans`（單 PR 計畫）
  - PR 完成 → `pr-review-toolkit:code-reviewer` + `comment-analyzer`
  - DB schema 變更 → `verify-shiba-db`
- **不用**：本次重構不涉及前端 UI 視覺，不用 `frontend-design`；不涉及 dag/airflow。

---

## 9. 風險與回退

| 風險 | 機率 | 影響 | 緩解 |
|---|---|---|---|
| PR-O-7 `DROP COLUMN source_instruction` 後資料遺失 | 低 | 高 | DROP 前必須完成 backfill 驗證；DB backup 由 `scripts/db_backup.sh` 強制 |
| flag=off 時 import 殘留副作用 | 中 | 中 | registry lifecycle 內 lazy import；off 時 module path 不進 `sys.modules` |
| 表改名期間 `INSERT...SELECT` 中斷 | 低 | 中 | 每張表獨立 PR；migration 包在 transaction 內，失敗自動 rollback |
| 既有 baseline（PR-N golden set 65）失效 | 中 | 中 | RAGAS migration 完成後重跑 n50-baseline，建立新基準線；舊基準存檔備查 |
| frontend 模型切換 UI 對接舊表名 | 低 | 低 | 模型切換走 `model_registry`，與本次重構表無交集 |

**全 PR 回退方法**：每個 PR 獨立可 revert（branch 命名 `pr-o-N-...`）；schema 改名 PR 附 `down_migration.sql` 反向腳本。

---

## 10. 未來方向（備忘，本次不做）

- **新模型快速接管既有訓練資料**：靠 `model_registry` + 統一 yaml schema；訓練資料表（`training_samples`）已 model-agnostic（Alpaca instruction/input/output 三欄），新模型只需新增一筆 yaml + `is_current` 切換即可。
- **前端模型無縫切換**：現有 frontend-vue 已能讀 `model_registry`；待新模型實際上線時，依 yaml 規範（含 inference / prompt / training / meta / maintenance 五區塊）補新檔。
- **「建議注入」以外的模式**：先記錄（如 shadow merge / prompt rewriting / RAG 之外的 in-context tool memory），本階段不採納。

---

## 11. 驗收標準

### 11.1 全程強約束（每個模組 PR 都必須過）

- [ ] **全關回歸**：`features.*` 全 false 時，核心閉環（Hook → Bridge → Score → Trigger → Update）端到端跑通；既有 `tests/` 全綠
- [ ] **單一啟用隔離**：對每個 module，僅開該 flag、其餘全 false 時：
  - [ ] 該模組單元 + 整合測試全綠
  - [ ] 核心 smoke test 仍綠（無功能性副作用滲入核心）
  - [ ] 無新表洩漏到核心 layer 目錄的程式碼或 schema
- [ ] 上述兩階段測試結果寫進 PR 描述（`modules/<topic>/tests/verify_isolation.py` 的輸出）

### 11.2 結構約束（重構結束時整體驗收）

- [ ] `config/db/schema_core.sql` 內任何表的 FK 不指向 `modules/` 任何 schema
- [ ] grep 規則回傳零筆：
  ```bash
  grep -rn "gatekeeper_golden_samples\|ragas_runs\|ragas_results\|ragas_golden_set\|multi_judge_v2_agreement_logs\|paraphrase_variant_sources" \
    layer_0_router/ layer_1_memory/ layer_2_chamber/ layer_3_pipeline/ core/ clients/ scripts/ tools/
  ```
- [ ] grep 規則回傳零筆：核心目錄不得 import `modules/`
  ```bash
  grep -rn "from modules\.\|import modules\." \
    layer_0_router/ layer_1_memory/ layer_2_chamber/ layer_3_pipeline/ core/
  ```
  （allowed only in `main.py` lifespan via `feature_registry`）

### 11.3 組合矩陣驗收（PR-O-10 收尾）

| 組合情境 | 期望 |
|---|---|
| 全 false | 核心閉環綠；DB 僅含核心表 |
| 每個 flag 單獨 on（× N 次） | 核心閉環綠 + 該模組綠 |
| `shadow_gatekeeper=true` 但 `golden_retention=false` | registry fail fast（依賴違反） |
| 全 true | 全部測試綠；無 lifecycle 衝突 |

### 11.4 文件 / 版號

- [ ] CHANGELOG 記錄表改名對照與每個 PR 的 Stage A/B 驗證結果摘要
- [ ] 版號跳 v2.0.0（breaking schema：表改名 + drop column）
