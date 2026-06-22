# EV Gate 量測 Implementation Plan（Phase 1）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 寫一支唯讀離線分析腳本，量測 `exchange_embeddings` 清洗後的「指令任務重複頻率」與 EV，輸出 gate 判決（PASS/FAIL），決定是否值得建 Pattern Library。

**Architecture:** 純函數管線（parametrize → junk filter → dedup → frequency → EV/gate）+ 一個 `main()` 串接 DB 讀取與 RESULT.md 產出。零 production code 改動，唯讀 DB。純函數獨立單元測試；`main()` 為整合產報告。

**Tech Stack:** Python 3、sqlite3（stdlib）、pytest。複用 `layer_1_memory/lib/rag.py` 既有查詢側閘（`is_short_query` / `is_system_meta_query`）。

## Global Constraints

- Gate 判準（design §4，Shiba 採保守預設）：**PASS** 若清洗後存在 **≥ 20** 個 distinct task-pattern 頻率 **≥ 3**，且這些 pattern 覆蓋 **≥ 25%** 的非-junk 任務量。
- frequency 單位 = distinct `(session_uuid, commands)` per parametrized-pattern（去掉跨 branch 同一 exchange 的 D4 verbatim 灌水）。
- 採納天花板 = **0.13**（EV 估算上界）。
- DB 路徑：`data/shiba-brain.db`（唯讀開啟）。
- 高發散控制詞於 SQL 讀取階段過濾：複用 production `_vector_search` 的 `HAVING count(DISTINCT commands) < 3`。
- 純結構 junk 過濾：`is_short_query`（≤15 字）OR `is_system_meta_query`，皆來自 `rag.py`（零 DB）。
- 負結果照實寫，不裝飾（運作宗旨：證據留痕）。

---

### Task 1: 腳本骨架 + 指令參數化 `parametrize_instruction`

**Files:**
- Create: `experiments/2026-06-22_ev_gate/measure.py`
- Create: `experiments/2026-06-22_ev_gate/__init__.py`（空檔，使其可 import）
- Test: `tests/experiments/test_ev_gate.py`
- Create: `tests/experiments/__init__.py`（空檔）

**Interfaces:**
- Produces: `parametrize_instruction(text: str) -> str` — 把 repo 路徑 / 檔名 / branch / PR 號 / commit hash 替換成變數槽 `{path}` `{file}` `{branch}` `{pr}` `{hash}`，讓同型任務歸併。

- [ ] **Step 1: 建空 `__init__.py` 兩個**

```bash
mkdir -p experiments/2026-06-22_ev_gate tests/experiments
touch experiments/2026-06-22_ev_gate/__init__.py tests/experiments/__init__.py
```

- [ ] **Step 2: Write the failing test**

```python
# tests/experiments/test_ev_gate.py
import importlib.util
from pathlib import Path

# 動態載入 experiments 腳本（目錄名以數字開頭、非合法 module name）
_spec = importlib.util.spec_from_file_location(
    "ev_gate_measure",
    Path(__file__).resolve().parents[2] / "experiments" / "2026-06-22_ev_gate" / "measure.py",
)
measure = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(measure)


def test_parametrize_collapses_concrete_paths_and_ids():
    # 同型任務、僅路徑/PR 不同 → 參數化後應相等
    a = measure.parametrize_instruction("幫我 review PR #14 的 docs/roadmap/x.md")
    b = measure.parametrize_instruction("幫我 review PR #99 的 docs/note/y.md")
    assert a == b
    assert "{pr}" in a and "{path}" in a
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/experiments/test_ev_gate.py::test_parametrize_collapses_concrete_paths_and_ids -v`
Expected: FAIL（`measure.py` 不存在 / `parametrize_instruction` 未定義）

- [ ] **Step 4: Write minimal implementation**

