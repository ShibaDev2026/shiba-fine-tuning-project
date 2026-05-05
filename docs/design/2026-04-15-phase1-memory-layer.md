# Phase 1：Daily Memory Layer 實作計劃

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 每次 Claude Code 對話結束後，自動捕捉並分類對話內容存入本地 SQLite，下次對話開始時注入相關記憶 context，減少重複解釋的 token 消耗。

**Architecture:** Stop Hook 在背景解析 `~/.claude/projects/*.jsonl`，用規則分類事件類型後存入 SQLite + FTS5 全文索引。SessionStart Hook 查詢相關記憶，透過 `hookSpecificOutput` 注入 context 給 Claude。全程不阻塞 Claude，所有 I/O 都在背景 process 執行。

**Tech Stack:** Python 3.11+、SQLite 3（含 FTS5，macOS 內建）、Claude Code Hooks（Stop / SessionStart）

---

## 檔案結構

```
~/.claude/plugins/local-brain/        ← Claude Code Plugin 主體（由 setup.sh 建立 symlink）
shiba-fine-tuning-project/
├── memory/
│   ├── hooks/
│   │   ├── hooks.json               # Claude Code hook 定義
│   │   ├── stop_hook.py             # Stop Hook 入口（快速回應，spawn 背景）
│   │   ├── sync_session.py          # 背景同步主邏輯
│   │   └── session_start_hook.py    # SessionStart Hook 入口
│   ├── lib/
│   │   ├── parser.py                # JSONL 解析器
│   │   ├── classifier.py            # 事件分類器（規則型）
│   │   ├── db.py                    # SQLite 連線與 schema 初始化
│   │   └── rag.py                   # FTS5 查詢 + context 格式化
│   ├── db/
│   │   └── schema.sql               # SQLite schema 定義
│   ├── config.yaml                  # 設定（路徑、閾值）
│   ├── requirements.txt             # Python 依賴
│   └── setup.sh                     # 部署到 ~/.claude/plugins/local-brain/
└── tests/
    └── memory/
        ├── test_parser.py
        ├── test_classifier.py
        ├── test_db.py
        └── test_rag.py
```

---

## Task 1：專案目錄結構 + 依賴初始化

**Files:**
- Create: `memory/requirements.txt`
- Create: `memory/config.yaml`
- Create: `memory/db/schema.sql`

- [ ] **Step 1：建立目錄結構**

```bash
cd /Users/surpend/Developer/01_project/shiba-fine-tuning-project
mkdir -p memory/hooks memory/lib memory/db tests/memory
```

- [ ] **Step 2：建立 requirements.txt**

```
# memory/requirements.txt
pyyaml>=6.0
pytest>=8.0
```

（SQLite、FTS5、json、pathlib 皆為 Python 標準庫，不需額外安裝）

- [ ] **Step 3：建立 config.yaml**

```yaml
# memory/config.yaml

# Claude Code session 檔案位置
claude_projects_dir: "~/.claude/projects"

# 本地記憶資料庫位置
db_path: "~/.local-brain/memory.db"

# Log 位置
log_path: "~/.local-brain/logs/memory.log"

# RAG 注入設定
rag:
  max_context_tokens: 500      # 注入 context 最大 token 數（估算）
  max_sessions: 3              # 最多注入幾筆歷史
  min_exchange_count: 2        # 至少幾輪對話才值得記錄

# 事件分類閾值
classifier:
  min_message_length: 20       # 忽略太短的訊息
```

- [ ] **Step 4：建立 SQLite Schema**

```sql
-- memory/db/schema.sql

-- 對話 session 記錄
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_uuid TEXT UNIQUE NOT NULL,   -- Claude session UUID
    project_path TEXT,                   -- 對話發生的專案目錄
    started_at TEXT,                     -- ISO8601 時間
    ended_at TEXT,
    exchange_count INTEGER DEFAULT 0,    -- user/assistant 輪數
    event_types TEXT DEFAULT '[]',       -- JSON array，如 ["debugging","git_ops"]
    summary TEXT,                        -- 簡短摘要（前 3 輪 user 訊息）
    created_at TEXT DEFAULT (datetime('now'))
);

-- 訊息明細（用於 FTS5 全文索引）
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    msg_uuid TEXT,
    role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
    content TEXT NOT NULL,
    timestamp TEXT,
    has_code_block INTEGER DEFAULT 0,
    has_tool_use INTEGER DEFAULT 0
);

-- FTS5 全文索引（加速 RAG 查詢）
CREATE VIRTUAL TABLE IF NOT EXISTS sessions_fts USING fts5(
    summary,
    event_types,
    content=sessions,
    content_rowid=id
);

-- 觸發器：session 寫入時同步更新 FTS5
CREATE TRIGGER IF NOT EXISTS sessions_ai AFTER INSERT ON sessions BEGIN
    INSERT INTO sessions_fts(rowid, summary, event_types)
    VALUES (new.id, new.summary, new.event_types);
END;

CREATE TRIGGER IF NOT EXISTS sessions_au AFTER UPDATE ON sessions BEGIN
    INSERT INTO sessions_fts(sessions_fts, rowid, summary, event_types)
    VALUES ('delete', old.id, old.summary, old.event_types);
    INSERT INTO sessions_fts(rowid, summary, event_types)
    VALUES (new.id, new.summary, new.event_types);
END;
```

