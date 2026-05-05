# Plan：shiba-fine-tuning-project 系統設計與初始化

## Context

這次對話在 real-estate-project 目錄下進行，但主題與其完全無關。
目標是設計一套**個人 AI 分流與自我進化系統**，讓本地 Ollama 模型透過：
1. 每日對話記憶累積（省 token）
2. 定期「精神時光屋」訓練（提升本地模型能力）

逐步接手 Claude 的重複性、常規性任務，讓 Claude 專注在高價值工作。

---

## 批判性評估後的架構修正（2026-04-15）

### 已修正的關鍵問題

| # | 問題 | 修正方向 |
|---|------|---------|
| 1 | Layer 1 單點故障（Spring Boot 未啟動 → 記憶靜默失失） | Hook fallback：寫本地 queue 檔案，Spring Boot 起來後補同步 |
| 2 | 兩個 DB 邊界不清 | 統一為單一 SQLite：`~/.local-brain/shiba-brain.db` |
| 3 | Layer 1 → Layer 2 橋接未定義 | 新增「session 昇級為問題」功能 |
| 4 | LLM-as-Judge 裁判未指定 | 明確指定 Gemini 2.5 Flash（免費、無循環依賴） |
| 5 | API Key 明文儲存 | macOS Keychain 儲存，DB 只存 reference ID |
| 6 | v_daily_question_status「今日」定義歧義 | 改為以 `teacher_usage_logs.called_at` 過濾 |
| 7 | Benchmark 未定義 | `question_sets.is_benchmark` 旗標，fine-tuning 前後自動執行 |
| 8 | Fine-tuning 並發競態 | `training_runs` status 鎖 + queue 機制 |
| 9 | 問題集冷啟動 | 提供 7 個 event_type × 各 5 題的 seed data |
| 10 | RAG token 預算未驗證 | Hook 回傳前估算並截斷超額 context |

---

## 專案位置

```
/Users/surpend/Developer/01_project/shiba-fine-tuning-project/
```

Claude Code Plugin 主體：
```
~/.claude/plugins/local-brain/
```

各專案引用：
```
~/Developer/<project>/.claude-plugin/local-brain/
```

---

## 系統四層架構

### Layer 0：路由層（Router）

**目標**：每條訊息進來先分類，greeting/fyi 直接本地回應，跳過 Claude；其餘訊息壓縮 context 再路由。

```
Incoming request
  ↓
Gemma E2B（Fast tier，think: false，< 2s）：分類 + urgency
  ├── greeting / fyi → 跳過 Claude，直接本地回應
  └── question / request / idea
        ↓
      Gemma E4B（Primary tier，think: false）：壓縮上下文 + 重構 Claude prompt
        ↓
      依複雜度路由：
        ├── 一般任務 → Qwen ft（中文回應）
        ├── 複雜任務 → Claude（高價值工作）
        └── Claude 不可用 → Qwen 35B fallback（llama.cpp，port 8081）
```

**重要**：Gemma E2B/E4B 必須關閉 thinking 模式（think: false），否則速度差 30 倍。

**Resilience Chain**：Claude Sonnet → Claude Haiku → Qwen ft → Qwen 35B → Queue

**Context 壓縮三時機**：

| 時機 | 觸發 | 目的 |
|------|------|------|
| A | Stop Hook（session 結束） | 壓縮存入 SQLite context_summary |
| B | SessionStart（RAG 注入前） | 壓縮歷史 context 不超 token 預算 |
| C | 即時（user 訊息進來） | 500 字 → 30 字，節省 Claude token |

---

### Layer 1：日常記憶層（Daily Memory）

**目標**：每次 Claude 對話結束後，自動捕捉並分類知識，下次對話注入相關 context 省 token。

