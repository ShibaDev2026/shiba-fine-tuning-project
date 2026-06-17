"""grading_harness 單元 + E2E 測試（v1 grading harness）。

import 解析沿用 tests/layer2 慣例：sys.path 插專案根使 `from layer_2_chamber...` 可解析；
freeze_golden_set 則改以檔案路徑載入（見 _load_freeze_golden_set），避免全量測試時
layer_1_memory/scripts 佔用 sys.modules['scripts'] 造成套件名衝突而 import 失敗。
"""

import importlib.util
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


def _load_freeze_golden_set():
    """以絕對檔案路徑載入 scripts/freeze_golden_set.py，繞過 scripts 套件名衝突。

    全量測試時 layer1/layer3 會把 layer_1_memory 插上 sys.path，使
    sys.modules['scripts'] 綁到 layer_1_memory/scripts；`from scripts import ...`
    會解析錯套件。該模組自身會把專案根插入 sys.path，故 shiba_config 仍可解析。
    """
    path = Path(__file__).parent.parent.parent / "scripts" / "freeze_golden_set.py"
    spec = importlib.util.spec_from_file_location("_tierB_freeze_golden_set", path)
    if spec is None or spec.loader is None:          # fail-closed：路徑錯則明確報錯，不靜默
        raise ImportError(f"無法載入 freeze_golden_set：{path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

# 鏡像 live DB 真實約束（CHECK / question_id FK / 題庫兩表）：刻意不放寬，
# 避免測試 schema 過鬆遮蔽真實 CHECK 失敗（先前 source='question_bank' 即栽在此）。
_SCHEMA_SQL = """
CREATE TABLE question_sets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    event_type TEXT NOT NULL,
    description TEXT
);
CREATE TABLE questions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    set_id INTEGER NOT NULL REFERENCES question_sets(id),
    prompt TEXT NOT NULL,
    difficulty INTEGER NOT NULL DEFAULT 5,
    is_active INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE training_samples (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL DEFAULT 'layer1_bridge'
        CHECK(source IN ('layer1_bridge','layer1_bridge_v2','error_repair')),
    session_id TEXT,
    question_id INTEGER REFERENCES questions(id),
    teacher_id INTEGER,
    event_type TEXT NOT NULL,
    instruction TEXT NOT NULL,
    input TEXT NOT NULL DEFAULT '',
    output TEXT NOT NULL,
    refined_instruction TEXT,
    expected_answer TEXT,
    pii_scrubbed INTEGER NOT NULL DEFAULT 0,
    score REAL,
    score_reason TEXT,
    status TEXT NOT NULL DEFAULT 'raw'
        CHECK(status IN ('raw','pending','approved','rejected','needs_review')),
    adapter_block INTEGER,
    reviewed_at TEXT,
    weight REAL NOT NULL DEFAULT 1.0,
    source_exchange_ids TEXT
);
"""


def _conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA_SQL)
    return conn


def _insert(conn, event_type, instruction, output, status="pending", expected_answer=None):
    conn.execute(
        "INSERT INTO training_samples (source, event_type, instruction, input, output, status, expected_answer) "
        "VALUES ('layer1_bridge', ?, ?, '', ?, ?, ?)",
        (event_type, instruction, output, status, expected_answer),
    )
    conn.commit()


def _seed_questions(conn):
    """種 2 個 question_set（git_ops / code_gen）+ 2 題 active question（Tier B 橋接來源）。"""
    conn.execute("INSERT INTO question_sets (id, name, event_type) VALUES (1, 'git-set', 'git_ops')")
    conn.execute("INSERT INTO question_sets (id, name, event_type) VALUES (2, 'code-set', 'code_gen')")
    conn.execute("INSERT INTO questions (id, set_id, prompt) VALUES (1, 1, 'how to git rebase?')")
    conn.execute("INSERT INTO questions (id, set_id, prompt) VALUES (2, 2, 'write a fizzbuzz')")
    conn.commit()


# ---- Task 1: PII export gate ----
def test_scrub_for_export_redacts_path_and_handle(monkeypatch):
    from layer_2_chamber.backend.services import grading_harness as gh
    monkeypatch.setattr(gh, "_sensitive_tokens", lambda: ["alice"])
    out = gh.scrub_for_export("see /Users/alice/proj/x.py and user alice")
    assert "/Users/alice" not in out   # base refiner scrub 命中路徑
    assert "alice" not in out          # runtime handle 換成 <USER>
    assert "<USER>" in out


def test_assert_clean_raises_on_residue(monkeypatch):
    from layer_2_chamber.backend.services import grading_harness as gh
    monkeypatch.setattr(gh, "_sensitive_tokens", lambda: ["alice"])
    with pytest.raises(ValueError):
        gh.assert_clean("leftover alice mention")