- [ ] **Step 5：建立 log 目錄並確認 Python 版本**

```bash
mkdir -p ~/.local-brain/logs
python3 --version   # 需要 3.11+
pip3 install -r memory/requirements.txt
```

預期輸出：`Python 3.11.x` 或以上

- [ ] **Step 6：Commit**

```bash
git add memory/ tests/ docs/
git commit -m "chore: 初始化 Phase 1 記憶層目錄結構與 schema"
```

---

## Task 2：DB 工具函式（db.py）

**Files:**
- Create: `memory/lib/db.py`
- Test: `tests/memory/test_db.py`

- [ ] **Step 1：撰寫 test_db.py（失敗測試）**

```python
# tests/memory/test_db.py
import sqlite3
import tempfile
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "memory"))

from lib.db import init_db, get_connection

def test_init_db_creates_tables():
    """init_db 應建立 sessions、messages、sessions_fts 三張表"""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    conn = init_db(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = {row[0] for row in cursor.fetchall()}
    conn.close()

    assert "sessions" in tables
    assert "messages" in tables
    assert "sessions_fts" in tables

def test_get_connection_returns_connection():
    """get_connection 應回傳 sqlite3.Connection"""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    conn = get_connection(db_path)
    assert isinstance(conn, sqlite3.Connection)
    conn.close()
```

- [ ] **Step 2：執行測試確認失敗**

```bash
cd /Users/surpend/Developer/01_project/shiba-fine-tuning-project
python3 -m pytest tests/memory/test_db.py -v
```

預期：`ModuleNotFoundError: No module named 'lib.db'`

- [ ] **Step 3：實作 db.py**

```python
# memory/lib/db.py
"""SQLite 連線管理與 Schema 初始化"""

import sqlite3
from pathlib import Path

# Schema 檔案路徑（相對於此檔案）
_SCHEMA_PATH = Path(__file__).parent.parent / "db" / "schema.sql"


def get_connection(db_path: str) -> sqlite3.Connection:
    """建立並回傳 SQLite 連線，啟用 WAL 模式與外鍵約束"""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row  # 允許用欄位名稱存取
    conn.execute("PRAGMA journal_mode=WAL")   # 提升並行寫入效能
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(db_path: str) -> sqlite3.Connection:
    """初始化資料庫：建立目錄、執行 schema，回傳連線"""
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = get_connection(db_path)
    schema_sql = _SCHEMA_PATH.read_text(encoding="utf-8")
    conn.executescript(schema_sql)
    conn.commit()
    return conn
```

- [ ] **Step 4：執行測試確認通過**

```bash
python3 -m pytest tests/memory/test_db.py -v
```

預期：`2 passed`

- [ ] **Step 5：Commit**

```bash
git add memory/lib/db.py tests/memory/test_db.py
git commit -m "feat: 新增 SQLite DB 初始化工具（db.py）"
```

---

## Task 3：JSONL 解析器（parser.py）

**Files:**
- Create: `memory/lib/parser.py`
- Test: `tests/memory/test_parser.py`

- [ ] **Step 1：撰寫 test_parser.py（失敗測試）**

```python
# tests/memory/test_parser.py
import json
import tempfile
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "memory"))

from lib.parser import parse_session_file, SessionData

def _write_jsonl(path: Path, entries: list) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for entry in entries:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

def test_parse_basic_session():
    """應正確解析 user/assistant 訊息，回傳 SessionData"""
    with tempfile.TemporaryDirectory() as tmpdir:
        jsonl_path = Path(tmpdir) / "test-session.jsonl"
        _write_jsonl(jsonl_path, [
            {"type": "summary", "summary": "test session"},
            {
                "type": "user",
                "uuid": "uuid-1",
                "timestamp": "2026-04-15T10:00:00Z",
                "message": {"content": "如何使用 LoRA fine-tuning？"}
            },
            {
                "type": "assistant",
                "uuid": "uuid-2",
                "timestamp": "2026-04-15T10:00:05Z",
                "message": {"content": "LoRA 是一種..."}
            },
        ])
        result = parse_session_file(str(jsonl_path))

    assert result.session_uuid == "test-session"
    assert len(result.messages) == 2
    assert result.messages[0].role == "user"
    assert result.messages[1].role == "assistant"
    assert result.exchange_count == 1

def test_parse_empty_file_returns_none():
    """空檔案應回傳 None"""
    with tempfile.TemporaryDirectory() as tmpdir:
        jsonl_path = Path(tmpdir) / "empty.jsonl"
        jsonl_path.write_text("")
        result = parse_session_file(str(jsonl_path))
    assert result is None

def test_parse_detects_code_block():
    """含 code block 的訊息應標記 has_code_block=True"""
    with tempfile.TemporaryDirectory() as tmpdir:
        jsonl_path = Path(tmpdir) / "code-session.jsonl"
        _write_jsonl(jsonl_path, [
            {
                "type": "user",
                "uuid": "u1",
                "timestamp": "2026-04-15T10:00:00Z",
                "message": {"content": "```python\nprint('hello')\n```"}
            }
        ])
        result = parse_session_file(str(jsonl_path))

    assert result.messages[0].has_code_block is True
```

