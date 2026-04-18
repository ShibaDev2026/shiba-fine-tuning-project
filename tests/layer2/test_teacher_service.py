"""teacher_service.py 單元測試"""

import json
import sqlite3
import sys
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from layer_2_chamber.backend.services.teacher_service import (
    _SCORE_AUTO_APPROVE,
    _SCORE_AUTO_REJECT,
    get_active_teachers,
    get_today_usage,
    is_quota_available,
    score_sample,
    upsert_teacher,
)

LAYER1_SCHEMA = Path(__file__).parent.parent.parent / "layer_1_memory" / "db" / "schema.sql"
LAYER2_SCHEMA = (
    Path(__file__).parent.parent.parent
    / "layer_2_chamber" / "backend" / "db" / "schema_layer2.sql"
)


def _make_db(tmp_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(tmp_path / "test.db"))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(LAYER1_SCHEMA.read_text())
    conn.executescript(LAYER2_SCHEMA.read_text())
    conn.commit()
    return conn


def _add_teacher(conn, name="Gemini Flash", priority=0, daily_limit=250, is_active=1):
    return upsert_teacher(
        conn, name=name, model_id="gemini-2.5-flash",
        api_base="https://api.example.com", keychain_ref="test-ref",
        priority=priority, daily_limit=daily_limit,
    )


def _add_sample(conn):
    cur = conn.execute(
        """INSERT INTO training_samples
           (source, session_id, event_type, instruction, input, output, adapter_block)
           VALUES ('layer1_bridge', 'sess-t', 'git_ops', '請 commit', '', '已完成', 1)"""
    )
    conn.commit()
    return cur.lastrowid


class TestTeacherCRUD:
    def test_upsert_creates_teacher(self, tmp_path):
        conn = _make_db(tmp_path)
        tid = _add_teacher(conn)
        assert tid > 0
        teachers = get_active_teachers(conn)
        assert len(teachers) == 1
        assert teachers[0]["name"] == "Gemini Flash"

    def test_upsert_updates_existing(self, tmp_path):
        conn = _make_db(tmp_path)
        tid1 = _add_teacher(conn, name="T1", priority=0)
        tid2 = upsert_teacher(
            conn, name="T1", model_id="new-model", api_base="http://x",
            keychain_ref="ref", priority=1,
        )
        assert tid1 == tid2
        row = conn.execute("SELECT model_id, priority FROM teachers WHERE id=?", (tid1,)).fetchone()
        assert row["model_id"] == "new-model"
        assert row["priority"] == 1

    def test_priority_ordering(self, tmp_path):
        conn = _make_db(tmp_path)
        _add_teacher(conn, name="B", priority=2)
        _add_teacher(conn, name="A", priority=0)
        teachers = get_active_teachers(conn)
        assert teachers[0]["name"] == "A"


class TestQuota:
    def test_quota_available_when_under_limit(self, tmp_path):
        conn = _make_db(tmp_path)
        tid = _add_teacher(conn, daily_limit=10)
        teacher = conn.execute("SELECT * FROM teachers WHERE id=?", (tid,)).fetchone()
        assert is_quota_available(conn, teacher)

    def test_quota_exhausted_at_limit(self, tmp_path):
        conn = _make_db(tmp_path)
        tid = _add_teacher(conn, daily_limit=2)
        sid = _add_sample(conn)
        # 寫入 2 筆 usage log
        conn.execute("INSERT INTO teacher_usage_logs (teacher_id, sample_id) VALUES (?, ?)", (tid, sid))
        conn.execute("INSERT INTO teacher_usage_logs (teacher_id, sample_id) VALUES (?, ?)", (tid, sid))
        conn.commit()
        teacher = conn.execute("SELECT * FROM teachers WHERE id=?", (tid,)).fetchone()
        assert not is_quota_available(conn, teacher)

    def test_today_usage_counts_only_today(self, tmp_path):
        conn = _make_db(tmp_path)
        tid = _add_teacher(conn)
        sid = _add_sample(conn)
        # 寫入昨天的 log
        conn.execute(
            "INSERT INTO teacher_usage_logs (teacher_id, sample_id, used_at) VALUES (?, ?, date('now', '-1 day'))",
            (tid, sid),
        )
        conn.commit()
        assert get_today_usage(conn, tid) == 0


