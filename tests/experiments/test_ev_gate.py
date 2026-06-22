import importlib.util
import sqlite3
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


def test_is_junk_filters_short_control_words():
    assert measure.is_junk_instruction("好") is True
    assert measure.is_junk_instruction("幫我把目前的修改 git stash 起來再切 branch") is False


def test_compute_frequencies_dedups_d4_and_drops_junk():
    # 注意：parametrize 僅做 lexical（path/file/PR/hash）歸併，不做語意同義詞折疊。
    # 故兩筆只能靠「僅 path/PR 不同」合流，不能靠「修改↔改動」這類措辭差異。
    rows = [
        # 同一 exchange 跨 3 branch 灌水（session+commands 相同）→ 應折疊為 1
        {"session_uuid": "s1", "instruction": "幫我 review PR #14 的 docs/roadmap/x.md", "commands": "git diff"},
        {"session_uuid": "s1", "instruction": "幫我 review PR #14 的 docs/roadmap/x.md", "commands": "git diff"},
        {"session_uuid": "s1", "instruction": "幫我 review PR #14 的 docs/roadmap/x.md", "commands": "git diff"},
        # 不同 session 的同型任務（僅 PR 號/路徑不同）→ 參數化後同型，計 1 次
        {"session_uuid": "s2", "instruction": "幫我 review PR #99 的 docs/note/y.md", "commands": "git diff"},
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
