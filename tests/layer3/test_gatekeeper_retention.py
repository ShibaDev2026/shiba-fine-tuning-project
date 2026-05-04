"""gatekeeper retention 評估測試（C：防遺忘第 4 條件）"""

import sqlite3
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_ROOT))

_LAYER1_SCHEMA = _ROOT / "layer_1_memory" / "db" / "schema.sql"
_LAYER2_SCHEMA = _ROOT / "layer_2_chamber" / "backend" / "db" / "schema_layer2.sql"

from layer_3_pipeline.gatekeeper import (
    RETENTION_MIN_N,
    RETENTION_THRESHOLD,
    _check_conditions,
    _evaluate_retention,
)


def _make_db(tmp_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(tmp_path / "test.db"))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(_LAYER1_SCHEMA.read_text())
    conn.executescript(_LAYER2_SCHEMA.read_text())
    conn.commit()
    return conn


def _insert_golden(conn: sqlite3.Connection, n: int) -> None:
    """插入 n 筆 golden_samples（training_samples 做為 source）"""
    conn.execute(
        "INSERT OR IGNORE INTO projects (id, name, path, hash) VALUES (1,'t','/t','h')"
    )
    cur = conn.execute("INSERT INTO sessions (uuid, project_id) VALUES ('g-sess', 1)")
    conn.commit()
    for i in range(n):
        cur2 = conn.execute(
            """INSERT INTO training_samples
               (source, session_id, event_type, instruction, input, output, status, score)
               VALUES ('layer1_bridge_v2','g-sess','git_ops',?,'',' ','approved',9.5)""",
            (f"instruction {i}",),
        )
        conn.execute(
            """INSERT INTO golden_samples
               (source_sample_id, instruction, input, expected_output, event_type, score)
               VALUES (?, ?, '', 'expected', 'git_ops', 9.5)""",
            (cur2.lastrowid, f"instruction {i}"),
        )
    conn.commit()


class TestRetentionBelowThreshold:
    def test_retention_below_threshold_blocks_deploy(self, tmp_path):
        """golden set 上 new 輸 50% → retention_score < 0.85 → passed=False"""
        conn = _make_db(tmp_path)
        _insert_golden(conn, 10)

        # new 輸（False）5 次，new 贏（True）5 次 → score = 0.5
        judge_results = [False, True] * 5

        with patch("layer_3_pipeline.gatekeeper._call_ollama", return_value=("resp", 100.0)), \
             patch("layer_3_pipeline.gatekeeper._judge_pair", side_effect=judge_results):
            score, n = _evaluate_retention("shadow:tag", "old:tag", "old:tag", conn)

        assert score is not None
        assert score == pytest.approx(0.5)
        # _check_conditions 應封鎖
        _, _, failures = _check_conditions(
            ci_lower=0.55, latency_ratio=None,
            acceptance_baseline=None, retention_score=score,
        )
        assert any("retention" in f for f in failures)


class TestRetentionAboveThreshold:
    def test_retention_above_threshold_passes(self, tmp_path):
        """new 90% 不退化 → retention_score = 0.9 ≥ 0.85 → 不封鎖"""
        conn = _make_db(tmp_path)
        _insert_golden(conn, 10)

        # 9 次 True（new 勝），1 次 False（new 輸）→ score = 0.9
        judge_results = [True] * 9 + [False]

        with patch("layer_3_pipeline.gatekeeper._call_ollama", return_value=("resp", 100.0)), \
             patch("layer_3_pipeline.gatekeeper._judge_pair", side_effect=judge_results):
            score, n = _evaluate_retention("shadow:tag", "old:tag", "old:tag", conn)

        assert score == pytest.approx(0.9)
        passed, _, failures = _check_conditions(
            ci_lower=0.55, latency_ratio=None,
            acceptance_baseline=None, retention_score=score,
        )
        assert passed is True
        assert not any("retention" in f for f in failures)


class TestRetentionSkipsWhenSmall:
    def test_retention_skips_when_set_too_small(self, tmp_path):
        """golden_samples < RETENTION_MIN_N → retention_score=None → 不阻塞"""
        conn = _make_db(tmp_path)
        _insert_golden(conn, RETENTION_MIN_N - 1)

        with patch("layer_3_pipeline.gatekeeper._call_ollama", return_value=("resp", 100.0)), \
             patch("layer_3_pipeline.gatekeeper._judge_pair", return_value=False):
            score, n = _evaluate_retention("shadow:tag", "old:tag", "old:tag", conn)

        assert score is None
        # None → _check_conditions 略過第 4 條件
        passed, _, failures = _check_conditions(
            ci_lower=0.55, latency_ratio=None,
            acceptance_baseline=None, retention_score=None,
        )
        assert passed is True