```
Stop Hook 觸發
    ↓
stop_hook.py（Python，fire-and-forget）
    ↓  Chamber 無回應時 → fallback 寫 queue 檔
POST /api/hooks/stop
    ↓
FastAPI SessionSyncService
    ↓
讀取 ~/.claude/projects/<hash>/<session-id>.jsonl
    ↓
解析 entries → 偵測 Branch（rewind UUID 樹）
    ↓
事件分類（規則型）+ 計算 context_summary
    ↓
儲存四層結構：projects → sessions → branches → messages
    ↓
更新 FTS5 索引（aggregated_content + context_summary）

SessionStart Hook 觸發
    ↓
查詢 is_active branch 的 context_summary
    ↓
hookSpecificOutput 注入（≤500 token，超額截斷）
```

**Branch 追蹤**：
- 每則訊息有 `uuid` 與 `parentUuid`，形成 DAG
- rewind 後新的訊息鏈形成新 branch（不同的 leaf_uuid）
- RAG 只取 `is_active = true` 的 branch，避免廢棄對話污染記憶

**Context Summary 內容**（對齊 Claudest 品質）：
```
exchange_count      對話輪數
files_modified      修改的檔案清單（從 tool_use 解析）
commits             產生的 commit（從 Bash 工具結果解析）
tool_counts         各工具呼叫次數
context_summary     結構化 Markdown 摘要
event_types         分類標籤 JSON array
```

**事件類型分類表**：

| event_type | 觸發條件（規則） |
|-----------|----------------|
| `debugging` | 含 error / traceback / fix 關鍵字 |
| `architecture` | 含 schema / design / flow / 架構 |
| `git_ops` | 含 commit / branch / merge / push |
| `terminal_ops` | bash 指令 / docker / 系統操作 |
| `code_gen` | 大量 code block，無錯誤修復 |
| `knowledge_qa` | 純問答、無工具呼叫 |
| `fine_tuning_ops` | 含 MLX / LoRA / GGUF / Ollama 訓練相關 |

**統一 DB 路徑**：`~/.local-brain/shiba-brain.db`（Layer 1 + Layer 2 + Layer 3 共用）

**Layer 1 Schema（四層結構）**：
```sql
projects
  id, path UNIQUE, key UNIQUE, name

sessions
  id, project_id FK, uuid UNIQUE, git_branch, cwd

branches
  id, session_id FK, leaf_uuid, fork_point_uuid,
  is_active BOOL, started_at, ended_at,
  exchange_count, files_modified JSON, commits JSON,
  tool_counts JSON, context_summary, aggregated_content,
  summary_version INT

messages
  id, session_id FK, msg_uuid, parent_uuid,
  role, content, timestamp,
  has_code_block, has_tool_use, origin

branch_messages
  branch_id FK, message_id FK  （多對多橋接）

sessions_fts（FTS5 虛擬表）
  rowid → branches.id
  aggregated_content, context_summary
```

**記憶衰減機制**（容量觸發，非定時）：

新增 branches 表欄位：`last_accessed TEXT`, `access_count INTEGER DEFAULT 0`, `decay_score REAL DEFAULT 1.0`

衰減公式：`decay_score = decay_score × e^(-λ × days_since_last_access)`，λ 預設 0.1

觸發：active memories > 500 → 歸檔 decay_score < 0.2；7 天內記憶受鞏固保護期保護。

被 RAG 命中 → decay_score 重置 1.0；FTS5 相似度 > 0.8 的舊記憶 → decay_score × 0.8（干擾加速）。

**Fallback 機制**（Chamber 未啟動時）：
```
Stop Hook → Chamber 無回應（timeout 1s）
    ↓
寫入 ~/.local-brain/queue/<session-id>.json
    ↓
Chamber 啟動時掃描 queue/ 補同步
```

---

### Layer 2：精神時光屋（Training Chamber）

**目標**：定期用 AI 師父產生高品質訓練資料，全自動 LLM-as-Judge 評分。

```
問題集合空間（依 event_type 分組）
    ↓
選擇師父組合（單一 or 多師父）
    ↓
批次呼叫 Teacher API（統一 OpenAI-compatible 格式）
    ↓
收集各師父回應
    ↓
第一裁判（Gemini 2.5 Flash）：1-10 分
  ├── ≥ 8 → 自動 approved
  ├── 6-7 → 送第二裁判交叉驗證（取平均或高分）
  │         兩裁判差距 > 2 → 標記 needs_review（非同步批次處理）
  └── < 6 → 自動 rejected
    ↓
approved 樣本 → 存入訓練資料集 JSONL
```