```python
# experiments/2026-06-22_ev_gate/measure.py
"""EV gate 量測腳本（Phase 1，唯讀離線分析）。

量測 exchange_embeddings 清洗後的指令任務重複頻率與 EV，輸出 gate 判決。
不改 production code、不寫 DB。
"""
import re

# 參數化規則：順序重要（先吃較長/較具體的樣式）
_PR_RE = re.compile(r"#\s*\d+|PR\s*\d+", re.IGNORECASE)
_HASH_RE = re.compile(r"\b[0-9a-f]{7,40}\b")          # git commit hash
_PATH_RE = re.compile(r"[\w./-]*/[\w./-]+")           # 含 / 的路徑
_FILE_RE = re.compile(r"\b[\w-]+\.[A-Za-z0-9]{1,5}\b")  # 檔名.副檔名


def parametrize_instruction(text: str) -> str:
    """把具體路徑/檔名/PR/hash 替換成變數槽，歸併同型任務。"""
    s = text or ""
    s = _PR_RE.sub("{pr}", s)
    s = _HASH_RE.sub("{hash}", s)
    s = _PATH_RE.sub("{path}", s)
    s = _FILE_RE.sub("{file}", s)
    return s.strip()
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/experiments/test_ev_gate.py::test_parametrize_collapses_concrete_paths_and_ids -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add experiments/2026-06-22_ev_gate tests/experiments
git commit -m "feat(ev-gate): 指令參數化 parametrize_instruction + 骨架"
```

---

### Task 2: junk 過濾 `is_junk_instruction`（複用 rag.py 閘）

**Files:**
- Modify: `experiments/2026-06-22_ev_gate/measure.py`
- Test: `tests/experiments/test_ev_gate.py`

**Interfaces:**
- Consumes: `rag.is_short_query`, `rag.is_system_meta_query`（`layer_1_memory/lib/rag.py`，皆零 DB 純結構）。
- Produces: `is_junk_instruction(text: str) -> bool` — 短控制詞或系統 meta query 視為 junk。

- [ ] **Step 1: Write the failing test**

```python
def test_is_junk_filters_short_control_words():
    assert measure.is_junk_instruction("好") is True          # 短控制詞
    assert measure.is_junk_instruction("做git stash pop") is False  # 真實任務（>15 字界內仍保留）
```

註：`is_short_query` 門檻為「去空白後 `<= 15` 字」。`"做git stash pop"` 去空白 13 字 → 會被判 junk。改用一個明確 >15 字的真實任務避免誤判：

```python
def test_is_junk_filters_short_control_words():
    assert measure.is_junk_instruction("好") is True
    assert measure.is_junk_instruction("幫我把目前的修改 git stash 起來再切 branch") is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/experiments/test_ev_gate.py::test_is_junk_filters_short_control_words -v`
Expected: FAIL（`is_junk_instruction` 未定義）

- [ ] **Step 3: Write minimal implementation**

在 `measure.py` 頂部加 import（用絕對路徑插入 sys.path，因從 experiments 子目錄執行）：

```python
import sys
from pathlib import Path

# 讓 measure.py 可 import 專案 layer_1_memory.lib.rag
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from layer_1_memory.lib import rag  # noqa: E402
```

新增函數：

```python
def is_junk_instruction(text: str) -> bool:
    """短控制詞或系統 meta query 視為 junk（複用 production 查詢側閘）。"""
    return rag.is_short_query(text) or rag.is_system_meta_query(text)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/experiments/test_ev_gate.py::test_is_junk_filters_short_control_words -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add experiments/2026-06-22_ev_gate/measure.py tests/experiments/test_ev_gate.py
git commit -m "feat(ev-gate): junk 過濾複用 rag.py 查詢側閘"
```

---

### Task 3: 頻率統計 + EV/gate 判決（純函數）

**Files:**
- Modify: `experiments/2026-06-22_ev_gate/measure.py`
- Test: `tests/experiments/test_ev_gate.py`