def test_scrub_for_export_redacts_email():
    # 不 stub：跑真實 gate（含 email redaction），對齊實機 git_ops 樣本含 author email 的情況
    from layer_2_chamber.backend.services import grading_harness as gh
    out = gh.scrub_for_export("ping noreply@anthropic.com or a.b@x.org now")
    assert "@" not in out
    assert "<EMAIL>" in out


def test_assert_clean_raises_on_email():
    from layer_2_chamber.backend.services import grading_harness as gh
    with pytest.raises(ValueError):  # fail-closed：殘留 email → 不送 Claude
        gh.assert_clean("reach me at someone@example.com")


# ---- Task 2: export_gold_candidates ----
def test_export_balances_and_scrubs(monkeypatch):
    from layer_2_chamber.backend.services import grading_harness as gh
    monkeypatch.setattr(gh, "_sensitive_tokens", lambda: ["alice"])
    conn = _conn()
    _insert(conn, "git_ops", "do git in /Users/alice/p/x", "rm /Users/alice/p")
    _insert(conn, "code_gen", "write code for alice", "print('alice')")
    batch = gh.export_gold_candidates(conn, tier="B", batch_size=14)
    assert batch["tier"] == "B"
    assert len(batch["candidates"]) == 2
    for c in batch["candidates"]:
        joined = c["instruction"] + c["input"] + c["output"]
        assert "alice" not in joined
        assert "/Users/alice" not in joined


# ---- Task 3: ingest_grades ----
def test_ingest_writes_score_status_and_expected():
    from layer_2_chamber.backend.services import grading_harness as gh
    conn = _conn()
    _insert(conn, "git_ops", "instr", "out", status="pending")
    sid = conn.execute("SELECT id FROM training_samples").fetchone()["id"]
    graded = {"tier": "B", "grades": [
        {"sample_id": sid, "score": 9.5, "reason": "good", "status": "approved",
         "expected_output": "the ideal answer"},
    ]}
    res = gh.ingest_grades(conn, graded)
    assert res["applied"] == 1
    row = conn.execute(
        "SELECT score, status, score_reason, expected_answer "
        "FROM training_samples WHERE id=?", (sid,),
    ).fetchone()
    assert row["score"] == 9.5
    assert row["status"] == "approved"
    assert row["score_reason"] == "good"
    assert row["expected_answer"] == "the ideal answer"


# ---- Task 4: drain_pending ----
def test_drain_pending_loops_until_empty(monkeypatch):
    from layer_2_chamber.backend.services import grading_harness as gh
    from layer_2_chamber.backend.core import background
    calls = {"n": 0}
    def fake_score(conn_factory):       # 前 2 輪各評 1 筆，第 3 輪無 pending
        calls["n"] += 1
        return {"scored": 1, "failed": 0} if calls["n"] <= 2 else {"scored": 0, "failed": 0}
    monkeypatch.setattr(background, "score_pending_samples", fake_score)
    res = gh.drain_pending(lambda: None, max_rounds=10)
    assert res["scored"] == 2
    assert res["rounds"] == 3           # 2 評 + 1 偵測空


# ---- Task 5: harness_progress + freeze COALESCE ----
def test_harness_progress_counts():
    from layer_2_chamber.backend.services import grading_harness as gh
    conn = _conn()
    _insert(conn, "git_ops", "a", "o", status="pending")
    _insert(conn, "git_ops", "b", "o", status="approved")
    _insert(conn, "code_gen", "c", "o", status="rejected")
    prog = gh.harness_progress(conn)
    assert prog["training_samples"]["git_ops"]["pending"] == 1
    assert prog["training_samples"]["git_ops"]["approved"] == 1
    assert prog["gold"] == {}           # gold 表未建 → 空（OperationalError 吞成 {}）


def test_freeze_prefers_expected_answer(tmp_path):
    freeze_golden_set = _load_freeze_golden_set()
    dbfile = str(tmp_path / "t.db")
    conn = sqlite3.connect(dbfile); conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA_SQL)
    conn.execute(
        "INSERT INTO training_samples (source,event_type,instruction,input,output,expected_answer,status,score) "
        "VALUES ('layer1_bridge','git_ops','i','','RAW_OUT','GOLD_ANS','approved',9.5)")
    conn.commit(); conn.close()
    freeze_golden_set.main(dry_run=False, db_path=dbfile)
    conn = sqlite3.connect(dbfile); conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT expected_output FROM gatekeeper_golden_samples").fetchone()
    assert row["expected_output"] == "GOLD_ANS"   # 取 expected_answer 而非 RAW_OUT


