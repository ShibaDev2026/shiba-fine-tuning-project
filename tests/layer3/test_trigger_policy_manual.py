"""trigger_policy 首次訓練人工把關測試（D）"""

import sqlite3
import sys
from pathlib import Path

_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_ROOT))

_LAYER1_SCHEMA = _ROOT / "layer_1_memory" / "db" / "schema.sql"
_LAYER2_SCHEMA = _ROOT / "layer_2_chamber" / "backend" / "db" / "schema_layer2.sql"

from layer_3_pipeline.trigger_policy import should_trigger


def _make_db(tmp_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(tmp_path / "test.db"))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(_LAYER1_SCHEMA.read_text())
    conn.executescript(_LAYER2_SCHEMA.read_text())
    conn.commit()
    return conn


def _seed_approved(conn: sqlite3.Connection, adapter_block: int, n: int = 35) -> None:
    """插入足夠多的 approved 樣本讓信號 A（首次 = 立即觸發）通過 MIN_SAMPLES 檢查"""
    conn.execute(
        "INSERT OR IGNORE INTO projects (id, name, path, hash) VALUES (1,'t','/t','h')"
    )
    conn.execute("INSERT INTO sessions (uuid, project_id) VALUES ('ms-test', 1)")
    for i in range(n):
        conn.execute(
            """INSERT INTO training_samples
               (source, session_id, event_type, instruction, input, output,
                status, adapter_block)
               VALUES ('layer1_bridge_v2','ms-test','git_ops',?,'',' ','approved',?)""",
            (f"inst {i}", adapter_block),
        )
    conn.commit()


class TestFirstRunRequiresManual:
    def test_first_run_returns_requires_manual(self, tmp_path):
        """finetune_runs 該 block 無 done run → should_train=True + requires_manual=True"""
        conn = _make_db(tmp_path)
        _seed_approved(conn, adapter_block=1)

        decision = should_trigger(conn, adapter_block=1)

        assert decision.should_train is True, f"期望 should_train=True，reason={decision.reason}"
        assert decision.requires_manual is True, "首次訓練應標記 requires_manual=True"


class TestSubsequentRunNoManual:
    def test_subsequent_run_no_manual(self, tmp_path):
        """已有 done run → requires_manual=False"""
        conn = _make_db(tmp_path)
        _seed_approved(conn, adapter_block=1)

        # 寫一筆 done run（距今 1 天，落在 Ebbinghaus 1d 窗口）
        conn.execute(
            """INSERT INTO finetune_runs
               (adapter_block, status, finished_at, started_at)
               VALUES (1, 'done', datetime('now', '-1 days'), datetime('now', '-1 days'))"""
        )
        conn.commit()

        decision = should_trigger(conn, adapter_block=1)

        assert decision.requires_manual is False, "已有 done run 不應要求人工把關"