- [ ] **Step 2：執行測試確認失敗**

```bash
python3 -m pytest tests/memory/test_parser.py -v
```

預期：`ModuleNotFoundError: No module named 'lib.parser'`

- [ ] **Step 3：實作 parser.py**

```python
# memory/lib/parser.py
"""解析 Claude Code 原生 JSONL session 檔案"""

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class MessageData:
    """單則訊息資料"""
    uuid: str
    role: str          # 'user' | 'assistant'
    content: str
    timestamp: str
    has_code_block: bool = False
    has_tool_use: bool = False


@dataclass
class SessionData:
    """一個 session 的完整解析結果"""
    session_uuid: str
    messages: list[MessageData] = field(default_factory=list)
    started_at: Optional[str] = None
    ended_at: Optional[str] = None

    @property
    def exchange_count(self) -> int:
        """計算 user/assistant 來回輪數（以 user 訊息數為準）"""
        return sum(1 for m in self.messages if m.role == "user")


def _extract_text(content) -> str:
    """從 content（字串或 list）萃取純文字"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict):
                if block.get("type") == "text":
                    parts.append(block.get("text", ""))
                elif block.get("type") == "tool_use":
                    parts.append(f"[tool:{block.get('name','')}]")
        return " ".join(parts)
    return ""


def _has_code_block(text: str) -> bool:
    """偵測是否含 markdown code block"""
    return bool(re.search(r"```", text))


def _has_tool_use(content) -> bool:
    """偵測是否含工具呼叫"""
    if isinstance(content, list):
        return any(
            isinstance(b, dict) and b.get("type") == "tool_use"
            for b in content
        )
    return False


def parse_session_file(jsonl_path: str) -> Optional[SessionData]:
    """
    解析單一 JSONL session 檔案，回傳 SessionData。
    檔案為空或無有效訊息時回傳 None。
    """
    path = Path(jsonl_path)
    if not path.exists() or path.stat().st_size == 0:
        return None

    session_uuid = path.stem  # 檔名即 session UUID
    session = SessionData(session_uuid=session_uuid)

    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            entry_type = entry.get("type")
            if entry_type not in ("user", "assistant"):
                continue

            message = entry.get("message", {})
            raw_content = message.get("content", "")
            text = _extract_text(raw_content)

            if not text.strip():
                continue

            msg = MessageData(
                uuid=entry.get("uuid", ""),
                role=entry_type,
                content=text,
                timestamp=entry.get("timestamp", ""),
                has_code_block=_has_code_block(text),
                has_tool_use=_has_tool_use(raw_content),
            )
            session.messages.append(msg)

            # 記錄時間範圍
            if msg.timestamp:
                if session.started_at is None:
                    session.started_at = msg.timestamp
                session.ended_at = msg.timestamp

    if not session.messages:
        return None

    return session
```

- [ ] **Step 4：執行測試確認通過**

```bash
python3 -m pytest tests/memory/test_parser.py -v
```

預期：`3 passed`

- [ ] **Step 5：Commit**

```bash
git add memory/lib/parser.py tests/memory/test_parser.py
git commit -m "feat: 新增 Claude JSONL session 解析器（parser.py）"
```

---

## Task 4：事件分類器（classifier.py）

**Files:**
- Create: `memory/lib/classifier.py`
- Test: `tests/memory/test_classifier.py`

- [ ] **Step 1：撰寫 test_classifier.py（失敗測試）**

```python
# tests/memory/test_classifier.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "memory"))

from lib.classifier import classify_session
from lib.parser import SessionData, MessageData

def _make_session(texts: list[str]) -> SessionData:
    """建立測試用 SessionData"""
    s = SessionData(session_uuid="test")
    for i, text in enumerate(texts):
        s.messages.append(MessageData(
            uuid=f"u{i}", role="user" if i % 2 == 0 else "assistant",
            content=text, timestamp="2026-04-15T10:00:00Z"
        ))
    return s

def test_classify_debugging():
    s = _make_session(["這個 function 有 error，幫我 fix", "好的，問題在於..."])
    assert "debugging" in classify_session(s)