**Layer 1 → Layer 2 自動橋接**：
```
Layer 1 捕捉到：event_type ∈ {git_ops, terminal_ops, code_gen} + has_tool_use + exchange_count ≥ 2
→ 自動萃取 instruction/output → 建立 training_sample（pending）→ 進入自動評分流程
```

**前端定位：監控儀表板**（自動評分通過/拒絕率、Teacher KPI、樣本累積進度、fine-tuning 狀態、Token 消耗趨勢）

**Teacher Plugin 設計（YAML 可擴充）**：

```yaml
teachers:
  - id: gemini-flash
    name: "Gemini 2.5 Flash"
    api_base: "https://generativelanguage.googleapis.com/v1beta/openai"
    model: "gemini-2.5-flash"
    free: true
    daily_limit: 250

  - id: gemini-flash-lite
    name: "Gemini 2.5 Flash-Lite"
    api_base: "https://generativelanguage.googleapis.com/v1beta/openai"
    model: "gemini-2.5-flash-lite"
    free: true
    daily_limit: 1000

  - id: mistral-7b
    name: "Mistral 7B"
    api_base: "https://api.mistral.ai/v1"
    model: "open-mistral-7b"
    free: true
    monthly_token_limit: 1_000_000_000

  - id: deepseek-v3
    name: "DeepSeek V3.2"
    api_base: "https://api.deepseek.com/v1"
    model: "deepseek-chat"
    free: false   # 新帳號 500萬 token 試用期
    notes: "新帳號 30 天免費額度"

  - id: grok-4
    name: "Grok 4"
    api_base: "https://api.x.ai/v1"
    model: "grok-4"
    free: false   # 新帳號 $175 額度
    notes: "新帳號第一個月免費額度"
```

**前端評分介面（6 頁）**：

1. **評分頁（核心）**：問題 + 最多 5 師父並排回答 + 各師父 1-10 評分滑桿
2. **問題集管理**：CRUD 問題，依 event_type 分組，標記難度
3. **訓練室執行**：選問題集 + 師父 → 一鍵執行 → 進度條 → 完成導向評分頁
4. **資料集管理**：查看訓練樣本，依分數/類型/師父篩選
5. **Fine-tuning 狀態**：各類型樣本計數、訓練進度、前後 benchmark 對比
6. **Teacher 管理**：新增/編輯師父，YAML 視覺化編輯

---

### Layer 3：Fine-tuning Pipeline

**目標**：累積足夠樣本後自動觸發 MLX LoRA 訓練，更新 Ollama 模型。

```
Block 觸發條件：各 Block 合計 ≥ 30 approved 樣本（各自獨立觸發）
    ↓
MLX LoRA fine-tuning（M1 Max 64GB，背景執行）
訓練資料比例：70% 新樣本 / 20% 穩定老樣本 / 10% 通用指令集
    ↓
Benchmark 評測（訓練前後對比，含退化測試題組）
    ↓
通過門檻 → 轉換 GGUF → 更新 Ollama modelfile
    ↓
Ollama 模型版本管理（保留上一版供回滾）
```

**兩個 LoRA Adapter**：

| Adapter | 訓練來源 | 目標 |
|---------|---------|------|
| block1_adapter | git_ops + terminal_ops + code_gen | bash/tools 執行模式 |
| block2_adapter | debugging + architecture + knowledge_qa + fine_tuning_ops | 中文回應生成 |

**基底模型**：Qwen2.5 7B（Phase 1）→ Qwen2.5 32B（Phase 2，64GB 可行）
**訓練方式**：LoRA（非全量，避免 catastrophic forgetting）
**訓練資料格式**：Alpaca JSONL
```jsonl
{"instruction": "問題", "input": "", "output": "最佳回答", 
 "source": "gemini-flash", "event_type": "debugging", "score": 8.5}
```

---

## 技術選型總覽