class TestScoreSample:
    def _mock_teacher_result(self, score: float):
        """回傳指定分數的 mock _call_teacher"""
        return MagicMock(return_value={"score": score, "reason": f"score={score}"})

    def test_auto_approved_when_score_ge_8(self, tmp_path):
        conn = _make_db(tmp_path)
        _add_teacher(conn)
        sid = _add_sample(conn)

        with patch("layer_2_chamber.backend.services.teacher_service._call_teacher") as mock_call, \
             patch("layer_2_chamber.backend.services.teacher_service.get_api_key", return_value="key"):
            mock_call.return_value = {"score": 9.0, "reason": "excellent"}
            result = score_sample(conn, sid, "inst", "inp", "out")

        assert result["status"] == "approved"
        assert result["score"] == 9.0
        row = conn.execute("SELECT status FROM training_samples WHERE id=?", (sid,)).fetchone()
        assert row["status"] == "approved"

    def test_auto_rejected_when_score_lt_6(self, tmp_path):
        conn = _make_db(tmp_path)
        _add_teacher(conn)
        sid = _add_sample(conn)

        with patch("layer_2_chamber.backend.services.teacher_service._call_teacher") as mock_call, \
             patch("layer_2_chamber.backend.services.teacher_service.get_api_key", return_value="key"):
            mock_call.return_value = {"score": 4.0, "reason": "poor"}
            result = score_sample(conn, sid, "inst", "inp", "out")

        assert result["status"] == "rejected"

    def test_needs_review_when_score_6_to_7(self, tmp_path):
        conn = _make_db(tmp_path)
        _add_teacher(conn, name="T1", priority=0)
        _add_teacher(conn, name="T2", priority=1)
        sid = _add_sample(conn)

        with patch("layer_2_chamber.backend.services.teacher_service._call_teacher") as mock_call, \
             patch("layer_2_chamber.backend.services.teacher_service.get_api_key", return_value="key"):
            # 兩裁判都給 6.5，差距 0 → needs_review（平均 < 8）
            mock_call.return_value = {"score": 6.5, "reason": "borderline"}
            result = score_sample(conn, sid, "inst", "inp", "out")

        assert result["status"] == "needs_review"

    def test_needs_review_when_disagreement_gt_2(self, tmp_path):
        conn = _make_db(tmp_path)
        _add_teacher(conn, name="T1", priority=0)
        _add_teacher(conn, name="T2", priority=1)
        sid = _add_sample(conn)

        scores = [7.0, 4.0]  # 差距 3 > 2
        call_count = 0

        def side_effect(*args, **kwargs):
            nonlocal call_count
            s = scores[call_count % 2]
            call_count += 1
            return {"score": s, "reason": f"score={s}"}

        with patch("layer_2_chamber.backend.services.teacher_service._call_teacher", side_effect=side_effect), \
             patch("layer_2_chamber.backend.services.teacher_service.get_api_key", return_value="key"):
            result = score_sample(conn, sid, "inst", "inp", "out")

        assert result["status"] == "needs_review"
        assert "分歧" in result["reason"]

    def test_no_teachers_returns_pending(self, tmp_path):
        conn = _make_db(tmp_path)
        sid = _add_sample(conn)
        result = score_sample(conn, sid, "inst", "inp", "out")
        assert result["status"] == "pending"

    def test_usage_log_written_after_scoring(self, tmp_path):
        conn = _make_db(tmp_path)
        tid = _add_teacher(conn)
        sid = _add_sample(conn)

        with patch("layer_2_chamber.backend.services.teacher_service._call_teacher") as mock_call, \
             patch("layer_2_chamber.backend.services.teacher_service.get_api_key", return_value="key"):
            mock_call.return_value = {"score": 9.0, "reason": "ok"}
            score_sample(conn, sid, "inst", "inp", "out")

        assert get_today_usage(conn, tid) == 1