def test_classify_git_ops():
    s = _make_session(["幫我寫 commit message", "feat: 新增功能"])
    assert "git_ops" in classify_session(s)

def test_classify_terminal_ops():
    s = _make_session(["docker compose up 失敗了", "請執行 docker ps 確認"])
    assert "terminal_ops" in classify_session(s)

def test_classify_architecture():
    s = _make_session(["幫我設計這個系統的 schema", "建議如下架構..."])
    assert "architecture" in classify_session(s)

def test_classify_knowledge_qa():
    s = _make_session(["LoRA 跟全量 fine-tuning 差在哪裡？", "LoRA 只訓練低秩矩陣..."])
    assert "knowledge_qa" in classify_session(s)

def test_classify_multiple_types():
    """一個 session 可以有多個類型"""
    s = _make_session([
        "git commit 之後發現有 error",
        "先 fix error 再 commit"
    ])
    types = classify_session(s)
    assert "debugging" in types
    assert "git_ops" in types

def test_classify_returns_list():
    """回傳值必須是 list"""
    s = _make_session(["任意問題"])
    assert isinstance(classify_session(s), list)
```

- [ ] **Step 2：執行測試確認失敗**

```bash
python3 -m pytest tests/memory/test_classifier.py -v
```

預期：`ModuleNotFoundError: No module named 'lib.classifier'`

- [ ] **Step 3：實作 classifier.py**

```python
# memory/lib/classifier.py
"""事件類型分類器（規則型，無需 LLM）"""

import re
from lib.parser import SessionData

# 各事件類型的關鍵字規則
_RULES: dict[str, list[str]] = {
    "debugging": [
        r"error", r"traceback", r"exception", r"fix\b", r"bug\b",
        r"修正", r"修復", r"錯誤", r"失敗", r"TypeError", r"KeyError",
        r"AttributeError", r"ImportError", r"SyntaxError", r"ValueError",
    ],
    "git_ops": [
        r"\bgit\b", r"\bcommit\b", r"\bbranch\b", r"\bmerge\b",
        r"\bpush\b", r"\bpull\b", r"\brebase\b", r"\btag\b",
        r"CHANGELOG", r"版本號",
    ],
    "terminal_ops": [
        r"\bdocker\b", r"\bbash\b", r"\bssh\b", r"\bcurl\b",
        r"\bbrew\b", r"\bnpm\b", r"\byarn\b", r"\bpip\b",
        r"docker compose", r"\bkubectl\b", r"終端機", r"指令",
    ],
    "architecture": [
        r"\bschema\b", r"\bdesign\b", r"\bflow\b", r"架構",
        r"設計", r"資料庫", r"table\b", r"migration\b",
        r"\bAPI\b", r"endpoint\b", r"pattern\b", r"interface\b",
    ],
    "code_gen": [
        r"```",   # code block
        r"幫我寫", r"實作", r"generate", r"implement",
    ],
    "fine_tuning_ops": [
        r"\bMLX\b", r"\bLoRA\b", r"\bGGUF\b", r"\bOllama\b",
        r"fine.?tun", r"fine-tuning", r"訓練", r"training",
        r"embedding", r"checkpoint",
    ],
    "knowledge_qa": [
        r"是什麼", r"如何", r"怎麼", r"差在哪", r"解釋",
        r"what is", r"how to", r"explain", r"difference between",
    ],
}

# 預先編譯 regex（提升效能）
_COMPILED_RULES: dict[str, list[re.Pattern]] = {
    event_type: [re.compile(pattern, re.IGNORECASE) for pattern in patterns]
    for event_type, patterns in _RULES.items()
}


def classify_session(session: SessionData) -> list[str]:
    """
    分析 session 所有訊息，回傳符合的事件類型清單。
    一個 session 可同時屬於多個類型。
    若無符合，回傳 ['knowledge_qa'] 作為預設。
    """
    # 合併所有訊息文字供搜尋
    full_text = " ".join(m.content for m in session.messages)

    matched = []
    for event_type, patterns in _COMPILED_RULES.items():
        if any(p.search(full_text) for p in patterns):
            matched.append(event_type)

    # 若無任何匹配，預設為 knowledge_qa
    return matched if matched else ["knowledge_qa"]
```

- [ ] **Step 4：執行測試確認通過**

```bash
python3 -m pytest tests/memory/test_classifier.py -v
```

預期：`7 passed`

- [ ] **Step 5：Commit**

```bash
git add memory/lib/classifier.py tests/memory/test_classifier.py
git commit -m "feat: 新增規則型事件分類器（classifier.py）"
```

---

## Task 5：RAG 查詢模組（rag.py）

**Files:**
- Create: `memory/lib/rag.py`
- Test: `tests/memory/test_rag.py`

- [ ] **Step 1：撰寫 test_rag.py（失敗測試）**

```python
# tests/memory/test_rag.py
import tempfile
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "memory"))

from lib.db import init_db
from lib.rag import search_memory, format_context