| 元件 | 技術 | 語言 | 理由 |
|------|------|------|------|
| 對話捕捉 | Claude Code Stop/SessionStart Hook（Python） | Python | Claude Code 原生，零依賴 |
| RAG 搜尋 | SQLite FTS5（sessions_fts 虛擬表） | Python | 輕量，無額外服務，同一 DB |
| Fine-tuning | MLX-LM LoRA（Apple Silicon 原生） | Python | 僅支援 Python SDK |
| 基底模型 | Qwen2.5 7B → 32B | — | 中文最強，64GB 可行 |
| Teacher API | FastAPI + openai SDK（OpenAI-compatible） | Python | 語言一致，切換零改 code |
| 前端框架 | Vue 3 + Vite + TypeScript | TypeScript | 監控儀表板 |
| Fast tier | Gemma E2B（think: false） | — | 分類 < 2s |
| Primary tier | Gemma E4B（think: false） | — | 壓縮 + prompt 重構 |
| Response tier | Qwen2.5 7B ft | — | 中文回應生成 |
| Heavy tier | Qwen 35B（llama.cpp，port 8081） | — | 64GB 直接載入 |
| LLM-as-Judge | Gemini 2.5 Flash + 第二裁判 | — | 免費、無循環依賴 |

**切換師父方式**：改 DB 的 `api_base` + `keychain_ref`，零改 code。

---

## 完整 DB Schema（`~/.local-brain/shiba-brain.db`）

