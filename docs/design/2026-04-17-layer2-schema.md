# Layer 2 Schema 擴充實作計劃

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在現有 `shiba-brain.db` 新增 Layer 2 所需資料表與 View，為精神時光屋後端提供完整 DB 基礎。

**Architecture:** 沿用現有 `layer_1_memory/db/schema.sql`，以 append 方式新增 Layer 2 資料表及 8 個 View，並補充對應 migration 邏輯至 `db.py`。

**Tech Stack:** SQLite 3（含 FTS5，macOS 內建）、Python 3.11+

---

## 檔案結構

| 動作 | 檔案 | 說明 |
|------|------|------|
| Modify | `layer_1_memory/db/schema.sql` | 新增 Layer 2 資料表與 View |
| Modify | `layer_1_memory/lib/db.py` | migration 函式補充 Layer 2 資料表建立 |
| Create | `tests/memory/test_schema_layer2.py` | 驗證資料表欄位、View 可查詢 |

---

## Task 1：Layer 2 資料表 Schema

**Files:**
- Modify: `layer_1_memory/db/schema.sql`

- [ ] **Step 1：確認現有 schema 結尾位置**

```bash
tail -20 layer_1_memory/db/schema.sql
```

預期：看到 `sessions_fts` virtual table 定義結尾。

- [ ] **Step 2：在 schema.sql 末尾新增 Layer 2 資料表**

在 `layer_1_memory/db/schema.sql` 末尾加入：