def _seed_db(conn):
    """植入測試資料"""
    conn.execute("""
        INSERT INTO sessions (session_uuid, project_path, started_at, ended_at,
                              exchange_count, event_types, summary)
        VALUES ('uuid-001', '/project', '2026-04-14T10:00:00Z', '2026-04-14T10:30:00Z',
                5, '["debugging"]', 'address_parser 里鄰剝離修正')
    """)
    conn.execute("""
        INSERT INTO sessions (session_uuid, project_path, started_at, ended_at,
                              exchange_count, event_types, summary)
        VALUES ('uuid-002', '/project', '2026-04-13T09:00:00Z', '2026-04-13T09:45:00Z',
                8, '["architecture"]', 'geocoder 查詢改用 COALESCE 優化')
    """)
    conn.commit()

def test_search_memory_finds_relevant():
    """FTS5 查詢應找到相關 session"""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    conn = init_db(db_path)
    _seed_db(conn)

    results = search_memory(conn, "address parser 修正", limit=3)
    assert len(results) >= 1
    assert any("address_parser" in r["summary"] for r in results)

def test_search_memory_empty_query_returns_recent():
    """空查詢應回傳最近的 sessions"""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    conn = init_db(db_path)
    _seed_db(conn)

    results = search_memory(conn, "", limit=3)
    assert len(results) >= 1

def test_format_context_returns_string():
    """format_context 應回傳非空字串"""
    sessions = [
        {"summary": "修正 bug", "event_types": '["debugging"]',
         "started_at": "2026-04-14T10:00:00Z", "project_path": "/project"}
    ]
    ctx = format_context(sessions, max_tokens=500)
    assert isinstance(ctx, str)
    assert len(ctx) > 0
    assert "修正 bug" in ctx
```

- [ ] **Step 2：執行測試確認失敗**

```bash
python3 -m pytest tests/memory/test_rag.py -v
```

預期：`ModuleNotFoundError: No module named 'lib.rag'`

- [ ] **Step 3：實作 rag.py**

```python
# memory/lib/rag.py
"""FTS5 記憶查詢與 context 格式化"""

import json
import sqlite3
from typing import Any


def search_memory(
    conn: sqlite3.Connection,
    query: str,
    limit: int = 3,
) -> list[dict[str, Any]]:
    """
    查詢相關歷史 session。
    - query 非空：FTS5 全文搜尋
    - query 為空：回傳最近 limit 筆
    """
    cursor = conn.cursor()

    if query.strip():
        # FTS5 語意搜尋（BM25 排序）
        cursor.execute("""
            SELECT s.session_uuid, s.summary, s.event_types,
                   s.started_at, s.project_path, s.exchange_count
            FROM sessions s
            JOIN sessions_fts fts ON s.id = fts.rowid
            WHERE sessions_fts MATCH ?
            ORDER BY rank
            LIMIT ?
        """, (query, limit))
    else:
        # 回傳最近的 sessions
        cursor.execute("""
            SELECT session_uuid, summary, event_types,
                   started_at, project_path, exchange_count
            FROM sessions
            WHERE summary IS NOT NULL AND summary != ''
            ORDER BY started_at DESC
            LIMIT ?
        """, (limit,))

    rows = cursor.fetchall()
    return [dict(row) for row in rows]


def format_context(sessions: list[dict], max_tokens: int = 500) -> str:
    """
    將查詢結果格式化為注入 context 的 Markdown 字串。
    以 max_tokens 估算（1 token ≈ 4 字元）粗略截斷。
    """
    if not sessions:
        return ""

    max_chars = max_tokens * 4
    lines = ["## 相關歷史對話記憶\n"]

    for s in sessions:
        date = (s.get("started_at") or "")[:10]  # 只取日期部分
        event_types = s.get("event_types", "[]")
        try:
            types = json.loads(event_types)
            type_str = ", ".join(types)
        except (json.JSONDecodeError, TypeError):
            type_str = ""

        summary = s.get("summary", "")
        entry = f"- **{date}** [{type_str}]：{summary}\n"
        lines.append(entry)

        # 粗略 token 估算截斷
        if sum(len(l) for l in lines) > max_chars:
            break

    return "".join(lines)
```

- [ ] **Step 4：執行測試確認通過**

```bash
python3 -m pytest tests/memory/test_rag.py -v
```

預期：`3 passed`

- [ ] **Step 5：Commit**

```bash
git add memory/lib/rag.py tests/memory/test_rag.py
git commit -m "feat: 新增 FTS5 記憶查詢模組（rag.py）"
```

---

## Task 6：背景同步主邏輯（sync_session.py）

**Files:**
- Create: `memory/hooks/sync_session.py`

（此模組整合 parser + classifier + db，為整合測試，不另寫 unit test）

- [ ] **Step 1：實作 sync_session.py**

```python
# memory/hooks/sync_session.py
"""
背景同步邏輯：解析 JSONL → 分類 → 存入 SQLite。
由 stop_hook.py 以獨立 process 呼叫，不阻塞 Claude。
"""