```sql
-- ── Layer 1：記憶層 ──────────────────────────────────

CREATE TABLE projects (
    id   INTEGER PRIMARY KEY AUTOINCREMENT,
    path TEXT UNIQUE NOT NULL,
    key  TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL
);

CREATE TABLE sessions (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id),
    uuid       TEXT UNIQUE NOT NULL,
    git_branch TEXT,
    cwd        TEXT
);

CREATE TABLE branches (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id         INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    leaf_uuid          TEXT NOT NULL,
    fork_point_uuid    TEXT,
    is_active          INTEGER DEFAULT 1,
    started_at         TEXT,
    ended_at           TEXT,
    exchange_count     INTEGER DEFAULT 0,
    files_modified     TEXT,   -- JSON array
    commits            TEXT,   -- JSON array
    tool_counts        TEXT,   -- JSON object
    context_summary    TEXT,
    aggregated_content TEXT,
    summary_version    INTEGER DEFAULT 0,
    UNIQUE(session_id, leaf_uuid)
);

CREATE TABLE messages (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id     INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    msg_uuid       TEXT,
    parent_uuid    TEXT,
    role           TEXT NOT NULL CHECK(role IN ('user','assistant')),
    content        TEXT NOT NULL,
    timestamp      TEXT,
    has_code_block INTEGER DEFAULT 0,
    has_tool_use   INTEGER DEFAULT 0,
    origin         TEXT,
    UNIQUE(session_id, msg_uuid)
);

CREATE TABLE branch_messages (
    branch_id  INTEGER NOT NULL REFERENCES branches(id) ON DELETE CASCADE,
    message_id INTEGER NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
    PRIMARY KEY (branch_id, message_id)
);

CREATE VIRTUAL TABLE sessions_fts USING fts5(
    aggregated_content,
    context_summary,
    content=branches,
    content_rowid=id
);

-- ── Layer 2：精神時光屋 ───────────────────────────────

CREATE TABLE teachers (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    teacher_id           TEXT UNIQUE NOT NULL,
    name                 TEXT NOT NULL,
    api_base             TEXT NOT NULL,
    model                TEXT NOT NULL,
    keychain_ref         TEXT,          -- macOS Keychain reference（非明文）
    is_free              INTEGER DEFAULT 1,
    daily_limit          INTEGER,       -- NULL = 無限制
    monthly_token_limit  INTEGER,
    is_active            INTEGER DEFAULT 1,
    notes                TEXT,
    created_at           TEXT DEFAULT (datetime('now')),
    updated_at           TEXT DEFAULT (datetime('now'))
);

CREATE TABLE teacher_usage_logs (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    teacher_id         INTEGER NOT NULL REFERENCES teachers(id),
    training_sample_id INTEGER REFERENCES training_samples(id),
    called_at          TEXT DEFAULT (datetime('now')),
    input_tokens       INTEGER,
    output_tokens      INTEGER,
    total_tokens       INTEGER,
    latency_ms         INTEGER,
    status             TEXT NOT NULL CHECK(status IN ('success','error')),
    error_msg          TEXT
);

CREATE TABLE question_sets (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    name         TEXT NOT NULL,
    event_type   TEXT NOT NULL,
    description  TEXT,
    is_benchmark INTEGER DEFAULT 0,  -- fine-tuning 前後自動執行
    created_at   TEXT DEFAULT (datetime('now'))
);

CREATE TABLE questions (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    question_set_id  INTEGER NOT NULL REFERENCES question_sets(id),
    content          TEXT NOT NULL,
    difficulty       INTEGER DEFAULT 2 CHECK(difficulty IN (1,2,3)),
    event_type       TEXT NOT NULL,
    estimated_tokens INTEGER,         -- 建立時估算
    created_at       TEXT DEFAULT (datetime('now'))
);

CREATE TABLE training_samples (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    question_id  INTEGER NOT NULL REFERENCES questions(id),
    teacher_id   INTEGER NOT NULL REFERENCES teachers(id),
    response     TEXT,
    auto_score   REAL,               -- LLM-as-Judge 初評
    human_score  REAL,               -- 人工 1-10 評分
    status       TEXT DEFAULT 'pending'
                 CHECK(status IN ('pending','approved','rejected')),
    created_at   TEXT DEFAULT (datetime('now')),
    UNIQUE(question_id, teacher_id)
);

-- ── Layer 3：Fine-tuning ─────────────────────────────

CREATE TABLE training_runs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type   TEXT NOT NULL,
    sample_count INTEGER NOT NULL,
    base_model   TEXT DEFAULT 'qwen2.5-7b',
    adapter_path TEXT,
    gguf_path    TEXT,
    ollama_model TEXT,               -- e.g. shiba-brain-v3
    before_score REAL,
    after_score  REAL,
    status       TEXT DEFAULT 'queued'
                 CHECK(status IN ('queued','running','completed','failed')),
    created_at   TEXT DEFAULT (datetime('now'))
);

-- ── Views ────────────────────────────────────────────

CREATE VIEW v_teacher_status AS ...;          -- 師父可用狀態 + 今日用量
CREATE VIEW v_teacher_kpi AS ...;             -- 評分分佈、訓練量、核准率
CREATE VIEW v_teacher_daily_trend AS ...;     -- 每日訓練趨勢
CREATE VIEW v_token_consumption AS ...;       -- Token 消耗總覽
CREATE VIEW v_token_daily_trend AS ...;       -- 每日 Token 趨勢
CREATE VIEW v_training_overview AS ...;       -- 問題/師父/評分跨表觀察
CREATE VIEW v_daily_question_status AS ...;   -- 今日被訓練問題狀態（per 問題）
CREATE VIEW v_category_summary AS ...;        -- 分類彙總（per 分類）
```

### 語言邊界

| 元件 | 語言 | 理由 |
|------|------|------|
| Claude Code Hooks | Python | Claude Code 原生，fire-and-forget |
| Chamber 後端 + RAG + Teacher API | Python（FastAPI） | 語言一致，openai SDK 直接支援 |
| 路由層（router/） | Python | 統一語言，Ollama API 呼叫 |
| 前端監控儀表板 | Vue 3 + TypeScript | 視覺化儀表板 |
| Fine-tuning Pipeline | Python（MLX-LM） | MLX 僅有 Python SDK，無法替換 |

---

## 學術依據（參考論文）

- **Self-Evolving LLMs via Continual Instruction Tuning** (2025) — LoRA Expert 解決 catastrophic forgetting
- **SEAL: Self-Adapting Language Models** (2025) — 自動生成 fine-tuning 資料
- **From RAG to Memory** (2025) — RAG 先行，fine-tune 後補的混合策略
- **FOREVER: Forgetting Curve Memory Replay** (2025) — 記憶管理與清理策略

---

## 執行 Phase 規劃