# ---- Task 6: E2E ----
def test_e2e_tierB_export_ingest_freeze(tmp_path, monkeypatch):
    from layer_2_chamber.backend.services import grading_harness as gh
    freeze_golden_set = _load_freeze_golden_set()
    monkeypatch.setattr(gh, "_sensitive_tokens", lambda: ["alice"])
    dbfile = str(tmp_path / "e2e.db")
    conn = sqlite3.connect(dbfile); conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA_SQL)
    conn.execute(
        "INSERT INTO training_samples (source,event_type,instruction,input,output,status) "
        "VALUES ('layer1_bridge','git_ops','do git for alice','','git commit','pending')")
    conn.commit()
    # 1) export：Claude 視角拿到 scrubbed 候選
    batch = gh.export_gold_candidates(conn, tier="B", batch_size=7)
    assert len(batch["candidates"]) == 1
    sid = batch["candidates"][0]["sample_id"]
    assert "alice" not in batch["candidates"][0]["instruction"]
    # 2) Claude 評分 + 親手寫 expected_output → ingest
    graded = {"tier": "B", "grades": [
        {"sample_id": sid, "score": 9.5, "reason": "ok", "status": "approved",
         "expected_output": "git commit -m '...'"}]}
    gh.ingest_grades(conn, graded)
    conn.close()
    # 3) freeze → gold 長出，且取 Claude 答案
    freeze_golden_set.main(dry_run=False, db_path=dbfile)
    conn = sqlite3.connect(dbfile); conn.row_factory = sqlite3.Row
    n = conn.execute("SELECT COUNT(*) FROM gatekeeper_golden_samples").fetchone()[0]
    out = conn.execute("SELECT expected_output FROM gatekeeper_golden_samples").fetchone()["expected_output"]
    assert n == 1
    assert out == "git commit -m '...'"


# ---- Task 7: Tier B 題庫橋接（bridge_questions + status 隔離 + E2E）----
def test_bridge_questions_idempotent_and_needs_review():
    from layer_2_chamber.backend.services import grading_harness as gh
    conn = _conn()
    _seed_questions(conn)
    r1 = gh.bridge_questions(conn, source="layer1_bridge_v2")
    assert r1 == {"bridged": 2, "skipped": 0}
    rows = conn.execute(
        "SELECT question_id, status, output FROM training_samples ORDER BY question_id"
    ).fetchall()
    assert [x["question_id"] for x in rows] == [1, 2]        # question_id 設為來源題 id
    assert all(x["status"] == "needs_review" for x in rows)  # 落 needs_review，不入本地 drain 池
    assert all(x["output"] == "" for x in rows)              # output 待 Claude 親評填
    # 重跑冪等：已橋接 question_id → 全 skipped，不重覆插
    r2 = gh.bridge_questions(conn, source="layer1_bridge_v2")
    assert r2 == {"bridged": 0, "skipped": 2}


def test_export_status_param_selects_needs_review():
    from layer_2_chamber.backend.services import grading_harness as gh
    conn = _conn()
    _seed_questions(conn)
    gh.bridge_questions(conn, source="layer1_bridge_v2")
    # 預設 status='pending' → 橋接列（needs_review）撈不到，與本地評分池隔離
    assert gh.export_gold_candidates(conn, tier="B", batch_size=14)["candidates"] == []
    # status='needs_review' → 撈到 2 筆待 Claude 親評
    batch = gh.export_gold_candidates(conn, tier="B", batch_size=14, status="needs_review")
    assert len(batch["candidates"]) == 2


def test_e2e_tierB_bridge_to_freeze(tmp_path):
    from layer_2_chamber.backend.services import grading_harness as gh
    freeze_golden_set = _load_freeze_golden_set()
    dbfile = str(tmp_path / "bridge_e2e.db")
    conn = sqlite3.connect(dbfile); conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA_SQL)
    _seed_questions(conn)
    # 1) bridge：題庫 → needs_review 列
    assert gh.bridge_questions(conn, source="layer1_bridge_v2")["bridged"] == 2
    # 2) export（needs_review）→ Claude 視角候選
    batch = gh.export_gold_candidates(conn, tier="B", batch_size=14, status="needs_review")
    assert len(batch["candidates"]) == 2
    # 3) Claude 親評 + 親手寫 expected_output → ingest
    grades = [
        {"sample_id": c["sample_id"], "score": 9.5, "reason": "ok",
         "status": "approved", "expected_output": f"GOLD::{c['sample_id']}"}
        for c in batch["candidates"]
    ]
    gh.ingest_grades(conn, {"tier": "B", "grades": grades})
    conn.close()
    # 4) freeze → 2 筆 gold；expected_output 取 Claude 答案；FK source_sample_id 接回原題
    freeze_golden_set.main(dry_run=False, db_path=dbfile)
    conn = sqlite3.connect(dbfile); conn.row_factory = sqlite3.Row
    gold = conn.execute(
        "SELECT g.expected_output, g.source_sample_id, t.question_id "
        "FROM gatekeeper_golden_samples g "
        "JOIN training_samples t ON t.id = g.source_sample_id ORDER BY g.id"
    ).fetchall()
    assert len(gold) == 2
    assert all(x["expected_output"].startswith("GOLD::") for x in gold)
    assert {x["question_id"] for x in gold} == {1, 2}  # FK 接回原題庫 question