import argparse
import json
import logging
import os
import re
import sys
from pathlib import Path

# 將 lib/ 加入 import 路徑
_PLUGIN_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PLUGIN_ROOT))

import yaml
from lib.db import init_db
from lib.parser import parse_session_file
from lib.classifier import classify_session

# UUID 格式驗證（防止路徑穿越攻擊）
_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


def _load_config() -> dict:
    config_path = _PLUGIN_ROOT / "config.yaml"
    with open(config_path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _setup_logging(log_path: str) -> logging.Logger:
    Path(log_path).parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        filename=log_path,
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    return logging.getLogger("memory.sync")


def _find_session_file(projects_dir: Path, session_uuid: str) -> Path | None:
    """在 ~/.claude/projects/ 下找到對應的 JSONL 檔"""
    for project_dir in projects_dir.iterdir():
        if not project_dir.is_dir():
            continue
        candidate = project_dir / f"{session_uuid}.jsonl"
        if candidate.exists():
            # 確認路徑在 projects_dir 下（防止 symlink 逃逸）
            try:
                candidate.resolve().relative_to(projects_dir.resolve())
                return candidate
            except ValueError:
                continue
    return None


def _build_summary(session) -> str:
    """取前 3 則 user 訊息的前 80 字元組成摘要"""
    user_msgs = [m.content for m in session.messages if m.role == "user"][:3]
    parts = [msg[:80].replace("\n", " ") for msg in user_msgs]
    return " | ".join(parts)


def sync(session_uuid: str, config: dict, logger: logging.Logger) -> bool:
    """
    同步單一 session 到 SQLite。
    回傳 True 表示成功寫入，False 表示跳過（已存在或無資料）。
    """
    projects_dir = Path(config["claude_projects_dir"]).expanduser()
    db_path = str(Path(config["db_path"]).expanduser())
    min_exchanges = config["rag"]["min_exchange_count"]

    # 找 JSONL 檔
    session_file = _find_session_file(projects_dir, session_uuid)
    if not session_file:
        logger.warning(f"找不到 session 檔：{session_uuid}")
        return False

    # 解析
    session = parse_session_file(str(session_file))
    if not session:
        return False

    # 過濾太短的 session
    if session.exchange_count < min_exchanges:
        logger.info(f"Session {session_uuid[:8]} 太短（{session.exchange_count} 輪），略過")
        return False

    # 分類
    event_types = classify_session(session)
    summary = _build_summary(session)

    # 寫入 DB
    conn = init_db(db_path)
    try:
        conn.execute("""
            INSERT OR IGNORE INTO sessions
                (session_uuid, project_path, started_at, ended_at,
                 exchange_count, event_types, summary)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            session.session_uuid,
            str(session_file.parent),
            session.started_at,
            session.ended_at,
            session.exchange_count,
            json.dumps(event_types, ensure_ascii=False),
            summary,
        ))
        conn.commit()
        logger.info(f"已同步 session {session_uuid[:8]}，類型：{event_types}")
        return True
    except Exception as e:
        logger.error(f"DB 寫入失敗：{e}")
        return False
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-file", type=Path, help="由 stop_hook 傳入的暫存 JSON 檔")
    args = parser.parse_args()

    config = _load_config()
    logger = _setup_logging(
        str(Path(config["log_path"]).expanduser())
    )

    # 讀取 hook input
    if args.input_file and args.input_file.exists():
        try:
            hook_input = json.loads(args.input_file.read_text(encoding="utf-8"))
        except Exception:
            hook_input = {}
        finally:
            try:
                os.unlink(args.input_file)
            except OSError:
                pass
    else:
        try:
            hook_input = json.load(sys.stdin)
        except Exception:
            hook_input = {}

    session_uuid = hook_input.get("session_id", "")

    if not session_uuid or not _UUID_RE.match(session_uuid):
        logger.warning("無效或缺少 session_id")
        return

    sync(session_uuid, config, logger)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2：手動驗證（有 Claude session 時）**

```bash
# 找一個實際的 session UUID（取最新的）
ls -lt ~/.claude/projects/*/  | grep ".jsonl" | head -3

# 手動跑同步（用實際 UUID 替換下方的 XXXXX）
cd /Users/surpend/Developer/01_project/shiba-fine-tuning-project
python3 memory/hooks/sync_session.py <<< '{"session_id": "XXXXX-XXXXX-XXXXX"}'

# 確認 DB 有資料
sqlite3 ~/.local-brain/memory.db "SELECT session_uuid, event_types, summary FROM sessions LIMIT 5;"
```

- [ ] **Step 3：Commit**

```bash
git add memory/hooks/sync_session.py
git commit -m "feat: 新增背景同步主邏輯（sync_session.py）"
```

---

## Task 7：Stop Hook 入口（stop_hook.py）

**Files:**
- Create: `memory/hooks/stop_hook.py`

- [ ] **Step 1：實作 stop_hook.py**

```python
# memory/hooks/stop_hook.py
"""
Claude Code Stop Hook 入口。
立即回應 {"continue": true}，將同步工作交給背景 process。
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

_SYNC_SCRIPT = Path(__file__).resolve().parent / "sync_session.py"


def main():
    # 讀取 hook input
    try:
        hook_input_raw = sys.stdin.read()
    except Exception:
        hook_input_raw = "{}"

    # 寫入暫存檔（cross-platform stdin piping to detached process 不可靠）
    try:
        fd, tmp_path = tempfile.mkstemp(prefix="shiba-memory-", suffix=".json")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(hook_input_raw)
    except Exception:
        # 暫存失敗時直接略過，不影響 Claude
        print(json.dumps({"continue": True}))
        return

    # 背景啟動 sync_session.py
    try:
        kwargs: dict = {
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
            "start_new_session": True,   # 脫離 Claude Code 的 process group
        }
        subprocess.Popen(
            [sys.executable, str(_SYNC_SCRIPT), "--input-file", tmp_path],
            **kwargs,
        )
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

    # 立即回應，不阻塞 Claude
    print(json.dumps({"continue": True}))


if __name__ == "__main__":
    main()
```

- [ ] **Step 2：手動測試 stop_hook.py**

```bash
# 模擬 Claude Code 呼叫 Stop Hook
echo '{"session_id": "00000000-0000-0000-0000-000000000000"}' | \
  python3 memory/hooks/stop_hook.py
```

預期輸出：`{"continue": true}`（立即回應，無延遲）

- [ ] **Step 3：Commit**

```bash
git add memory/hooks/stop_hook.py
git commit -m "feat: 新增 Stop Hook 入口，背景 spawn sync_session"
```

---

## Task 8：SessionStart Hook（session_start_hook.py）

**Files:**
- Create: `memory/hooks/session_start_hook.py`

- [ ] **Step 1：實作 session_start_hook.py**

```python
# memory/hooks/session_start_hook.py
"""
Claude Code SessionStart Hook。
查詢 SQLite 記憶，透過 hookSpecificOutput 注入相關 context。
"""

import json
import sys
from pathlib import Path

_PLUGIN_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PLUGIN_ROOT))

