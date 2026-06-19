"""dataset_formatter.py 單元測試"""

import json
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from layer_2_chamber.backend.extraction.dataset_formatter import (
    export_dataset,
    get_export_stats,
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


def _insert_sample(
    conn: sqlite3.Connection,
    instruction: str = "test instruction",
    output: str = "test output",
    status: str = "approved",
    score: float = 9.0,
    adapter_block: int = 1,
    created_at: str | None = None,
) -> int:
    if created_at is None:
        created_at = datetime.now(timezone.utc).isoformat()
    cur = conn.execute(
        """INSERT INTO training_samples
           (source, session_id, event_type, instruction, input, output,
            score, status, adapter_block, created_at)
           VALUES ('layer1_bridge', 'sess-x', 'git_ops', ?, '', ?, ?, ?, ?, ?)""",
        (instruction, output, score, status, adapter_block, created_at),
    )
    conn.commit()
    return cur.lastrowid


class TestExportDataset:
    def test_exports_approved_samples(self, tmp_path):
        conn = _make_db(tmp_path)
        _insert_sample(conn, instruction="inst1", output="out1")
        _insert_sample(conn, instruction="inst2", output="out2")

        out = tmp_path / "dataset.jsonl"
        stats = export_dataset(conn, out)

        assert stats["total"] == 2
        lines = out.read_text().splitlines()
        assert len(lines) == 2
        record = json.loads(lines[0])
        assert "instruction" in record
        assert "input" in record
        assert "output" in record
        assert "adapter_block" in record

    def test_pending_samples_excluded(self, tmp_path):
        conn = _make_db(tmp_path)
        _insert_sample(conn, status="approved")
        _insert_sample(conn, status="pending")
        _insert_sample(conn, status="rejected")

        out = tmp_path / "dataset.jsonl"
        stats = export_dataset(conn, out)
        assert stats["total"] == 1

    def test_adapter_block_filter(self, tmp_path):
        conn = _make_db(tmp_path)
        _insert_sample(conn, adapter_block=1)
        _insert_sample(conn, adapter_block=2)

        out = tmp_path / "dataset.jsonl"
        stats = export_dataset(conn, out, adapter_block=1)
        assert stats["total"] == 1
        record = json.loads(out.read_text().splitlines()[0])
        assert record["adapter_block"] == 1

    def test_since_id_separates_new_from_stable(self, tmp_path):
        conn = _make_db(tmp_path)
        # 穩定老樣本（created_at 超過 30 天前）
        old_date = (datetime.now(timezone.utc) - timedelta(days=40)).isoformat()
        old_id = _insert_sample(conn, instruction="old", score=9.0, created_at=old_date)
        # 新樣本
        new_id = _insert_sample(conn, instruction="new")

        out = tmp_path / "dataset.jsonl"
        stats = export_dataset(conn, out, since_id=new_id)

        assert stats["new"] == 1
        # replay_target = round(1 * 2/7) = 0（太少）
        assert stats["replay"] == 0

    def test_stable_sample_score_threshold(self, tmp_path):
        conn = _make_db(tmp_path)
        # Ebbinghaus 桶 7±1 天：刻意挑桶內日期
        old_date = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
        # 低分老樣本：不進 replay 集
        _insert_sample(conn, instruction="low", score=8.0, created_at=old_date)
        # 高分老樣本：進 replay 集
        _insert_sample(conn, instruction="high", score=9.0, created_at=old_date)
        # 新樣本（基底）：拉高 replay_target 至 ≥1
        new_ids = [_insert_sample(conn, instruction=f"new{i}") for i in range(7)]
        since_id = new_ids[0]  # 7 新樣本 → replay_target = round(7*2/7) = 2

        out = tmp_path / "dataset.jsonl"
        stats = export_dataset(conn, out, since_id=since_id)
        # 高分老樣本進 replay 集，低分不進
        assert stats["replay"] == 1

    def test_output_file_created(self, tmp_path):
        conn = _make_db(tmp_path)
        _insert_sample(conn, instruction="ensure-non-empty")
        out = tmp_path / "sub" / "dataset.jsonl"
        export_dataset(conn, out)
        assert out.exists()

    def test_empty_samples_raises(self, tmp_path):
        """B2：無 approved 樣本時 raise ValueError，避免下游拿到空檔。"""
        conn = _make_db(tmp_path)
        out = tmp_path / "dataset.jsonl"
        with pytest.raises(ValueError, match="no samples"):
            export_dataset(conn, out)
        assert not out.exists()

    def test_ensure_no_ascii_escape(self, tmp_path):
        """中文內容應直接輸出，不 escape 為 \\uXXXX"""
        conn = _make_db(tmp_path)
        _insert_sample(conn, instruction="請幫我 commit", output="完成 git commit")

        out = tmp_path / "dataset.jsonl"
        export_dataset(conn, out)
        content = out.read_text(encoding="utf-8")
        assert "請幫我" in content
        assert "\\u" not in content

    def test_question_bank_seed_excluded_without_block_filter(self, tmp_path):
        """Tier B 題庫橋接列（question_id 設、output=''）即使 adapter_block=None 也不得進 dataset。

        對應 POST /export 省略 adapter_block 的路徑：無 block 過濾時，靠 question_id IS NULL
        排除親評種子列，避免空 output 餵進 MLX（與 B2 空集守衛同一防護理念）。
        """
        conn = _make_db(tmp_path)
        _insert_sample(conn, instruction="real", output="real-out", adapter_block=1)
        # 模擬 bridge_questions 產生的 Tier B 種子列：question_id 設、output=''、adapter_block 留 NULL
        conn.execute("INSERT INTO question_sets (id, name, event_type) VALUES (1, 'qs', 'git_ops')")
        conn.execute("INSERT INTO questions (id, set_id, prompt) VALUES (1, 1, 'q?')")
        conn.execute(
            """INSERT INTO training_samples
               (source, question_id, event_type, instruction, input, output, score, status)
               VALUES ('layer1_bridge_v2', 1, 'git_ops', 'seed', '', '', 9.5, 'approved')""",
        )
        conn.commit()

        out = tmp_path / "dataset.jsonl"
        stats = export_dataset(conn, out)  # adapter_block=None → 無 block 過濾（POST /export 漏洞路徑）
        assert stats["total"] == 1  # 只有 real 列；Tier B 空 output 列被 question_id IS NULL 排除
        assert all(json.loads(line)["output"] != "" for line in out.read_text().splitlines())


class TestGetExportStats:
    def test_stats_by_status(self, tmp_path):
        conn = _make_db(tmp_path)
        _insert_sample(conn, status="approved")
        _insert_sample(conn, status="approved")
        _insert_sample(conn, status="pending")

        stats = get_export_stats(conn)
        assert stats["by_status"]["approved"] == 2
        assert stats["by_status"]["pending"] == 1
        assert stats["total"] == 3

    def test_stats_by_block(self, tmp_path):
        conn = _make_db(tmp_path)
        _insert_sample(conn, adapter_block=1)
        _insert_sample(conn, adapter_block=1)
        _insert_sample(conn, adapter_block=2)

        stats = get_export_stats(conn)
        assert stats["by_block"][1] == 2
        assert stats["by_block"][2] == 1


# B2：_calc_stable_target 已移除（死碼，export_dataset 實際只用 _calc_replay_target）。