### Phase 0：文件同步（已完成）
- [x] 更新 CLAUDE.md（目錄結構、技術選型、路由層、評分機制、安全機制）
- [x] 更新 architecture-design.md（移除 Spring AI，加入路由層 + FastAPI）

### Phase 1：Layer 1 基礎記憶層
- [ ] schema.sql（含 decay 欄位預留，邏輯暫不啟用）
- [ ] parser.py / classifier.py / db.py / rag.py
- [ ] stop_hook.py（背景 sync）
- [ ] session_start_hook.py（FTS5 RAG 注入）
- [ ] hooks.json + setup.sh

### Phase 2：Router 基礎分類（Fast tier）
- [ ] router/config.yaml（Ollama 端點設定）
- [ ] router/classifier.py（Gemma E2B，think: false）
- [ ] 整合 Stop Hook：訊息進來先過分類

### Phase 3：Router 壓縮層（Primary tier）
- [ ] router/compressor.py（Gemma E4B，think: false）
- [ ] router/prompt_engineer.py（context → 結構化 Claude prompt）
- [ ] 整合三時機壓縮（Stop Hook / SessionStart / 即時）

### Phase 4：Layer 2 後端（FastAPI）
- [ ] FastAPI 主體 + routers（teachers / questions / training / dashboard）
- [ ] openai SDK teacher 呼叫（base_url 切換）
- [ ] Gemini 2.5 Flash LLM-as-Judge（含 6-7 分第二裁判）
- [ ] Keychain 整合（macOS security 指令）

### Phase 5：Layer 2 前端（Vue 監控儀表板）
- [ ] Vue 3 + Vite 監控頁面
- [ ] 通過率、分數分佈、樣本累積進度、fine-tuning 狀態

### Phase 6：Layer 1 → Layer 2 自動橋接
- [ ] Stop Hook 新增橋接邏輯（event_type ∈ {git_ops, terminal_ops, code_gen} + has_tool_use）
- [ ] Layer 2 API 接收橋接推送

### Phase 7：Layer 1 記憶衰減
- [ ] db.py 新增 decay 欄位更新邏輯
- [ ] 容量觸發：active memories > 500 → 歸檔 decay_score < 0.2
- [ ] 7 天鞏固保護期 + 檢索命中重置
- [ ] **前提**：Phase 1 已跑至少 2 週

### Phase 8：Layer 3 Fine-tuning Pipeline
- [ ] layer_3_pipeline/finetune.py（Block 1 + Block 2 adapter 分別訓練）
- [ ] 訓練資料抽樣（70/20/10）
- [ ] benchmark 擴充（每 event_type ≥ 10 題 + 退化測試題組）
- [ ] GGUF 轉換 + Ollama 更新 + rollback 機制
- [ ] **前提**：per Block approved 樣本各 ≥ 30 筆

### Phase 9：Router 完整整合（Response tier + Resilience chain）
- [ ] router/response.py（Qwen ft 中文回應）
- [ ] router/resilience.py（完整 fallback chain）
- [ ] Heavy tier（Qwen 35B llama.cpp，port 8081）
- [ ] shiba-brain-ft 安全機制整合
- [ ] **前提**：Phase 8 完成

---

## 待寫入：CLAUDE.md（退出 Plan Mode 後執行）

路徑：`/Users/surpend/Developer/01_project/shiba-fine-tuning-project/CLAUDE.md`