import yaml
from lib.db import init_db
from lib.rag import search_memory, format_context


def _load_config() -> dict:
    config_path = _PLUGIN_ROOT / "config.yaml"
    with open(config_path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def main():
    # 讀取 hook input
    try:
        hook_input = json.load(sys.stdin)
    except Exception:
        hook_input = {}

    config = _load_config()
    db_path = str(Path(config["db_path"]).expanduser())
    max_sessions = config["rag"]["max_sessions"]
    max_tokens = config["rag"]["max_context_tokens"]

    try:
        conn = init_db(db_path)

        # 以工作目錄作為查詢關鍵字（找同專案的歷史）
        cwd = hook_input.get("cwd", "")
        project_name = Path(cwd).name if cwd else ""

        sessions = search_memory(conn, project_name, limit=max_sessions)
        conn.close()

        if not sessions:
            print(json.dumps({"continue": True}))
            return

        context = format_context(sessions, max_tokens=max_tokens)

        print(json.dumps({
            "continue": True,
            "hookSpecificOutput": context,
        }))

    except Exception:
        # DB 查詢失敗不影響 Claude 啟動
        print(json.dumps({"continue": True}))


if __name__ == "__main__":
    main()
```

- [ ] **Step 2：手動測試 session_start_hook.py**

```bash
# 需要 DB 中已有資料（先執行過 Task 6 的手動驗證）
echo '{"session_id": "new-session", "cwd": "/Users/surpend/Developer/01_project/real-estate-project"}' | \
  python3 memory/hooks/session_start_hook.py
```

預期輸出：包含 `hookSpecificOutput` 的 JSON，或 `{"continue": true}`（DB 無資料時）

- [ ] **Step 3：Commit**

```bash
git add memory/hooks/session_start_hook.py
git commit -m "feat: 新增 SessionStart Hook，RAG 注入歷史 context"
```

---

## Task 9：hooks.json + 部署腳本

**Files:**
- Create: `memory/hooks/hooks.json`
- Create: `memory/setup.sh`

- [ ] **Step 1：建立 hooks.json**

```json
{
  "hooks": {
    "Stop": [
      {
        "matcher": "*",
        "hooks": [
          {
            "type": "command",
            "command": "python3 \"${CLAUDE_PLUGIN_ROOT}/hooks/stop_hook.py\""
          }
        ]
      }
    ],
    "SessionStart": [
      {
        "matcher": "startup",
        "hooks": [
          {
            "type": "command",
            "command": "python3 \"${CLAUDE_PLUGIN_ROOT}/hooks/session_start_hook.py\""
          }
        ]
      }
    ]
  }
}
```

- [ ] **Step 2：建立 setup.sh**

```bash
#!/bin/bash
# memory/setup.sh
# 將 local-brain plugin 部署到 ~/.claude/plugins/

set -e

PLUGIN_DIR="$HOME/.claude/plugins/local-brain"
SOURCE_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "==> 建立 plugin 目錄：$PLUGIN_DIR"
mkdir -p "$PLUGIN_DIR"

echo "==> 建立 symlink（source: $SOURCE_DIR）"
# 建立各子目錄 symlink
for subdir in hooks lib db; do
    TARGET="$PLUGIN_DIR/$subdir"
    if [ -L "$TARGET" ]; then
        rm "$TARGET"
    fi
    ln -s "$SOURCE_DIR/$subdir" "$TARGET"
    echo "    linked: $subdir"
done

# symlink config.yaml
CONFIG_TARGET="$PLUGIN_DIR/config.yaml"
if [ -L "$CONFIG_TARGET" ] || [ -f "$CONFIG_TARGET" ]; then
    rm "$CONFIG_TARGET"
fi
ln -s "$SOURCE_DIR/config.yaml" "$CONFIG_TARGET"
echo "    linked: config.yaml"

# 建立 .claude-plugin 標記檔
cat > "$PLUGIN_DIR/.claude-plugin" << EOF
{
  "name": "local-brain",
  "version": "0.1.0",
  "description": "個人記憶層：自動捕捉 Claude 對話，提供 RAG context 注入"
}
EOF

echo "==> 安裝 Python 依賴"
pip3 install -r "$SOURCE_DIR/requirements.txt" --quiet

echo "==> 建立資料庫目錄"
mkdir -p "$HOME/.local-brain/logs"

echo ""
echo "✅ local-brain plugin 部署完成"
echo "   Plugin 路徑：$PLUGIN_DIR"
echo "   資料庫路徑：$HOME/.local-brain/memory.db"
echo ""
echo "下一步：重啟 Claude Code 讓 hooks 生效"
```

- [ ] **Step 3：執行部署**

```bash
chmod +x memory/setup.sh
./memory/setup.sh
```

預期輸出：
```
==> 建立 plugin 目錄：/Users/surpend/.claude/plugins/local-brain
==> 建立 symlink...
✅ local-brain plugin 部署完成
```

- [ ] **Step 4：確認 plugin 結構**

```bash
ls -la ~/.claude/plugins/local-brain/
# 應看到 hooks/ lib/ db/ config.yaml 的 symlink 與 .claude-plugin 檔
```

- [ ] **Step 5：Commit**

```bash
git add memory/hooks/hooks.json memory/setup.sh
git commit -m "feat: 新增 hooks.json 與部署腳本 setup.sh"
```

---

## Task 10：端到端驗證

- [ ] **Step 1：執行所有測試確認全綠**

```bash
cd /Users/surpend/Developer/01_project/shiba-fine-tuning-project
python3 -m pytest tests/memory/ -v
```

預期：所有 tests passed，0 failures

- [ ] **Step 2：重啟 Claude Code**

關閉目前的 Claude Code session，重新開啟。

- [ ] **Step 3：確認 Stop Hook 觸發**

結束一次 Claude 對話後：
```bash
# 確認有 log 產生
tail -20 ~/.local-brain/logs/memory.log

# 確認 DB 有寫入
sqlite3 ~/.local-brain/memory.db \
  "SELECT session_uuid, event_types, exchange_count FROM sessions ORDER BY created_at DESC LIMIT 3;"
```

- [ ] **Step 4：確認 SessionStart Hook 注入 context**

開啟新 Claude Code session，確認對話開始時 context 中包含：
```
## 相關歷史對話記憶
- 2026-04-15 [debugging]：...
```

- [ ] **Step 5：最終 Commit**

```bash
git add .
git commit -m "feat: Phase 1 記憶層完成 — Stop/SessionStart Hook + SQLite FTS5 RAG"
```

---

## 自我檢查

**Spec 覆蓋確認：**
- ✅ Stop Hook → 背景解析 JSONL → SQLite 儲存（Task 5, 6）
- ✅ 事件分類（規則型）（Task 4）
- ✅ SessionStart Hook → RAG 注入（Task 8）
- ✅ Claude Code hooks.json 設定（Task 9）
- ✅ 部署到 `~/.claude/plugins/local-brain/`（Task 9）

**型別一致性確認：**
- `parse_session_file()` 回傳 `SessionData | None`，Task 6 有做 None 檢查 ✅
- `classify_session()` 接受 `SessionData`，Task 6 正確傳入 ✅
- `search_memory()` 回傳 `list[dict]`，`format_context()` 接受相同型別 ✅
- `init_db()` 回傳 `sqlite3.Connection`，各模組正確使用 ✅