**Interfaces:**
- Consumes: `parametrize_instruction`, `is_junk_instruction`（Task 1/2）。
- Produces:
  - `compute_pattern_frequencies(rows: list[dict]) -> dict[str, int]` — rows 每筆含 `instruction` / `commands` / `session_uuid`；去 junk → 去 D4（distinct `(session_uuid, commands)`）→ 參數化 → 群組計數。回傳 `{parametrized_pattern: frequency}`。
  - `evaluate_gate(freqs: dict[str, int], min_patterns: int = 20, min_freq: int = 3, min_coverage: float = 0.25, adoption_ceiling: float = 0.13) -> dict` — 回傳 `{passed: bool, qualifying_patterns: int, coverage: float, ev_calls_saved: float, histogram: dict}`。

- [ ] **Step 1: Write the failing test**

```python
def test_compute_frequencies_dedups_d4_and_drops_junk():
    rows = [
        # 同一 exchange 跨 3 branch 灌水（session+commands 相同）→ 應折疊為 1
        {"session_uuid": "s1", "instruction": "幫我把修改 git stash 起來再切 branch", "commands": "git stash"},
        {"session_uuid": "s1", "instruction": "幫我把修改 git stash 起來再切 branch", "commands": "git stash"},
        {"session_uuid": "s1", "instruction": "幫我把修改 git stash 起來再切 branch", "commands": "git stash"},
        # 不同 session 的同型任務 → 計 1 次
        {"session_uuid": "s2", "instruction": "幫我把改動 git stash 起來再切 branch", "commands": "git stash"},
        # junk 短控制詞 → 丟棄
        {"session_uuid": "s3", "instruction": "好", "commands": "noop"},
    ]
    freqs = measure.compute_pattern_frequencies(rows)
    # 兩句參數化後同型，s1（D4 折疊後 1）+ s2（1）= 2
    assert max(freqs.values()) == 2
    assert all("好" not in k for k in freqs)


def test_evaluate_gate_fail_when_too_few_patterns():
    freqs = {"pattern_a": 5, "pattern_b": 1, "pattern_c": 1}
    report = measure.evaluate_gate(freqs, min_patterns=20, min_freq=3, min_coverage=0.25)
    assert report["passed"] is False
    assert report["qualifying_patterns"] == 1  # 只有 pattern_a 達 >=3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/experiments/test_ev_gate.py -k "frequencies or gate" -v`
Expected: FAIL（兩函數未定義）

- [ ] **Step 3: Write minimal implementation**

```python
from collections import Counter


def compute_pattern_frequencies(rows: list[dict]) -> dict[str, int]:
    """去 junk → 去 D4 verbatim 灌水 → 參數化 → 計頻。

    frequency 單位 = distinct (session_uuid, commands) per parametrized-pattern。
    """
    seen: set[tuple[str, str]] = set()
    counter: Counter[str] = Counter()
    for r in rows:
        instr = r["instruction"]
        if is_junk_instruction(instr):
            continue
        d4_key = (r["session_uuid"], r["commands"])
        if d4_key in seen:
            continue  # 同 session 同 commands = D4 跨 branch verbatim 副本
        seen.add(d4_key)
        counter[parametrize_instruction(instr)] += 1
    return dict(counter)


def evaluate_gate(
    freqs: dict[str, int],
    min_patterns: int = 20,
    min_freq: int = 3,
    min_coverage: float = 0.25,
    adoption_ceiling: float = 0.13,
) -> dict:
    """計 gate 判決：合格 pattern 數 / 覆蓋率 / EV，回傳判決字典。"""
    total_occurrences = sum(freqs.values())
    qualifying = {k: v for k, v in freqs.items() if v >= min_freq}
    qualifying_occurrences = sum(qualifying.values())
    coverage = (qualifying_occurrences / total_occurrences) if total_occurrences else 0.0
    # EV = 合格 pattern 的重複占用量 × 採納天花板（可省的 Claude 呼叫上界）
    ev_calls_saved = qualifying_occurrences * adoption_ceiling
    passed = (len(qualifying) >= min_patterns) and (coverage >= min_coverage)
    # 頻率直方圖
    buckets = {"1": 0, "2-4": 0, "5-9": 0, "10+": 0}
    for v in freqs.values():
        if v == 1:
            buckets["1"] += 1
        elif v <= 4:
            buckets["2-4"] += 1
        elif v <= 9:
            buckets["5-9"] += 1
        else:
            buckets["10+"] += 1
    return {
        "passed": passed,
        "qualifying_patterns": len(qualifying),
        "coverage": round(coverage, 3),
        "ev_calls_saved": round(ev_calls_saved, 1),
        "total_patterns": len(freqs),
        "total_occurrences": total_occurrences,
        "histogram": buckets,
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/experiments/test_ev_gate.py -k "frequencies or gate" -v`
Expected: PASS（2 passed）