```markdown
# shiba-fine-tuning-project — 專案規範

## 專案目的

個人 AI 分流與自我進化系統。讓本地 Ollama 模型透過對話記憶累積與定期「精神時光屋」訓練，
逐步接手 Claude 的重複性任務，Claude 專注於高價值工作。

## 系統三層架構

| Layer | 名稱 | 功能 |
|-------|------|------|
| 1 | 日常記憶層 | Stop Hook 捕捉對話 → SQLite（四層結構）→ FTS5 RAG 注入省 token |
| 2 | 精神時光屋 | 問題集 × AI 師父 → 人工評分 → 訓練資料集 |
| 3 | Fine-tuning Pipeline | MLX LoRA → GGUF → Ollama 更新 |

## 目錄結構

```
shiba-fine-tuning-project/
├── memory/                   # Layer 1：記憶層
│   ├── hooks/                # stop_hook.sh / session_start_hook.sh
│   ├── db/                   # schema.sql + migrations
│   └── queue/                # fallback queue（Spring Boot 離線時暫存）
├── chamber/                  # Layer 2：精神時光屋
│   ├── src/                  # Spring Boot 3 + Spring AI 1.0
│   └── frontend/             # Vue 3 + Vite（評分介面）
├── pipeline/                 # Layer 3：Fine-tuning
│   ├── finetune.py           # MLX LoRA 訓練腳本
│   ├── convert.py            # GGUF 轉換
│   └── benchmark/            # 訓練前後評測
└── data/
    ├── seeds/                # 初始問題集（7 event_type × 5 題）
    └── training/             # 訓練資料 JSONL（Alpaca 格式）
```

## 統一 DB

路徑：`~/.local-brain/shiba-brain.db`（Layer 1 + 2 + 3 共用）

### Layer 1 Schema（四層，對齊 Claudest 設計）

```
projects → sessions → branches → messages
                            ↓
                     branch_messages（橋接）
                            ↓
                     sessions_fts（FTS5 全文索引）
```

- Branch 追蹤：偵測 rewind，只取 `is_active=true` branch 注入 context
- Context Summary：包含 exchange_count / files_modified / commits / tool_counts

### Layer 2 Schema

```
teachers（DB 管理，API Key 存 macOS Keychain）
question_sets（is_benchmark 旗標）
questions（estimated_tokens）
training_samples（auto_score + human_score + status）
teacher_usage_logs（input/output/total tokens + latency_ms）
```

### Views

| View | 用途 |
|------|------|
| v_teacher_status | 師父可用狀態 + 今日用量 |
| v_teacher_kpi | 評分分佈、訓練量、核准率 |
| v_teacher_daily_trend | 每日訓練趨勢 |
| v_token_consumption | Token 消耗總覽 |
| v_token_daily_trend | 每日 Token 趨勢 |
| v_training_overview | 問題/師父/評分跨表觀察 |
| v_daily_question_status | 今日被訓練問題狀態 |
| v_category_summary | 分類彙總 |

## 技術選型

| 元件 | 技術 | 語言 |
|------|------|------|
| Claude Code Hooks 入口 | Shell（stop_hook.sh / session_start_hook.sh） | Shell |
| Fallback Queue | 本地 JSON 檔（~/.local-brain/queue/） | Shell |
| 後端 + RAG + Teacher API | Spring Boot 3 + Spring AI 1.0 | Java |
| 前端評分介面 | Vue 3 + Vite + TypeScript | TypeScript |
| Fine-tuning Pipeline | MLX-LM LoRA | Python（唯一需要 Python 的元件） |
| 基底模型 | Qwen2.5 7B | — |
| LLM-as-Judge 裁判 | Gemini 2.5 Flash（免費，無循環依賴） | — |

## Fallback 機制

Spring Boot 未啟動時：
1. stop_hook.sh timeout 1s → 寫入 `~/.local-brain/queue/<session-id>.json`
2. Spring Boot 啟動後掃描 queue/ 自動補同步

## 免費 AI 師父清單（2026）

| 師父 | 模型 | 免費額度 |
|------|------|---------|
| Gemini 2.5 Flash | gemini-2.5-flash | 250 req/day，永久免費 |
| Gemini 2.5 Flash-Lite | gemini-2.5-flash-lite | 1,000 req/day，永久免費 |
| Mistral 7B | open-mistral-7b | 1B token/月，永久免費 |
| DeepSeek V3.2 | deepseek-chat | 新帳號 500萬 token（30天） |
| Grok 4 | grok-4 | 新帳號 $175 額度（首月） |

## 事件分類（event_type）

`debugging` / `architecture` / `git_ops` / `terminal_ops` / `code_gen` / `knowledge_qa` / `fine_tuning_ops`

## 前端頁面清單（Layer 2）

1. 今日問題統計（分類彙總 + 展開問題列表）
2. 評分介面（問題 + 最多 5 師父並排 + 1-10 評分）
3. 問題集管理（CRUD，依 event_type 分組）
4. 訓練室執行（選問題集 + 師父 → 一鍵執行）
5. 資料集管理（篩選/查看訓練樣本）
6. Fine-tuning 狀態（訓練進度 + benchmark 前後對比）
7. Teacher 管理（設定 + KPI + Token 消耗）

## Fine-tuning 規範

- 訓練方式：LoRA（非全量，避免 catastrophic forgetting）
- 觸發條件：per event_type approved 樣本 ≥ 30 筆
- 競態保護：training_runs status 鎖（queued → running，同時只跑一個）
- 模型版本：保留前一版供回滾
- Benchmark：is_benchmark=true 的問題集在訓練前後自動執行評測
- 資料格式：Alpaca JSONL
  `{"instruction":"...","input":"","output":"...","source":"gemini-flash","event_type":"debugging","score":8.5}`

## 安全規範

- API Key 存於 macOS Keychain，DB 只存 keychain_ref
- SQLite 無明文敏感資訊

## 開發規範

- 所有程式碼附中文註解
- 單次異動原則，驗證通過後才進行下一個
- Layer 1 Hooks 同步至 `~/.claude/plugins/local-brain/`
- 有意義的異動須同步更新 CHANGELOG.md

## 學術參考

- [Self-Evolving LLMs via Continual Instruction Tuning](https://arxiv.org/abs/2509.18133)
- [SEAL: Self-Adapting Language Models](https://arxiv.org/abs/2506.10943)
- [From RAG to Memory](https://arxiv.org/html/2502.14802v1)
- [FOREVER: Forgetting Curve Memory Replay](https://arxiv.org/html/2601.03938v1)

## Git

- Repo：ShibaDev2026/shiba-fine-tuning-project（待建立）
- CLAUDE.md 與 plan 檔不進版控（.gitignore）

## 驗證方式

### Phase 1 驗證
```bash
# 確認 hook 觸發與 DB 寫入
tail -f ~/.local-brain/logs/memory.log
sqlite3 ~/.local-brain/shiba-brain.db \
  "SELECT s.uuid, b.is_active, b.exchange_count FROM sessions s JOIN branches b ON b.session_id=s.id LIMIT 5;"