```sql
-- ============================================================
-- Layer 2：精神時光屋
-- ============================================================

-- AI 師父（Teacher）設定表
CREATE TABLE IF NOT EXISTS teachers (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    name                 TEXT NOT NULL UNIQUE,        -- 師父名稱，如 gemini-flash
    model_id             TEXT NOT NULL,               -- API model 識別符
    api_base             TEXT NOT NULL,               -- OpenAI-compatible base URL
    keychain_ref         TEXT NOT NULL,               -- macOS Keychain 參照 key（不存明文）

    -- System Prompt（含計量）
    system_prompt        TEXT NOT NULL DEFAULT '',
    system_prompt_bytes  INTEGER,                     -- UTF-8 bytes 數
    system_prompt_chars  INTEGER,                     -- Unicode 字元數
    system_prompt_tokens INTEGER,                     -- 估算 token 數

    -- 師父狀態
    is_active            INTEGER NOT NULL DEFAULT 1,  -- 手動控制：1=啟用 0=停用
    auto_status          TEXT NOT NULL DEFAULT 'available'
                         CHECK(auto_status IN ('available','quota_exceeded','expired','error')),
                         -- available=可用 / quota_exceeded=本週期額度耗盡 /
                         -- expired=到期 / error=連續呼叫失敗

    -- 額度類型與限制
    limit_type           TEXT NOT NULL DEFAULT 'daily_requests'
                         CHECK(limit_type IN ('daily_requests','monthly_tokens','credit')),
    limit_requests       INTEGER,                     -- req 上限（daily_requests 用）
    limit_tokens         INTEGER,                     -- token 上限（monthly_tokens 用）
    limit_credits_usd    REAL,                        -- 美金額度（credit 用）

    -- 額度時間追蹤
    quota_started_at     TEXT,                        -- 免費額度起始時間
    quota_expires_at     TEXT,                        -- 到期時間（NULL=永久免費）
    quota_reset_cycle    TEXT NOT NULL DEFAULT 'daily'
                         CHECK(quota_reset_cycle IN ('daily','monthly','none')),
                         -- daily=每日重置(Gemini) / monthly=每月重置(Mistral) /
                         -- none=不重置用完即止(DeepSeek/Grok)
    quota_next_reset_at  TEXT,                        -- 下次重置時間（系統計算後更新）

    created_at           TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at           TEXT NOT NULL DEFAULT (datetime('now'))
);

-- 問題集（Question Set）
CREATE TABLE IF NOT EXISTS question_sets (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT NOT NULL UNIQUE,
    description   TEXT,
    is_benchmark  INTEGER NOT NULL DEFAULT 0,  -- 1=benchmark集，fine-tune前後自動執行
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

-- 問題（Question）
CREATE TABLE IF NOT EXISTS questions (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    question_set_id      INTEGER NOT NULL REFERENCES question_sets(id) ON DELETE CASCADE,
    event_type           TEXT NOT NULL,  -- debugging/git_ops/terminal_ops/code_gen/
                                         -- architecture/knowledge_qa/fine_tuning_ops
    ft_block             INTEGER CHECK(ft_block IN (1, 2)),
                         -- 1=git_ops+terminal_ops+code_gen
                         -- 2=debugging+architecture+knowledge_qa+fine_tuning_ops

    -- Instruction（含計量）
    instruction          TEXT NOT NULL,
    instruction_bytes    INTEGER,        -- UTF-8 bytes 數
    instruction_chars    INTEGER,        -- Unicode 字元數
    instruction_tokens   INTEGER,        -- 估算 token 數

    token_estimated_at   TEXT,           -- 最後估算時間（NULL=尚未估算）
    created_at           TEXT NOT NULL DEFAULT (datetime('now'))
);

-- 訓練樣本（Training Sample）
CREATE TABLE IF NOT EXISTS training_samples (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    question_id   INTEGER NOT NULL REFERENCES questions(id) ON DELETE RESTRICT,
                  -- RESTRICT：避免刪題目時意外刪除已 approved 的訓練資料
    teacher_id    INTEGER NOT NULL REFERENCES teachers(id),
    event_type    TEXT NOT NULL,
    ft_block      INTEGER CHECK(ft_block IN (1, 2)),  -- 直接存，匯出不需再推算
    origin        TEXT NOT NULL DEFAULT 'teacher_api'
                  CHECK(origin IN ('teacher_api','layer1_bridge')),
                  -- teacher_api=師父呼叫生成 / layer1_bridge=Layer1自動橋接萃取

    -- Alpaca 格式欄位
    instruction         TEXT NOT NULL,   -- 來自 question.instruction（冗余存，方便匯出）
    instruction_bytes   INTEGER,
    instruction_chars   INTEGER,
    instruction_tokens  INTEGER,

    input               TEXT NOT NULL DEFAULT '',   -- Alpaca input（通常為空）
    input_bytes         INTEGER,
    input_chars         INTEGER,
    input_tokens        INTEGER,

    output              TEXT NOT NULL,   -- 師父生成的回答
    output_bytes        INTEGER,
    output_chars        INTEGER,
    output_tokens       INTEGER,

    -- 評分（三裁判制）
    judge_1_auto_score  REAL,            -- 第一裁判（Gemini 2.5 Flash）
    judge_1_scored_at   TEXT,
    judge_2_cross_score REAL,            -- 第二裁判（6-7分邊界交叉驗證）
    judge_2_scored_at   TEXT,
    judge_3_human_score REAL,            -- 人工複評（needs_human_review時填入）
    judge_3_scored_at   TEXT,
    final_score         REAL,            -- 最終採用分數

    -- 狀態
    status        TEXT NOT NULL DEFAULT 'pending'
                  CHECK(status IN ('pending','approved','rejected','needs_human_review')),
                  -- pending=等待評分 / approved=核准進訓練 /
                  -- rejected=拒絕(保留供未來負樣本使用) /
                  -- needs_human_review=兩裁判差距>2需人工介入

    source        TEXT,                  -- 師父 model_id（JSONL 匯出用）
    created_at    TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

-- 師父使用記錄（Teacher Usage Log）— 每 row = 1次 API 呼叫
CREATE TABLE IF NOT EXISTS teacher_usage_logs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    teacher_id      INTEGER NOT NULL REFERENCES teachers(id),
    sample_id       INTEGER REFERENCES training_samples(id),
    input_tokens    INTEGER DEFAULT 0,
    output_tokens   INTEGER DEFAULT 0,
    total_tokens    INTEGER DEFAULT 0,
    latency_ms      INTEGER DEFAULT 0,
    called_at       TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ============================================================
-- Layer 2 索引
-- ============================================================

CREATE INDEX IF NOT EXISTS idx_training_samples_status
    ON training_samples(status);
CREATE INDEX IF NOT EXISTS idx_training_samples_event
    ON training_samples(event_type);
CREATE INDEX IF NOT EXISTS idx_training_samples_ft_block
    ON training_samples(ft_block);
CREATE INDEX IF NOT EXISTS idx_teacher_usage_logs_called
    ON teacher_usage_logs(called_at);
CREATE INDEX IF NOT EXISTS idx_teacher_usage_logs_teacher
    ON teacher_usage_logs(teacher_id);

-- ============================================================
-- Layer 2 Views
-- ============================================================

-- 師父可用狀態 + 今日 req 數 + 今日 token 數
CREATE VIEW IF NOT EXISTS v_teacher_status AS
SELECT
    t.id,
    t.name,
    t.model_id,
    t.is_active,
    t.auto_status,
    t.limit_type,
    t.limit_requests,
    t.limit_tokens,
    t.quota_expires_at,
    t.quota_next_reset_at,
    COUNT(l.id)               AS today_requests,
    SUM(l.total_tokens)       AS today_tokens,
    (SELECT SUM(l2.total_tokens)
     FROM teacher_usage_logs l2
     WHERE l2.teacher_id = t.id
       AND strftime('%Y-%m', l2.called_at) = strftime('%Y-%m', 'now')
    )                         AS monthly_tokens,
    CASE t.limit_type
        WHEN 'daily_requests'  THEN t.limit_requests - COUNT(l.id)
        WHEN 'monthly_tokens'  THEN t.limit_tokens - (
            SELECT COALESCE(SUM(l3.total_tokens),0)
            FROM teacher_usage_logs l3
            WHERE l3.teacher_id = t.id
              AND strftime('%Y-%m', l3.called_at) = strftime('%Y-%m', 'now')
        )
        ELSE NULL
    END                       AS remaining_quota
FROM teachers t
LEFT JOIN teacher_usage_logs l
    ON l.teacher_id = t.id
    AND date(l.called_at) = date('now')
GROUP BY t.id;

-- 師父 KPI：評分分佈、訓練量、核准率
CREATE VIEW IF NOT EXISTS v_teacher_kpi AS
SELECT
    t.name                                                       AS teacher_name,
    COUNT(s.id)                                                  AS total_samples,
    SUM(CASE WHEN s.status = 'approved'  THEN 1 ELSE 0 END)     AS approved,
    SUM(CASE WHEN s.status = 'rejected'  THEN 1 ELSE 0 END)     AS rejected,
    SUM(CASE WHEN s.status = 'needs_human_review' THEN 1 ELSE 0 END) AS needs_review,
    ROUND(AVG(s.judge_1_auto_score), 2)                          AS avg_judge1_score,
    ROUND(AVG(s.final_score), 2)                                 AS avg_final_score,
    ROUND(
        100.0 * SUM(CASE WHEN s.status = 'approved' THEN 1 ELSE 0 END)
              / MAX(COUNT(s.id), 1), 1
    )                                                            AS approval_rate_pct
FROM teachers t
LEFT JOIN training_samples s ON s.teacher_id = t.id
GROUP BY t.id;

-- 每日訓練趨勢
CREATE VIEW IF NOT EXISTS v_teacher_daily_trend AS
SELECT
    date(s.created_at)              AS day,
    t.name                          AS teacher_name,
    COUNT(s.id)                     AS samples,
    ROUND(AVG(s.judge_1_auto_score), 2) AS avg_score
FROM training_samples s
JOIN teachers t ON t.id = s.teacher_id
GROUP BY date(s.created_at), s.teacher_id;

-- Token 消耗總覽
CREATE VIEW IF NOT EXISTS v_token_consumption AS
SELECT
    t.name                      AS teacher_name,
    SUM(l.input_tokens)         AS total_input_tokens,
    SUM(l.output_tokens)        AS total_output_tokens,
    SUM(l.total_tokens)         AS total_tokens,
    COUNT(l.id)                 AS total_requests,
    ROUND(AVG(l.latency_ms), 0) AS avg_latency_ms
FROM teacher_usage_logs l
JOIN teachers t ON t.id = l.teacher_id
GROUP BY l.teacher_id;

-- 每日 Token 趨勢
CREATE VIEW IF NOT EXISTS v_token_daily_trend AS
SELECT
    date(l.called_at)       AS day,
    t.name                  AS teacher_name,
    SUM(l.total_tokens)     AS total_tokens,
    COUNT(l.id)             AS requests
FROM teacher_usage_logs l
JOIN teachers t ON t.id = l.teacher_id
GROUP BY date(l.called_at), l.teacher_id;

-- 問題 / 師父 / 評分跨表觀察
CREATE VIEW IF NOT EXISTS v_training_overview AS
SELECT
    q.event_type,
    q.ft_block,
    qs.name                 AS question_set,
    t.name                  AS teacher,
    s.origin,
    s.status,
    s.judge_1_auto_score,
    s.judge_2_cross_score,
    s.judge_3_human_score,
    s.final_score,
    s.created_at
FROM training_samples s
JOIN questions q       ON q.id = s.question_id
JOIN question_sets qs  ON qs.id = q.question_set_id
JOIN teachers t        ON t.id = s.teacher_id;

-- 今日被訓練問題狀態（以 called_at 判斷「今日」）
CREATE VIEW IF NOT EXISTS v_daily_question_status AS
SELECT
    q.event_type,
    q.instruction,
    s.status,
    s.judge_1_auto_score,
    s.final_score,
    l.called_at
FROM teacher_usage_logs l
JOIN training_samples s ON s.id = l.sample_id
JOIN questions q        ON q.id = s.question_id
WHERE date(l.called_at) = date('now');

-- 分類彙總
CREATE VIEW IF NOT EXISTS v_category_summary AS
SELECT
    q.event_type,
    q.ft_block,
    COUNT(s.id)                                                  AS total,
    SUM(CASE WHEN s.status = 'approved'  THEN 1 ELSE 0 END)     AS approved,
    SUM(CASE WHEN s.status = 'rejected'  THEN 1 ELSE 0 END)     AS rejected,
    ROUND(AVG(s.final_score), 2)                                 AS avg_final_score
FROM training_samples s
JOIN questions q ON q.id = s.question_id
GROUP BY q.event_type;
```

