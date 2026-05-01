import sqlite3
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from layer_3_pipeline.db import count_approved, create_run, update_run


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript("""
        CREATE TABLE training_samples (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            adapter_block INTEGER,
            status TEXT DEFAULT 'raw',
            instruction TEXT DEFAULT '',
            output TEXT DEFAULT ''
        );
        CREATE TABLE finetune_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            adapter_block INTEGER,
            status TEXT DEFAULT 'pending',
            sample_count INTEGER,
            dataset_path TEXT,
            adapter_path TEXT,
            gguf_path TEXT,
            ollama_model TEXT,
            error_msg TEXT,
            started_at TEXT,
            finished_at TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );
    """)
    return c


def test_count_approved_empty(conn):
    assert count_approved(conn, 1) == 0


def test_count_approved(conn):
    conn.execute("INSERT INTO training_samples (adapter_block, status) VALUES (1, 'approved')")
    conn.execute("INSERT INTO training_samples (adapter_block, status) VALUES (1, 'approved')")
    conn.execute("INSERT INTO training_samples (adapter_block, status) VALUES (2, 'approved')")
    conn.commit()
    assert count_approved(conn, 1) == 2
    assert count_approved(conn, 2) == 1


def test_create_and_update_run(conn):
    run_id = create_run(conn, 1, 35, "/tmp/data.jsonl")
    assert run_id == 1
    update_run(conn, run_id, status="done", gguf_path="/tmp/model.gguf")
    row = conn.execute("SELECT status, gguf_path FROM finetune_runs WHERE id=1").fetchone()
    assert row["status"] == "done"
    assert row["gguf_path"] == "/tmp/model.gguf"


def test_finished_at_iso_format(conn):
    """B1：finished_at 儲存為 ISO-8601 文字（TYPEOF='text'，格式含 T 分隔符）"""
    from datetime import datetime, timezone
    ts = datetime.now(timezone.utc).isoformat()
    run_id = create_run(conn, 1, 10, "/tmp/data.jsonl")
    update_run(conn, run_id, finished_at=ts, status="done")

    row = conn.execute(
        "SELECT typeof(finished_at) AS t, finished_at FROM finetune_runs WHERE id=?",
        (run_id,),
    ).fetchone()
    assert row["t"] == "text", "finished_at 應為 TEXT 類型"
    assert "T" in row["finished_at"], "finished_at 應為 ISO-8601（含 T 分隔符）"
    # started_at 由 SQLite datetime('now') 寫入，確認兩者都非 NULL
    started = conn.execute(
        "SELECT started_at FROM finetune_runs WHERE id=?", (run_id,)
    ).fetchone()["started_at"]
    assert started is not None


# ── runner 整合測試（Task 5 追加）─────────────────────────────────────────

from layer_3_pipeline.runner import run_finetune_if_ready


def test_run_skips_when_trigger_negative(conn):
    """should_trigger 回 False 時不執行 pipeline"""
    from layer_3_pipeline.trigger_policy import TriggerDecision
    with patch("layer_3_pipeline.runner.should_trigger",
               return_value=TriggerDecision(should_train=False, reason="no signal", approved_count=0)):
        result = run_finetune_if_ready(conn, adapter_block=1)
    assert result is None


def test_run_triggers_when_policy_positive(conn, tmp_path):
    """should_trigger 觸發時執行完整 pipeline"""
    for i in range(30):
        conn.execute(
            "INSERT INTO training_samples (adapter_block, status, instruction, output) VALUES (1,'approved',?,?)",
            (f"instr{i}", f"out{i}"),
        )
    conn.commit()

    from layer_3_pipeline.trigger_policy import TriggerDecision
    from layer_3_pipeline.gatekeeper import GateResult
    with patch("layer_3_pipeline.runner.should_trigger",
               return_value=TriggerDecision(should_train=True, reason="ebbinghaus", approved_count=30)), \
         patch("layer_3_pipeline.runner.export_dataset") as mock_export, \
         patch("layer_3_pipeline.runner.train_lora") as mock_train, \
         patch("layer_3_pipeline.runner.convert_to_gguf") as mock_convert, \
         patch("layer_3_pipeline.runner.run_gate",
               return_value=GateResult(passed=True, win_rate=0.8, ci_lower=0.7,
                                       latency_ratio=1.0, acceptance_baseline=0.5,
                                       reason="pass", n_evaluated=10)), \
         patch("layer_3_pipeline.runner.push_to_ollama") as mock_push:

        mock_export.return_value = {"total": 30, "path": str(tmp_path / "data.jsonl")}
        mock_train.return_value = tmp_path / "adapters" / "block1"
        mock_convert.return_value = tmp_path / "shiba-block1.gguf"
        mock_push.return_value = "shiba-block1:20260419"

        result = run_finetune_if_ready(conn, adapter_block=1, work_dir=tmp_path)

    assert result["ollama_model"] == "shiba-block1:20260419"
    assert result["status"] == "done"