- [ ] **Step 5: Commit**

```bash
git add experiments/2026-06-22_ev_gate/measure.py tests/experiments/test_ev_gate.py
git commit -m "feat(ev-gate): 頻率統計 + EV/gate 判決純函數"
```

---

### Task 4: `main()` 串接 DB 讀取 → 產出 RESULT.md

**Files:**
- Modify: `experiments/2026-06-22_ev_gate/measure.py`
- Create（執行時產出）: `experiments/2026-06-22_ev_gate/RESULT.md`

**Interfaces:**
- Consumes: `compute_pattern_frequencies`, `evaluate_gate`（Task 3）。
- Produces: `load_rows(db_path: str) -> list[dict]`（唯讀讀 exchange_embeddings，套 production 高發散過濾）+ `main()`。

- [ ] **Step 1: Write the failing test（load_rows SQL 過濾正確）**

```python
import sqlite3


def test_load_rows_applies_divergence_filter(tmp_path):
    db = tmp_path / "t.db"
    conn = sqlite3.connect(db)
    conn.execute("""CREATE TABLE exchange_embeddings(
        session_uuid TEXT, instruction TEXT, commands TEXT)""")
    # 高發散指令：同 instruction 對 3 種 commands → 應被過濾
    for c in ["a", "b", "c"]:
        conn.execute("INSERT INTO exchange_embeddings VALUES('s','繼續',?)", (c,))
    # 正常指令
    conn.execute("INSERT INTO exchange_embeddings VALUES('s','幫我跑 pytest 全量測試','pytest')")
    conn.commit()
    conn.close()
    rows = measure.load_rows(str(db))
    instrs = {r["instruction"] for r in rows}
    assert "繼續" not in instrs          # 高發散被 SQL 過濾
    assert "幫我跑 pytest 全量測試" in instrs
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/experiments/test_ev_gate.py::test_load_rows_applies_divergence_filter -v`
Expected: FAIL（`load_rows` 未定義）

- [ ] **Step 3: Write minimal implementation**