---

## Task 2：db.py migration 補充

**Files:**
- Modify: `layer_1_memory/lib/db.py`

- [ ] **Step 1：確認現有 migration 區塊位置**

```bash
grep -n "migration\|ALTER\|_column_exists" layer_1_memory/lib/db.py
```

- [ ] **Step 2：在 init_db() 末尾補充 Layer 2 migration**

在現有 migration 區塊之後加入：

```python
        # Layer 2 migration：確認關鍵欄位存在（舊版 DB 升級用）
        if _column_exists(conn, "training_samples", "id"):
            for col, definition in [
                ("human_score",         "REAL"),           # 舊版相容
                ("judge_1_auto_score",  "REAL"),
                ("judge_2_cross_score", "REAL"),
                ("judge_3_human_score", "REAL"),
                ("judge_3_scored_at",   "TEXT"),
                ("final_score",         "REAL"),
                ("origin",              "TEXT DEFAULT 'teacher_api'"),
                ("ft_block",            "INTEGER"),
                ("output_bytes",        "INTEGER"),
                ("output_chars",        "INTEGER"),
                ("output_tokens",       "INTEGER"),
            ]:
                if not _column_exists(conn, "training_samples", col):
                    conn.execute(
                        f"ALTER TABLE training_samples ADD COLUMN {col} {definition}"
                    )

        if _column_exists(conn, "teachers", "id"):
            for col, definition in [
                ("auto_status",          "TEXT DEFAULT 'available'"),
                ("limit_requests",       "INTEGER"),
                ("limit_tokens",         "INTEGER"),
                ("limit_credits_usd",    "REAL"),
                ("quota_started_at",     "TEXT"),
                ("quota_expires_at",     "TEXT"),
                ("quota_reset_cycle",    "TEXT DEFAULT 'daily'"),
                ("quota_next_reset_at",  "TEXT"),
                ("system_prompt",        "TEXT DEFAULT ''"),
                ("system_prompt_bytes",  "INTEGER"),
                ("system_prompt_chars",  "INTEGER"),
                ("system_prompt_tokens", "INTEGER"),
                ("updated_at",           "TEXT DEFAULT (datetime('now'))"),
            ]:
                if not _column_exists(conn, "teachers", col):
                    conn.execute(
                        f"ALTER TABLE teachers ADD COLUMN {col} {definition}"
                    )

        if _column_exists(conn, "questions", "id"):
            for col, definition in [
                ("ft_block",              "INTEGER"),
                ("instruction_bytes",     "INTEGER"),
                ("instruction_chars",     "INTEGER"),
                ("instruction_tokens",    "INTEGER"),
                ("token_estimated_at",    "TEXT"),
            ]:
                if not _column_exists(conn, "questions", col):
                    conn.execute(
                        f"ALTER TABLE questions ADD COLUMN {col} {definition}"
                    )

        conn.commit()
```

