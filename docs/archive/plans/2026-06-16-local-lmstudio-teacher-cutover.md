# 付費 Teacher → 本地 LM Studio 裁判切換 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 將 Layer 2 評分裁判從付費 API（Gemini/Claude…）硬切換為本地模型，透過 LM Studio 的 OpenAI 相容 server 擔任三方投票裁判。

**Architecture:** LM Studio 單一閘道（`http://localhost:1234/v1`）承載 3 個異質家族裁判（Qwen / GLM / gemma），全走既有 `OpenAICompatClient`。付費 teacher 設 `is_active=0` 保留可回滾。補一處 thinking 控制使本地裁判穩定吐 JSON。

**Tech Stack:** Python 3.14、SQLite、OpenAI SDK（指向 LM Studio）、LM Studio `lms` CLI、pytest。

**設計來源：** `docs/superpowers/specs/2026-06-16-local-lmstudio-teacher-cutover-design.md`

---

## 規劃時發現的 spec 精修（務必遵守）
- **vendor 用「家族」標記**（`local-qwen` / `local-glm` / `local-gemma`），不是 `local-lmstudio`。原因：`multi_judge._collect_votes` 的 C1 早停需 **≥2 distinct vendor** 才提前停止；3 active 裁判本就 3 家族，用家族標記直接滿足早停且更誠實。runtime（LM Studio）由 `api_base` 表達。

## File Structure
| 檔案 | 責任 | 動作 |
|------|------|------|
| `layer_2_chamber/backend/services/teacher_service.py` | Teacher CRUD + 呼叫 | Modify：`upsert_teacher` 加 vendor；新增 `set_teacher_active`；`_call_openai_compat`/`_call_teacher` 帶 `disable_thinking` |
| `clients/openai_compat/client.py` | OpenAI-compat 呼叫 | Modify：`generate` 加 `disable_thinking`；新增 `_apply_thinking_control` |
| `layer_2_chamber/scripts/setup_teachers.py` | Teacher seed/維運 CLI | Modify：新增 `LOCAL_JUDGES`/`PAID_TEACHER_NAMES`/`cmd_cutover`；`cmd_verify` 支援本地 + server 前置檢查 |
| `tests/layer2/test_teacher_service.py` | teacher_service 測試 | Modify：加 vendor / set_active / disable_thinking 測試 |
| `tests/clients/test_openai_compat_thinking.py` | client thinking 測試 | Create |
| `tests/layer2/test_setup_cutover.py` | cutover 流程測試 | Create |
| `CLAUDE.md` / `CHANGELOG.md` / memory | 文件同步 | Modify（最後一個 commit） |

---

## Task 1: `upsert_teacher` 支援寫入 vendor

**Files:**
- Modify: `layer_2_chamber/backend/services/teacher_service.py:116-158`
- Test: `tests/layer2/test_teacher_service.py`

- [ ] **Step 1: 寫失敗測試**

加到 `tests/layer2/test_teacher_service.py`（檔案頂部 import 已有 `upsert_teacher`、`_make_db`）：

