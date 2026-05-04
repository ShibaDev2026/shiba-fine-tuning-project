"""trigger_policy drift alert 測試（B-1：分布偏移告警）"""

import sqlite3
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_ROOT))

_LAYER1_SCHEMA = _ROOT / "layer_1_memory" / "db" / "schema.sql"
_LAYER2_SCHEMA = _ROOT / "layer_2_chamber" / "backend" / "db" / "schema_layer2.sql"

from layer_3_pipeline.trigger_policy import _signal_distribution_drift


def _make_db(tmp_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(tmp_path / "test.db"))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(_LAYER1_SCHEMA.read_text())
    conn.executescript(_LAYER2_SCHEMA.read_text())
    conn.commit()
    return conn


def _seed_embeddings(conn: sqlite3.Connection, n_old: int, n_new: int) -> None:
    """插入兩組 embedding：old（舊向量）、new（新向量）"""
    import json
    conn.execute(
        "INSERT OR IGNORE INTO projects (id, name, path, hash) VALUES (1,'t','/t','h')"
    )
    conn.execute("INSERT INTO sessions (uuid, project_id) VALUES ('drift-sess', 1)")
    # old embedding（舊向量）— 30 天前
    for i in range(n_old):
        conn.execute(
            "INSERT INTO exchange_embeddings (session_uuid, instruction, commands, embedding, created_at) "
            "VALUES (?, ?, ?, ?, datetime('now', '-30 days'))",
            ("drift-sess", f"old {i}", "echo old", json.dumps([1.0, 0.0, 0.0, 0.0])),
        )
    # new embedding（新向量）— 1 天前
    for i in range(n_new):
        conn.execute(
            "INSERT INTO exchange_embeddings (session_uuid, instruction, commands, embedding, created_at) "
            "VALUES (?, ?, ?, ?, datetime('now', '-1 days'))",
            ("drift-sess", f"new {i}", "echo new", json.dumps([0.0, 1.0, 0.0, 0.0])),
        )
    # 寫一筆 done run 作分界點（15 天前）
    conn.execute(
        "INSERT INTO finetune_runs (adapter_block, status, started_at) "
        "VALUES (1, 'done', datetime('now', '-15 days'))"
    )
    conn.commit()


class TestDriftAboveThresholdAlert:
    def test_drift_above_threshold_sends_alert(self, tmp_path):
        """cosine_dist > 0.35 → send_alert 應被呼叫一次"""
        conn = _make_db(tmp_path)
        # 舊 embedding [1,0,0,0] vs 新 embedding [0,1,0,0] → cosine_dist ≈ 1.0 > 0.35
        _seed_embeddings(conn, n_old=6, n_new=6)

        with patch("shiba_alert.send_alert") as mock_alert:
            sig, reason = _signal_distribution_drift(conn, adapter_block=1)

        assert sig is True, f"期望 signal=True（drift 觸發），reason={reason}"
        # send_alert 應被呼叫一次
        mock_alert.assert_called_once()
        args, kwargs = mock_alert.call_args
        assert args[0] == "distribution_drift"
        assert args[1]  # message not empty


class TestDriftBelowThresholdNoAlert:
    def test_drift_below_threshold_no_alert(self, tmp_path):
        """cosine_dist < 0.35 → send_alert 不應被呼叫"""
        conn = _make_db(tmp_path)
        # 舊 embedding [1,0,0,0] vs 新 embedding [0.99,0.01,0,0]（相似）→ cosine_dist ≈ 0.01 < 0.35
        import json
        conn.execute(
            "INSERT OR IGNORE INTO projects (id, name, path, hash) VALUES (1,'t','/t','h')"
        )
        conn.execute("INSERT INTO sessions (uuid, project_id) VALUES ('drift-sess', 1)")
        for i in range(6):
            conn.execute(
                "INSERT INTO exchange_embeddings (session_uuid, instruction, commands, embedding, created_at) "
                "VALUES (?, ?, ?, ?, datetime('now', '-30 days'))",
                ("drift-sess", f"old {i}", "echo", json.dumps([1.0, 0.0, 0.0, 0.0])),
            )
        for i in range(6):
            conn.execute(
                "INSERT INTO exchange_embeddings (session_uuid, instruction, commands, embedding, created_at) "
                "VALUES (?, ?, ?, ?, datetime('now', '-1 days'))",
                ("drift-sess", f"new {i}", "echo", json.dumps([0.99, 0.01, 0.0, 0.0])),  # 相似
            )
        conn.execute(
            "INSERT INTO finetune_runs (adapter_block, status, started_at) "
            "VALUES (1, 'done', datetime('now', '-15 days'))"
        )
        conn.commit()

        with patch("shiba_alert.send_alert") as mock_alert:
            sig, reason = _signal_distribution_drift(conn, adapter_block=1)

        assert sig is False, f"期望 signal=False（分布穩定），reason={reason}"
        # send_alert 不應被呼叫
        mock_alert.assert_not_called()
