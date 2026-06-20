# tests/memory/test_recall_log.py
"""recall_log.py + notify.py 單元測試（一行為一測）"""

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "layer_1_memory"))

from lib import recall_log
from lib import notify

_NOOP = lambda s: s  # noqa: E731 測試用無作用 scrub


def test_append_cause_writes_day_file_with_score(tmp_path):
    """vector hit：日檔含 header/問題/召回原因 + cosine 分數 + 命中內容"""
    when = datetime(2026, 6, 21, 10, 0, 0, 123000)
    hits = [{"score": 0.7777, "instruction": "做 X", "commands": "git status"}]
    recall_log.append_cause(
        tmp_path, "abcdef1234", "怎麼做 X", "vector", hits, scrub=_NOOP, when=when
    )
    day = tmp_path / "20260621.txt"
    text = day.read_text(encoding="utf-8")
    assert "[2026-06-21 10:00:00.123]" in text
    assert "[INFO][session=abcdef12]" in text
    assert "問題：怎麼做 X" in text
    assert "[召回原因] source=vector" in text
    assert "score=0.778" in text                  # 四捨五入到三位
    assert "問題：做 X / 指令：git status" in text


def test_append_cause_fts5_hit_marks_rank(tmp_path):
    """FTS5 hit 無 cosine 分數 → 標 rank fts5#N"""
    hits = [{"snippet": "某段歷史摘要"}]
    recall_log.append_cause(
        tmp_path, "sess0001", "查詢", "fts5", hits, scrub=_NOOP,
        when=datetime(2026, 6, 21),
    )
    text = (tmp_path / "20260621.txt").read_text(encoding="utf-8")
    assert "score=fts5#1" in text
    assert "某段歷史摘要" in text


def test_append_cause_applies_scrub(tmp_path):
    """scrub 注入確實作用於問題與召回內容"""
    redact = lambda s: s.replace("SECRET", "***")  # noqa: E731
    hits = [{"score": 0.5, "instruction": "my SECRET", "commands": "x"}]
    recall_log.append_cause(
        tmp_path, "s", "前 SECRET 後", "vector", hits, scrub=redact,
        when=datetime(2026, 6, 21),
    )
    text = (tmp_path / "20260621.txt").read_text(encoding="utf-8")
    assert "SECRET" not in text
    assert "***" in text


def test_day_file_name_varies_by_date(tmp_path):
    """跨日 append → 進不同日檔"""
    recall_log.append_cause(tmp_path, "s", "q1", "fts5", [{"snippet": "a"}],
                            scrub=_NOOP, when=datetime(2026, 6, 21))
    recall_log.append_cause(tmp_path, "s", "q2", "fts5", [{"snippet": "b"}],
                            scrub=_NOOP, when=datetime(2026, 6, 22))
    assert (tmp_path / "20260621.txt").exists()
    assert (tmp_path / "20260622.txt").exists()


def test_append_answer_with_pending_appends_and_clears(tmp_path):
    """有 pending：補回答（完整保留）+ 收尾，清標記，回 True"""
    when = datetime(2026, 6, 21, 10, 0, 0)
    recall_log.append_cause(tmp_path, "sess0001", "q", "vector",
                            [{"score": 0.6, "instruction": "i", "commands": "c"}],
                            scrub=_NOOP, when=when)
    assert recall_log.has_pending(tmp_path, "sess0001")

    ok = recall_log.append_answer(tmp_path, "sess0001", "這是很長的完整回答" * 3,
                                  scrub=_NOOP, when=when)
    assert ok is True
    text = (tmp_path / "20260621.txt").read_text(encoding="utf-8")
    assert "[Claude 回答]" in text
    assert "這是很長的完整回答這是很長的完整回答這是很長的完整回答" in text   # 不截斷
    assert "feed_model=false" in text
    assert "[=== END ===]" in text
    assert not recall_log.has_pending(tmp_path, "sess0001")  # 標記已清


def test_append_answer_without_pending_noops(tmp_path):
    """無 pending（本輪未召回）→ 不寫、回 False"""
    ok = recall_log.append_answer(tmp_path, "nope", "answer", scrub=_NOOP)
    assert ok is False
    assert list(tmp_path.glob("*.txt")) == []


def test_prune_deletes_expired_keeps_recent(tmp_path):
    """append 時順手刪超期日檔，保留期內日檔"""
    (tmp_path / "20200101.txt").write_text("old", encoding="utf-8")     # 超期
    (tmp_path / "20260610.txt").write_text("recent", encoding="utf-8")  # 11 天前，保留
    recall_log.append_cause(tmp_path, "s", "q", "fts5", [{"snippet": "x"}],
                            scrub=_NOOP, retention_days=30,
                            when=datetime(2026, 6, 21))
    assert not (tmp_path / "20200101.txt").exists()
    assert (tmp_path / "20260610.txt").exists()
    assert (tmp_path / "20260621.txt").exists()


def test_notify_args_escapes_and_single_lines():
    """osascript 指令字串：跳脫雙引號、換行收斂為單行"""
    args = notify._notify_args('標題"X"', "第一行\n第二行", "/usr/bin/osascript")
    assert args[0] == "/usr/bin/osascript"
    assert args[1] == "-e"
    script = args[2]
    assert '\\"X\\"' in script               # 雙引號跳脫
    assert "第一行 第二行" in script          # 換行→空白
    assert script.startswith("display notification ")
