"""background.py 單元測試（B5：compress_cold_data；C5：scheduler 併發保護）"""

import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from layer_2_chamber.backend.core.background import compress_cold_data, setup_scheduler

LAYER1_SCHEMA = Path(__file__).parent.parent.parent / "layer_1_memory" / "db" / "schema.sql"
LAYER2_SCHEMA = Path(__file__).parent.parent.parent / "layer_2_chamber" / "backend" / "db" / "schema_layer2.sql"


def _make_db(tmp_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(tmp_path / "test.db"))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(LAYER1_SCHEMA.read_text())
    conn.executescript(LAYER2_SCHEMA.read_text())
    conn.commit()
    return conn


def _insert_session_branch(conn, uuid="sess-1") -> tuple[int, int]:
    """插入 project + session + branch，回傳 (session_id, branch_id)"""
    conn.execute(
        "INSERT OR IGNORE INTO projects (id, name, path, hash) VALUES (1, 'test', '/tmp/test', 'testhash')"
    )
    cur = conn.execute(
        "INSERT INTO sessions (uuid, project_id) VALUES (?, 1)", (uuid,)
    )
    session_id = cur.lastrowid
    cur2 = conn.execute(
        """INSERT INTO branches (session_id, is_active, decay_score,
           last_accessed, branch_idx)
           VALUES (?, 1, 1.0, datetime('now', '-100 days'), 0)""",
        (session_id,),
    )
    conn.commit()
    return session_id, cur2.lastrowid


def _insert_sample(conn, session_uuid, status, created_days_ago=0):
    created_at = (datetime.now(timezone.utc) - timedelta(days=created_days_ago)).isoformat()
    conn.execute(
        """INSERT INTO training_samples
           (source, session_id, event_type, instruction, input, output, status, created_at)
           VALUES ('layer1_bridge_v2', ?, 'git_ops', 'i', '', 'o', ?, ?)""",
        (session_uuid, status, created_at),
    )
    conn.commit()


class TestCompressColdData:
    def test_compresses_session_with_all_approved(self, tmp_path):
        """所有樣本 approved → 可壓縮"""
        conn = _make_db(tmp_path)
        session_id, branch_id = _insert_session_branch(conn, "sess-1")
        _insert_sample(conn, "sess-1", "approved", created_days_ago=40)

        compress_cold_data(lambda: _make_db(tmp_path))
        row = conn.execute("SELECT decay_score FROM branches WHERE id=?", (branch_id,)).fetchone()
        assert row["decay_score"] == 0

    def test_protects_session_with_fresh_pending(self, tmp_path):
        """pending 樣本 created < 30 天 → 不壓縮（等待評分中）"""
        conn = _make_db(tmp_path)
        session_id, branch_id = _insert_session_branch(conn, "sess-2")
        _insert_sample(conn, "sess-2", "pending", created_days_ago=5)

        compress_cold_data(lambda: _make_db(tmp_path))
        row = conn.execute("SELECT decay_score FROM branches WHERE id=?", (branch_id,)).fetchone()
        assert row["decay_score"] == 1.0  # 未壓縮

    def test_compresses_session_with_stuck_pending(self, tmp_path):
        """B5：pending 樣本 created > 30 天（評分永久失敗）→ 允許壓縮"""
        conn = _make_db(tmp_path)
        session_id, branch_id = _insert_session_branch(conn, "sess-3")
        _insert_sample(conn, "sess-3", "pending", created_days_ago=35)

        compress_cold_data(lambda: _make_db(tmp_path))
        row = conn.execute("SELECT decay_score FROM branches WHERE id=?", (branch_id,)).fetchone()
        assert row["decay_score"] == 0


class TestSchedulerConcurrencyGuards:
    """C5：所有 add_job 必須具備 max_instances=1 + coalesce + misfire_grace_time"""

    def test_all_jobs_have_concurrency_guards(self):
        # 用空 conn_factory 避免實際開 DB；setup_scheduler 不啟動排程
        scheduler = setup_scheduler(app=None, conn_factory=lambda: None)
        assert scheduler is not None, "AsyncIOScheduler 應已建立（apscheduler 已安裝）"

        jobs = scheduler.get_jobs()
        assert len(jobs) == 7, f"應掛 7 個 job，實際 {len(jobs)}"

        for job in jobs:
            assert job.max_instances == 1, f"job {job.id} 缺 max_instances=1"
            assert job.coalesce is True, f"job {job.id} 缺 coalesce=True"
            assert job.misfire_grace_time == 300, f"job {job.id} 缺 misfire_grace_time=300"