```python
class TestTeacherVendor:
    def test_upsert_writes_vendor(self, tmp_path):
        conn = _make_db(tmp_path)
        tid = upsert_teacher(
            conn, name="J-Qwen", model_id="qwen3.5-27b",
            api_base="http://localhost:1234/v1", keychain_ref=None,
            vendor="local-qwen",
        )
        row = conn.execute("SELECT vendor FROM teachers WHERE id=?", (tid,)).fetchone()
        assert row["vendor"] == "local-qwen"

    def test_upsert_vendor_defaults_unknown(self, tmp_path):
        conn = _make_db(tmp_path)
        tid = upsert_teacher(
            conn, name="J-Default", model_id="m",
            api_base="http://x", keychain_ref=None,
        )
        row = conn.execute("SELECT vendor FROM teachers WHERE id=?", (tid,)).fetchone()
        assert row["vendor"] == "unknown"
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `pytest tests/layer2/test_teacher_service.py::TestTeacherVendor -q`
Expected: FAIL（`upsert_teacher()` 收到非預期 kwarg `vendor`）

- [ ] **Step 3: 改 `upsert_teacher` 簽章與 SQL**

把簽章末端加入 `vendor` 參數：

```python
def upsert_teacher(
    conn: sqlite3.Connection,
    name: str,
    model_id: str,
    api_base: str,
    keychain_ref: str | None = None,
    priority: int = 0,
    daily_limit: int = 250,
    daily_request_limit: int | None = None,
    daily_token_limit: int | None = None,
    quota_reset_period: str = "daily",
    vendor: str = "unknown",
) -> int:
```

UPDATE 分支改為（加 `vendor=?`）：

```python
        conn.execute(
            """UPDATE teachers SET model_id=?, api_base=?, keychain_ref=?,
               priority=?, daily_limit=?, daily_request_limit=?,
               daily_token_limit=?, quota_reset_period=?, vendor=? WHERE id=?""",
            (model_id, api_base, keychain_ref, priority, daily_limit,
             daily_request_limit, daily_token_limit, quota_reset_period, vendor,
             existing["id"]),
        )