---

## Task 3：單元測試

**Files:**
- Create: `tests/memory/test_schema_layer2.py`

- [ ] **Step 1：撰寫測試**

```python
# tests/memory/test_schema_layer2.py
"""Layer 2 schema 驗證測試"""

import sqlite3
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "layer_1_memory"))

from lib.db import init_db

LAYER2_TABLES = [
    "teachers",
    "question_sets",
    "questions",
    "training_samples",
    "teacher_usage_logs",
]

LAYER2_VIEWS = [
    "v_teacher_status",
    "v_teacher_kpi",
    "v_teacher_daily_trend",
    "v_token_consumption",
    "v_token_daily_trend",
    "v_training_overview",
    "v_daily_question_status",
    "v_category_summary",
]

TEACHERS_REQUIRED_COLS = [
    "id", "name", "model_id", "api_base", "keychain_ref",
    "system_prompt", "system_prompt_bytes", "system_prompt_chars", "system_prompt_tokens",
    "is_active", "auto_status",
    "limit_type", "limit_requests", "limit_tokens", "limit_credits_usd",
    "quota_started_at", "quota_expires_at", "quota_reset_cycle", "quota_next_reset_at",
    "created_at", "updated_at",
]

TRAINING_SAMPLES_REQUIRED_COLS = [
    "id", "question_id", "teacher_id", "event_type", "ft_block", "origin",
    "instruction", "instruction_bytes", "instruction_chars", "instruction_tokens",
    "input", "input_bytes", "input_chars", "input_tokens",
    "output", "output_bytes", "output_chars", "output_tokens",
    "judge_1_auto_score", "judge_1_scored_at",
    "judge_2_cross_score", "judge_2_scored_at",
    "judge_3_human_score", "judge_3_scored_at",
    "final_score", "status", "source", "created_at", "updated_at",
]


def _get_objects(db_path: Path) -> tuple[set[str], set[str]]:
    conn = sqlite3.connect(str(db_path))
    rows = conn.execute(
        "SELECT name, type FROM sqlite_master WHERE type IN ('table','view')"
    ).fetchall()
    conn.close()
    tables = {r[0] for r in rows if r[1] == "table"}
    views  = {r[0] for r in rows if r[1] == "view"}
    return tables, views


def _get_columns(db_path: Path, table: str) -> set[str]:
    conn = sqlite3.connect(str(db_path))
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    conn.close()
    return {r[1] for r in rows}


@pytest.mark.parametrize("table", LAYER2_TABLES)
def test_layer2_tables_exist(tmp_path, table):
    db_file = tmp_path / "test.db"
    with patch("lib.db.get_db_path", return_value=db_file):
        init_db()
    tables, _ = _get_objects(db_file)
    assert table in tables, f"資料表 {table} 不存在"


@pytest.mark.parametrize("view", LAYER2_VIEWS)
def test_layer2_views_exist(tmp_path, view):
    db_file = tmp_path / "test.db"
    with patch("lib.db.get_db_path", return_value=db_file):
        init_db()
    _, views = _get_objects(db_file)
    assert view in views, f"View {view} 不存在"


@pytest.mark.parametrize("col", TEACHERS_REQUIRED_COLS)
def test_teachers_columns(tmp_path, col):
    db_file = tmp_path / "test.db"
    with patch("lib.db.get_db_path", return_value=db_file):
        init_db()
    cols = _get_columns(db_file, "teachers")
    assert col in cols, f"teachers.{col} 欄位不存在"


@pytest.mark.parametrize("col", TRAINING_SAMPLES_REQUIRED_COLS)
def test_training_samples_columns(tmp_path, col):
    db_file = tmp_path / "test.db"
    with patch("lib.db.get_db_path", return_value=db_file):
        init_db()
    cols = _get_columns(db_file, "training_samples")
    assert col in cols, f"training_samples.{col} 欄位不存在"


def test_training_samples_status_constraint(tmp_path):
    """status CHECK 約束應拒絕非法值"""
    db_file = tmp_path / "test.db"
    with patch("lib.db.get_db_path", return_value=db_file):
        init_db()
    conn = sqlite3.connect(str(db_file))
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute(
        "INSERT INTO teachers (name,model_id,api_base,keychain_ref) VALUES ('t1','m1','http://x','k1')"
    )
    conn.execute("INSERT INTO question_sets (name) VALUES ('qs1')")
    conn.execute(
        "INSERT INTO questions (question_set_id,event_type,instruction) VALUES (1,'debugging','q1')"
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO training_samples "
            "(question_id,teacher_id,event_type,instruction,output,status) "
            "VALUES (1,1,'debugging','q1','ans','invalid_status')"
        )
    conn.close()


def test_training_samples_fk_restrict(tmp_path):
    """question 刪除時應因 RESTRICT 被阻擋（approved 樣本保護）"""
    db_file = tmp_path / "test.db"
    with patch("lib.db.get_db_path", return_value=db_file):
        init_db()
    conn = sqlite3.connect(str(db_file))
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute(
        "INSERT INTO teachers (name,model_id,api_base,keychain_ref) VALUES ('t1','m1','http://x','k1')"
    )
    conn.execute("INSERT INTO question_sets (name) VALUES ('qs1')")
    conn.execute(
        "INSERT INTO questions (question_set_id,event_type,instruction) VALUES (1,'debugging','q1')"
    )
    conn.execute(
        "INSERT INTO training_samples "
        "(question_id,teacher_id,event_type,instruction,output,status) "
        "VALUES (1,1,'debugging','q1','ans','approved')"
    )
    conn.commit()
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("DELETE FROM questions WHERE id = 1")
        conn.commit()
    conn.close()


def test_v_teacher_status_queryable(tmp_path):
    """v_teacher_status 應可正常查詢"""
    db_file = tmp_path / "test.db"
    with patch("lib.db.get_db_path", return_value=db_file):
        init_db()
    conn = sqlite3.connect(str(db_file))
    rows = conn.execute("SELECT * FROM v_teacher_status").fetchall()
    conn.close()
    assert isinstance(rows, list)
```