```python
import sqlite3

_DEFAULT_DB = str(_PROJECT_ROOT / "data" / "shiba-brain.db")

# 與 production _vector_search 一致：過濾「一句話對應 >=3 種 commands」的高發散控制詞
_LOAD_SQL = """
    SELECT session_uuid, instruction, commands
    FROM exchange_embeddings
    WHERE instruction IN (
        SELECT instruction FROM exchange_embeddings
        GROUP BY instruction HAVING count(DISTINCT commands) < 3
    )
"""


def load_rows(db_path: str = _DEFAULT_DB) -> list[dict]:
    """唯讀讀 exchange_embeddings，套 production 高發散過濾。"""
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(_LOAD_SQL).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def _render_result_md(report: dict, top_patterns: list[tuple[str, int]]) -> str:
    verdict = "✅ PASS" if report["passed"] else "❌ FAIL"
    lines = [
        "# EV Gate 量測結果（Phase 1）",
        "",
        f"> 判決：**{verdict}**（門檻：≥20 patterns 頻率≥3 且覆蓋≥25%）",
        "",
        "## 指標",
        f"- 清洗後 distinct task-pattern：{report['total_patterns']}",
        f"- 總 occurrence（去 junk+去 D4）：{report['total_occurrences']}",
        f"- 合格 pattern（頻率≥3）：{report['qualifying_patterns']}",
        f"- 覆蓋率：{report['coverage']}",
        f"- EV（可省 Claude 呼叫上界 @13%）：{report['ev_calls_saved']}",
        "",
        "## 頻率直方圖",
        f"- 1（一次性）：{report['histogram']['1']}",
        f"- 2-4：{report['histogram']['2-4']}",
        f"- 5-9：{report['histogram']['5-9']}",
        f"- 10+：{report['histogram']['10+']}",
        "",
        "## Top 20 重複 pattern",
    ]
    for pat, freq in top_patterns[:20]:
        lines.append(f"- [{freq}×] {pat}")
    return "\n".join(lines) + "\n"


def main() -> None:
    rows = load_rows()
    freqs = compute_pattern_frequencies(rows)
    report = evaluate_gate(freqs)
    top = sorted(freqs.items(), key=lambda kv: kv[1], reverse=True)
    out_path = Path(__file__).resolve().parent / "RESULT.md"
    out_path.write_text(_render_result_md(report, top), encoding="utf-8")
    print(f"gate passed={report['passed']} qualifying={report['qualifying_patterns']} "
          f"coverage={report['coverage']} -> {out_path}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/experiments/test_ev_gate.py::test_load_rows_applies_divergence_filter -v`
Expected: PASS

- [ ] **Step 5: 跑全量測試確認無回歸**

Run: `pytest tests/experiments/ -v`
Expected: 全 PASS（4 tests）

- [ ] **Step 6: 實際執行產出 RESULT.md**

Run: `python experiments/2026-06-22_ev_gate/measure.py`
Expected: 印出 `gate passed=... qualifying=... coverage=...` 並生成 `experiments/2026-06-22_ev_gate/RESULT.md`

- [ ] **Step 7: Commit**

```bash
git add experiments/2026-06-22_ev_gate/measure.py experiments/2026-06-22_ev_gate/RESULT.md tests/experiments/test_ev_gate.py
git commit -m "feat(ev-gate): main 串接 DB 讀取 + 產出 RESULT.md gate 判決"
```

---

## Gate 後決策（非本 plan 範圍，記錄供 Shiba 判讀）

- **PASS** → 進 design §5 Phase 2（HyDE），更新 memory Active Plan。
- **FAIL** → 高價值負結果：指令重複頻率不足以撐 Library，省下 Phase 2+ 所有 build；回 advisor 校準是否改走「不建 Library、純查詢側 HyDE 改善現有召回」的退路。

## Self-Review

1. **Spec coverage**：design §4 的 4 個清洗步驟 — 去 junk（Task 2）/ 去 D4（Task 3 dedup）/ 參數化（Task 1）/ 頻率+EV（Task 3）/ gate 判準（Task 3 evaluate_gate）/ RESULT.md 產出（Task 4）全覆蓋。✅
2. **Placeholder scan**：無 TBD/TODO，每步含實際 code。✅
3. **Type consistency**：`parametrize_instruction`/`is_junk_instruction`/`compute_pattern_frequencies`/`evaluate_gate`/`load_rows` 跨 task 簽章一致；`evaluate_gate` 回傳 dict 鍵（passed/qualifying_patterns/coverage/ev_calls_saved/histogram）與 `_render_result_md` 消費一致。✅
4. **Side-effect**：唯讀 DB（`mode=ro` URI）、只寫 experiments/ 目錄，無 production 副作用。✅