```

INSERT 分支改為（加 `vendor` 欄與值）：

```python
    cur = conn.execute(
        """INSERT INTO teachers
               (name, model_id, api_base, keychain_ref, priority, daily_limit,
                daily_request_limit, daily_token_limit, quota_reset_period, vendor)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (name, model_id, api_base, keychain_ref, priority, daily_limit,
         daily_request_limit, daily_token_limit, quota_reset_period, vendor),
    )
```

- [ ] **Step 4: 跑測試確認通過**

Run: `pytest tests/layer2/test_teacher_service.py::TestTeacherVendor -q`
Expected: PASS（2 passed）

- [ ] **Step 5: Commit**

```bash
git add layer_2_chamber/backend/services/teacher_service.py tests/layer2/test_teacher_service.py
git commit -m "feat(teacher): upsert_teacher 支援寫入 vendor 欄"
```

---

## Task 2: `set_teacher_active` 啟用切換函式

**Files:**
- Modify: `layer_2_chamber/backend/services/teacher_service.py`（接在 `upsert_teacher` 之後）
- Test: `tests/layer2/test_teacher_service.py`

- [ ] **Step 1: 寫失敗測試**

```python
class TestSetTeacherActive:
    def test_deactivate_existing(self, tmp_path):
        from layer_2_chamber.backend.services.teacher_service import set_teacher_active
        conn = _make_db(tmp_path)
        upsert_teacher(conn, name="Paid", model_id="m", api_base="http://x",
                       keychain_ref="r")
        assert set_teacher_active(conn, "Paid", False) is True
        row = conn.execute("SELECT is_active FROM teachers WHERE name='Paid'").fetchone()
        assert row["is_active"] == 0

    def test_unknown_name_returns_false(self, tmp_path):
        from layer_2_chamber.backend.services.teacher_service import set_teacher_active
        conn = _make_db(tmp_path)
        assert set_teacher_active(conn, "NoSuch", False) is False
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `pytest tests/layer2/test_teacher_service.py::TestSetTeacherActive -q`
Expected: FAIL（ImportError：無 `set_teacher_active`）

- [ ] **Step 3: 實作函式**

加在 `teacher_service.py` 的 `upsert_teacher` 之後：

```python
def set_teacher_active(conn: sqlite3.Connection, name: str, is_active: bool) -> bool:
    """依 name 切換 teacher 啟用狀態（硬切換用：停付費 / bench 裁判）。
    回傳是否命中至少一列（name 不存在回 False，不報錯）。"""
    cur = conn.execute(
        "UPDATE teachers SET is_active=? WHERE name=?",
        (1 if is_active else 0, name),
    )
    conn.commit()
    return cur.rowcount > 0
```

- [ ] **Step 4: 跑測試確認通過**

Run: `pytest tests/layer2/test_teacher_service.py::TestSetTeacherActive -q`
Expected: PASS（2 passed）

- [ ] **Step 5: Commit**

```bash
git add layer_2_chamber/backend/services/teacher_service.py tests/layer2/test_teacher_service.py
git commit -m "feat(teacher): 新增 set_teacher_active 啟用切換"
```

---

## Task 3: `OpenAICompatClient` 支援 disable_thinking

**Files:**
- Modify: `clients/openai_compat/client.py`（module 加 helper；`generate` 加參數）
- Test: `tests/clients/test_openai_compat_thinking.py`（Create）

- [ ] **Step 1: 寫失敗測試**

```python
"""OpenAICompatClient thinking 控制測試"""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from clients.openai_compat.client import OpenAICompatClient, _apply_thinking_control


def test_apply_thinking_control_qwen_appends_no_think():
    out = _apply_thinking_control("PROMPT", "local-qwen", True)
    assert out.endswith("/no_think")
    assert "PROMPT" in out


def test_apply_thinking_control_gemma_untouched():
    assert _apply_thinking_control("PROMPT", "local-gemma", True) == "PROMPT"


def test_apply_thinking_control_disabled_flag_off():
    assert _apply_thinking_control("PROMPT", "local-qwen", False) == "PROMPT"


def _fake_completion(content: str):
    msg = MagicMock(); msg.content = content
    choice = MagicMock(); choice.message = msg
    usage = MagicMock(); usage.prompt_tokens = 5; usage.completion_tokens = 7
    resp = MagicMock(); resp.choices = [choice]; resp.usage = usage
    return resp


def test_generate_injects_no_think_for_qwen():
    client = OpenAICompatClient(
        api_key="none", api_base="http://localhost:1234/v1", vendor="local-qwen",
    )
    fake_openai = MagicMock()
    fake_openai.chat.completions.create.return_value = _fake_completion('{"score":9,"reason":"ok"}')
    with patch("openai.OpenAI", return_value=fake_openai), \
         patch("clients.openai_compat.client.log_api_call"):
        text, _, _, status = client.generate(
            model_id="qwen3.5-27b", prompt="EVAL", disable_thinking=True,
        )
    assert status == "success"
    sent_messages = fake_openai.chat.completions.create.call_args.kwargs["messages"]
    assert "/no_think" in sent_messages[0]["content"]
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `pytest tests/clients/test_openai_compat_thinking.py -q`
Expected: FAIL（ImportError：無 `_apply_thinking_control`；或 `generate()` 不收 `disable_thinking`）

- [ ] **Step 3: 加 helper 與參數**

在 `clients/openai_compat/client.py` module 層（class 定義前，緊接 `_detect_source_type` 之後）新增：

```python
def _apply_thinking_control(prompt: str, vendor: str | None, disable_thinking: bool) -> str:
    """關閉本地裁判 thinking 以穩定吐 JSON。
    Qwen 系用 /no_think 軟開關；GLM 走 reasoning_content 分流、gemma 無強制 thinking，皆不注入。"""
    if disable_thinking and vendor and "qwen" in vendor.lower():
        return f"{prompt}\n/no_think"
    return prompt
```

`generate` 簽章加 `disable_thinking`（放 keyword-only 區），並在進入重試前先轉換 prompt：

```python
    def generate(
        self,
        model_id: str,
        prompt: str,
        max_tokens: int = 150,
        *,
        temperature: float = 0.0,
        disable_thinking: bool = False,
        caller_module: str | None = None,
        teacher_id: int | None = None,
        sample_id: int | None = None,
    ) -> tuple[str | None, int, int, str]:
```

在 `generate` 函式體最前面（`log_ctx = {...}` 之前）插入一行：

```python
        prompt = _apply_thinking_control(prompt, self._vendor, disable_thinking)
```

（`_invoke_once` 與重試已使用同一個 `prompt` 變數，故只需在此轉換一次。）

- [ ] **Step 4: 跑測試確認通過**

Run: `pytest tests/clients/test_openai_compat_thinking.py -q`
Expected: PASS（4 passed）

- [ ] **Step 5: Commit**

```bash
git add clients/openai_compat/client.py tests/clients/test_openai_compat_thinking.py
git commit -m "feat(openai-compat): generate 支援 disable_thinking（Qwen /no_think 注入）"
```

---

## Task 4: teacher_service 對本地裁判帶 disable_thinking

**Files:**
- Modify: `layer_2_chamber/backend/services/teacher_service.py:514-540`（`_call_openai_compat`）與 `:435-444`（`_call_teacher` else 分支）
- Test: `tests/layer2/test_teacher_service.py`

- [ ] **Step 1: 寫失敗測試**

```python
class TestDisableThinkingForwarded:
    def test_call_openai_compat_forwards_disable_thinking(self):
        from layer_2_chamber.backend.services import teacher_service
        fake_client = MagicMock()
        fake_client.generate.return_value = ("{}", 1, 1, "success")
        with patch("clients.openai_compat.OpenAICompatClient", return_value=fake_client):
            teacher_service._call_openai_compat(
                "none", "http://localhost:1234/v1", "qwen3.5-27b", "P",
                vendor="local-qwen", disable_thinking=True,
            )
        assert fake_client.generate.call_args.kwargs["disable_thinking"] is True
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `pytest tests/layer2/test_teacher_service.py::TestDisableThinkingForwarded -q`
Expected: FAIL（`_call_openai_compat()` 不收 `disable_thinking`）

- [ ] **Step 3: 改 `_call_openai_compat` 與 `_call_teacher`**

`_call_openai_compat` 簽章加 `disable_thinking`（keyword-only），並轉傳給 `.generate`：

```python
def _call_openai_compat(
    api_key: str,
    api_base: str,
    model_id: str,
    prompt: str,
    max_tokens: int = 150,
    *,
    vendor: str | None = None,
    disable_thinking: bool = False,
    caller_module: str | None = None,
    teacher_id: int | None = None,
    sample_id: int | None = None,
) -> tuple[str | None, int, int, str]:
```

`.generate(...)` 呼叫加一行參數：

```python
    return OpenAICompatClient(api_key, api_base, vendor=vendor).generate(
        model_id=model_id,
        prompt=prompt,
        max_tokens=max_tokens,
        disable_thinking=disable_thinking,
        caller_module=caller_module,
        teacher_id=teacher_id,
        sample_id=sample_id,
    )
```

`_call_teacher` 的 else 分支（local 路徑）改為帶入 `disable_thinking`（本地裁判 = `keychain_ref is None`）：

```python
    else:
        # 本地裁判（keychain_ref 為 None）關 thinking，使其穩定吐 JSON
        raw, input_t, output_t, status = _call_openai_compat(
            api_key, teacher["api_base"], teacher["model_id"], prompt,
            max_tokens=2048,
            vendor=_vendor_of(teacher),
            disable_thinking=(teacher["keychain_ref"] is None),
            caller_module="teacher_service",
            teacher_id=teacher["id"], sample_id=sample_id,
        )
```

- [ ] **Step 4: 跑測試確認通過**

Run: `pytest tests/layer2/test_teacher_service.py::TestDisableThinkingForwarded -q`
Expected: PASS（1 passed）

- [ ] **Step 5: Commit**

```bash
git add layer_2_chamber/backend/services/teacher_service.py tests/layer2/test_teacher_service.py
git commit -m "feat(teacher): 本地裁判呼叫帶 disable_thinking"
```

---

## Task 5: setup_teachers 新增 cutover（停付費 + seed 本地裁判）

**Files:**
- Modify: `layer_2_chamber/scripts/setup_teachers.py`（import 區、常數區、新增 `cmd_cutover`、argparse）
- Test: `tests/layer2/test_setup_cutover.py`（Create）

- [ ] **Step 1: 寫失敗測試**

```python
"""cmd_cutover 流程測試"""
import sqlite3
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from layer_2_chamber.backend.services.teacher_service import upsert_teacher

LAYER1_SCHEMA = Path(__file__).parent.parent.parent / "layer_1_memory" / "db" / "schema.sql"
LAYER2_SCHEMA = (Path(__file__).parent.parent.parent
                 / "layer_2_chamber" / "backend" / "db" / "schema_layer2.sql")


def _seed_db(path: Path) -> None:
    conn = sqlite3.connect(str(path)); conn.row_factory = sqlite3.Row
    conn.executescript(LAYER1_SCHEMA.read_text())
    conn.executescript(LAYER2_SCHEMA.read_text())
    upsert_teacher(conn, name="Gemini 2.5 Flash", model_id="gemini-2.5-flash",
                   api_base="https://g", keychain_ref="gemini-api-key")
    upsert_teacher(conn, name="Claude Sonnet 4.6", model_id="claude-sonnet-4-6",
                   api_base="https://api.anthropic.com", keychain_ref="anthropic-api-key")
    conn.commit(); conn.close()


def test_cutover_disables_paid_and_seeds_judges(tmp_path):
    db = tmp_path / "brain.db"
    _seed_db(db)
    from layer_2_chamber.scripts import setup_teachers

    def _open():
        c = sqlite3.connect(str(db)); c.row_factory = sqlite3.Row
        return c

    with patch.object(setup_teachers, "init_layer2_db", _open):
        setup_teachers.cmd_cutover()

    conn = sqlite3.connect(str(db)); conn.row_factory = sqlite3.Row
    # 付費全停
    paid = conn.execute(
        "SELECT name,is_active FROM teachers WHERE name IN ('Gemini 2.5 Flash','Claude Sonnet 4.6')"
    ).fetchall()
    assert all(r["is_active"] == 0 for r in paid)
    # 3 active 本地裁判、vendor 三家族
    active = conn.execute(
        "SELECT vendor FROM teachers WHERE is_active=1 AND keychain_ref IS NULL"
    ).fetchall()
    vendors = sorted(r["vendor"] for r in active)
    assert vendors == ["local-gemma", "local-glm", "local-qwen"]
    # 2 bench 停用
    bench = conn.execute(
        "SELECT COUNT(*) c FROM teachers WHERE is_active=0 AND keychain_ref IS NULL"
    ).fetchone()
    assert bench["c"] == 2
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `pytest tests/layer2/test_setup_cutover.py -q`
Expected: FAIL（`setup_teachers` 無 `cmd_cutover`）

- [ ] **Step 3: 實作常數與 `cmd_cutover`**

在 `setup_teachers.py` import 區補入 `set_teacher_active`：

```python
from layer_2_chamber.backend.services.teacher_service import (
    get_active_teachers,
    get_api_key,
    set_teacher_active,
    upsert_teacher,
)
```

在 `_TEST_SAMPLE` 定義之後新增常數（`model_id` 先填預估值，Task 7 會以 `/v1/models` 實際 id 校正）：

```python
# ── 本地 LM Studio 裁判（硬切換目標）─────────────────────────────────
_LMSTUDIO_BASE = "http://localhost:1234/v1"

# 付費 teacher（硬切換時 is_active=0，保留 row 可回滾）
PAID_TEACHER_NAMES = [
    "Gemini 2.5 Flash", "Gemini 2.5 Flash-Lite", "Claude Sonnet 4.6",
    "Grok 3 Mini", "GitHub Models GPT-4o-mini", "Mistral 7B",
]

# 5 裁判 = 3 active（三家族異質）+ 2 bench。model_id 以 LM Studio /v1/models 暴露者為準。
LOCAL_JUDGES = [
    {"name": "Local Qwen3.5-27B (LMS)",  "model_id": "qwen3.5-27b",   "vendor": "local-qwen",  "priority": 0, "is_active": 1},
    {"name": "Local GLM-4.7-Flash (LMS)","model_id": "glm-4.7-flash", "vendor": "local-glm",   "priority": 1, "is_active": 1},
    {"name": "Local Gemma (LMS)",        "model_id": "gemma-4-e4b",   "vendor": "local-gemma", "priority": 2, "is_active": 1},
    {"name": "Local Qwen3.5-9B (LMS)",   "model_id": "qwen3.5-9b",    "vendor": "local-qwen",  "priority": 3, "is_active": 0},
    {"name": "Local GLM-4.5 (LMS)",      "model_id": "glm-4.5",       "vendor": "local-glm",   "priority": 4, "is_active": 0},
]


def cmd_cutover():
    """硬切換：停用付費 teacher + seed 本地 LM Studio 裁判（3 active + 2 bench）。"""
    conn = init_layer2_db()
    print("=== 硬切換：付費 → 本地 LM Studio 裁判 ===\n")
    for name in PAID_TEACHER_NAMES:
        if set_teacher_active(conn, name, False):
            print(f"✓ 停用付費 teacher：{name}")
    for j in LOCAL_JUDGES:
        tid = upsert_teacher(
            conn, name=j["name"], model_id=j["model_id"], api_base=_LMSTUDIO_BASE,
            keychain_ref=None, priority=j["priority"],
            daily_limit=9999, daily_request_limit=None, daily_token_limit=None,
            quota_reset_period="none", vendor=j["vendor"],
        )
        set_teacher_active(conn, j["name"], bool(j["is_active"]))
        flag = "active" if j["is_active"] else "bench"
        print(f"✓ 本地裁判 {j['name']} id={tid}（{flag}）")
    conn.close()
    print("\n切換完成，執行 --verify 驗證連線（需先 lms server start）。")
```

在檔案末端 argparse 區（`if __name__ == "__main__":` 之後）新增 `--cutover` 分支。先讀現有 argparse 區，仿照 `--setup` / `--verify` 既有寫法加：

```python
    parser.add_argument("--cutover", action="store_true",
                        help="硬切換：停用付費 teacher 並 seed 本地 LM Studio 裁判")
```

並在分派邏輯加：

```python
    elif args.cutover:
        cmd_cutover()
```

- [ ] **Step 4: 跑測試確認通過**

Run: `pytest tests/layer2/test_setup_cutover.py -q`
Expected: PASS（1 passed）

- [ ] **Step 5: Commit**

```bash
git add layer_2_chamber/scripts/setup_teachers.py tests/layer2/test_setup_cutover.py
git commit -m "feat(teacher): setup --cutover 停付費並 seed 本地 LM Studio 裁判"
```

---

## Task 6: `cmd_verify` 支援本地裁判 + LM Studio server 前置檢查

**Files:**
- Modify: `layer_2_chamber/scripts/setup_teachers.py`（`cmd_verify` + 新增小 helper）
- Test: `tests/layer2/test_setup_cutover.py`

- [ ] **Step 1: 寫失敗測試**

加到 `tests/layer2/test_setup_cutover.py`：

```python
def test_resolve_api_key_local_returns_none_string():
    from layer_2_chamber.scripts.setup_teachers import _resolve_api_key
    local = {"keychain_ref": None}
    assert _resolve_api_key(local) == "none"

def test_resolve_api_key_remote_uses_keychain():
    from layer_2_chamber.scripts import setup_teachers
    remote = {"keychain_ref": "some-ref"}
    with patch.object(setup_teachers, "get_api_key", return_value="KEY123"):
        assert setup_teachers._resolve_api_key(remote) == "KEY123"
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `pytest tests/layer2/test_setup_cutover.py -q -k resolve_api_key`
Expected: FAIL（無 `_resolve_api_key`）

- [ ] **Step 3: 實作 helper 並改 `cmd_verify`**

新增 helper（放在 `_test_call` 附近）：

```python
def _resolve_api_key(teacher) -> str | None:
    """本地裁判（keychain_ref 為 None）回 'none'；遠端取 Keychain。"""
    ref = teacher["keychain_ref"]
    return "none" if ref is None else get_api_key(ref)


def _lmstudio_online(api_base: str) -> bool:
    """探測 LM Studio /v1/models 是否可達。"""
    import urllib.request as urlreq
    try:
        with urlreq.urlopen(api_base.rstrip("/") + "/models", timeout=3) as resp:
            return resp.status == 200
    except Exception:
        return False
```

改 `cmd_verify` 的 key 取得與前置檢查（把原本 `api_key = get_api_key(t["keychain_ref"])` 換掉，並在迴圈前對本地裁判提示 server 狀態）：

```python
def cmd_verify():
    """對每個 active Teacher 送一筆測試評分，驗證連線。"""
    conn = init_layer2_db()
    teachers = get_active_teachers(conn)
    conn.close()
    if not teachers:
        print("✗ 無可用 Teacher，請先執行 --setup / --cutover")
        return

    # 若有本地 LM Studio 裁判，先檢查 server 在線
    if any(t["keychain_ref"] is None for t in teachers):
        if not _lmstudio_online(_LMSTUDIO_BASE):
            print(f"✗ LM Studio server 未在線（{_LMSTUDIO_BASE}）。請先 `lms server start`。")
            return

    print("=== 驗證 Teacher 連線 ===\n")
    for t in teachers:
        api_key = _resolve_api_key(t)
        if not api_key:
            print(f"✗ {t['name']}：取不到 key")
            continue
        result = _test_call(t, api_key)
        if result:
            print(f"✓ {t['name']}：score={result['score']}，reason={result['reason']}")
        else:
            print(f"✗ {t['name']}：API 呼叫失敗")
```

- [ ] **Step 4: 跑測試確認通過**

Run: `pytest tests/layer2/test_setup_cutover.py -q`
Expected: PASS（全部 passed）

- [ ] **Step 5: Commit**

```bash
git add layer_2_chamber/scripts/setup_teachers.py tests/layer2/test_setup_cutover.py
git commit -m "feat(teacher): cmd_verify 支援本地裁判與 LM Studio server 前置檢查"
```

---

## Task 7: 運維 — 下載模型、載入、啟動 server、校正 model_id（手動）

**無自動測試；以指令輸出驗證。** 此步在實機執行，須有 LM Studio 與 `lms` CLI。

- [ ] **Step 1: 啟動 LM Studio server**

Run: `lms server start`
Expected: 提示 server 啟動於 `http://localhost:1234`

- [ ] **Step 2: 下載 5 個裁判模型（HF GGUF）**

```bash
lms get lmstudio-community/Qwen3.5-27B-GGUF
lms get lmstudio-community/GLM-4.7-Flash-GGUF
lms get lmstudio-community/Qwen3.5-9B-GGUF   # bench
lms get lmstudio-community/GLM-4.5-GGUF       # bench
# gemma：已裝 google/gemma-4-e4b（lms ls 可見），無需重抓
```
Expected: 各模型下載完成；`lms ls` 列出。

- [ ] **Step 3: 常駐 3 個 active 裁判**

```bash
lms load <qwen3.5-27b-id>
lms load <glm-4.7-flash-id>
lms load google/gemma-4-e4b
```
Expected: 三模型 loaded（64GB 約 25GB 佔用）。

- [ ] **Step 4: 取得實際 model_id 並校正 `LOCAL_JUDGES`**

Run: `curl -s http://localhost:1234/v1/models | python3 -m json.tool`
Expected: 列出各 model 的 `id` 字串。

將 `setup_teachers.py` 的 `LOCAL_JUDGES` 中每筆 `model_id` 改成上面 `/v1/models` 回傳的**實際 id 字串**（5 筆全部對齊；bench 的 9B / GLM-4.5 即使未常駐，id 也要正確以便日後啟用）。

- [ ] **Step 5: Commit（若 model_id 有調整）**

```bash
git add layer_2_chamber/scripts/setup_teachers.py
git commit -m "chore(teacher): LOCAL_JUDGES model_id 對齊 LM Studio /v1/models 實際 id"
```

---

## Task 8: 端到端驗證 + 文件同步

**Files:**
- Modify: `CLAUDE.md`（Teacher 配額表）、`CHANGELOG.md`、`memory/`（project 記憶）

- [ ] **Step 1: 執行切換並列出狀態**

```bash
python layer_2_chamber/scripts/setup_teachers.py --cutover
python layer_2_chamber/scripts/setup_teachers.py --list
```
Expected：6 付費顯示 `✗`（停用）；5 本地裁判存在，3 個 `✓`、2 個 `✗`。

- [ ] **Step 2: 驗證本地裁判連線吐乾淨 JSON**

Run: `python layer_2_chamber/scripts/setup_teachers.py --verify`
Expected：3 active 本地裁判各回 `score=…，reason=…`（證明 thinking 已關、JSON 可解析）。若報 server 未在線 → 先 `lms server start`。

- [ ] **Step 3: 跑 Layer 2 回歸測試**

Run: `pytest tests/layer2/ tests/clients/test_openai_compat_thinking.py -q`
Expected：全綠，且總測試數 ≥ 145 baseline（新增測試使數量上升）。

- [ ] **Step 4: 更新 CLAUDE.md 配額表**

在 `CLAUDE.md` 的「Teacher 配額表」段落標註：付費 teacher 已於 2026-06-16 硬切換停用（保留可回滾），現役裁判為本地 LM Studio 三家族（Qwen3.5-27B / GLM-4.7-Flash / gemma），api_base `http://localhost:1234/v1`，回滾方式：付費 teacher `is_active=1`。

- [ ] **Step 5: 更新 CHANGELOG.md**

在 `CHANGELOG.md` 頂部新增一筆（SemVer，minor）：

```markdown
## [x.y.0] - 2026-06-16
### Changed
- Layer 2 裁判由付費 API 硬切換為本地 LM Studio 三家族裁判（Qwen3.5-27B / GLM-4.7-Flash / gemma），去外部依賴；付費 teacher 保留 row 可回滾。
### Added
- `OpenAICompatClient.generate(disable_thinking=…)`、`set_teacher_active`、`setup_teachers --cutover`。
```

- [ ] **Step 6: 更新 memory**

更新 `memory/MEMORY.md` Recent Decisions 一筆，並更新或新增對應 project 記憶（teacher 本地化切換），連結 [[project-model-api-tools]]。

- [ ] **Step 7: Commit（文件同一個 commit）**

```bash
git add CLAUDE.md CHANGELOG.md ~/.claude/projects/*/memory/
git commit -m "docs(teacher-cutover): 付費→本地 LM Studio 裁判切換落地 + 文件/memory 同步"
```

---

## Self-Review 對照
- spec §2 雙 provider → Task 5（api_base/vendor）✓
- spec §3 5 模型編組 → Task 5 `LOCAL_JUDGES` + Task 7 下載 ✓
- spec §4 停付費 → Task 5 `cmd_cutover` + Task 2 `set_teacher_active` ✓
- spec §5 thinking 控制 → Task 3 + Task 4 ✓
- spec §6 運維 server → Task 6 前置檢查 + Task 7 ✓
- spec §9 DoD（--verify 吐 JSON、DB 狀態、log vendor）→ Task 8 ✓
- vendor 精修（家族標記滿足 ≥2 vendor 早停）→ Task 1 + Task 5 ✓