- [ ] **Step 2：執行測試確認失敗（資料表尚未加入 schema）**

```bash
/Users/surpend/.local-brain/venv/bin/python3 -m pytest tests/memory/test_schema_layer2.py -v
```

預期：`FAILED` — `AssertionError: 資料表 teachers 不存在`

- [ ] **Step 3：執行 Task 1、Task 2 實作後，重跑測試**

```bash
/Users/surpend/.local-brain/venv/bin/python3 -m pytest tests/memory/test_schema_layer2.py -v
```

預期：全數 passed

- [ ] **Step 4：跑全部測試確認無退化**

```bash
/Users/surpend/.local-brain/venv/bin/python3 -m pytest tests/ -v
```

預期：所有 tests passed

---

## Task 4：Commit

- [ ] **Step 1：確認實際 DB 已 migration**

```bash
sqlite3 ~/.local-brain/shiba-brain.db \
  "SELECT name, type FROM sqlite_master WHERE type IN ('table','view') ORDER BY name;"
```

預期包含：`teachers`、`question_sets`、`questions`、`training_samples`、`teacher_usage_logs`、8 個 `v_*` view。

- [ ] **Step 2：Commit**

```bash
git add layer_1_memory/db/schema.sql layer_1_memory/lib/db.py tests/memory/test_schema_layer2.py
git commit -m "feat: 新增 Layer 2 schema（teachers / questions / training_samples + 8 Views）"
```

---

## 自我檢查

**Spec 覆蓋確認（對照 CLAUDE.md + 討論決議）：**
- ✅ `teachers`：API Key Keychain、雙狀態（is_active + auto_status）、雙軌額度（req + token）、時間追蹤（quota_started/expires/reset）、system_prompt 計量
- ✅ `question_sets`：is_benchmark 旗標
- ✅ `questions`：estimated_tokens（含 bytes/chars/tokens 三計量）、ft_block、token_estimated_at
- ✅ `training_samples`：三裁判評分 + 時間戳、bytes/chars/tokens 計量、origin、ft_block、ON DELETE RESTRICT
- ✅ `teacher_usage_logs`：每次呼叫完整記錄（token + req + latency + called_at 時間歷程）
- ✅ 8 個 View 全數覆蓋，v_teacher_status 同時顯示 req 與 token 剩餘額度
- ✅ `v_daily_question_status` 用 `called_at` 判斷「今日」
- ✅ 索引：status / event_type / ft_block / called_at / teacher_id
- ✅ `rejected` 樣本永久保留（疑點已記錄：未來可作負樣本訓練用）