# 確認 RAG 注入：開新 Claude session，context 應含歷史摘要
```

### Phase 2 驗證
```bash
# 啟動 Spring Boot
cd chamber && ./gradlew bootRun

# 測試 Teacher API
curl http://localhost:8080/api/teachers
curl http://localhost:8080/api/teachers/kpi
```

### Phase 3 驗證
```bash
python pipeline/finetune.py --event-type debugging --dry-run
ollama list | grep shiba-brain
```
```

---

## 驗證方式（plan 檔用）

### Phase 1
```bash
tail -f ~/.local-brain/logs/memory.log
sqlite3 ~/.local-brain/shiba-brain.db \
  "SELECT session_uuid, event_types, exchange_count FROM sessions ORDER BY created_at DESC LIMIT 5;"
```

### Phase 2（Router Fast tier）
```bash
echo '{"message": "好的收到"}' | python3 router/classifier.py
# 應輸出 {"type": "fyi", "urgency": "low", "skip_claude": true}
```

### Phase 4（Layer 2 後端）
```bash
uvicorn main:app --reload
curl http://localhost:8000/api/teachers
curl http://localhost:8000/api/training/samples?status=pending
```

### Phase 8（Fine-tuning）
```bash
python3 layer_3_pipeline/finetune.py --block 1 --dry-run
ollama list | grep shiba-brain
```

### 文件驗證
```bash
# 確認無舊技術殘留
grep -n "Spring\|Spring Boot\|Spring AI\|memory/\|chamber/\|pipeline/" \
  /Users/surpend/Developer/01_project/shiba-fine-tuning-project/CLAUDE.md

# 確認新內容存在
grep -n "FastAPI\|layer_1\|router\|Gemma\|block1_adapter" \
  /Users/surpend/Developer/01_project/shiba-fine-tuning-project/CLAUDE.md
```
