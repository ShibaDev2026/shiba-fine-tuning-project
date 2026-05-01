"""multi_judge.py 單元測試（C1 early exit 驗證）"""

import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from layer_2_chamber.backend.services.multi_judge import _collect_votes, _APPROVED_THRESHOLD


def _make_teacher(tid: int) -> MagicMock:
    t = MagicMock()
    t.__getitem__ = lambda self, k: tid if k == "id" else f"Teacher{tid}"
    return t


def _mock_call(scores: list[float]):
    """回傳依序給出指定 score 的 _call_teacher mock。"""
    it = iter(scores)
    def side_effect(teacher, *args, **kwargs):
        try:
            s = next(it)
        except StopIteration:
            return None
        return {"score": s, "reason": "test"}
    return side_effect


class TestCollectVotesEarlyExit:
    def test_two_approved_stops_early(self):
        """2 票全 approved → 不呼叫第 3 個 teacher"""
        teachers = [_make_teacher(i) for i in range(3)]
        call_count = 0
        high = _APPROVED_THRESHOLD + 1.0

        def mock_call(teacher, *a, **kw):
            nonlocal call_count
            call_count += 1
            return {"score": high, "reason": "ok"}

        with patch("layer_2_chamber.backend.services.multi_judge._call_teacher", side_effect=mock_call):
            conn = MagicMock()
            votes = _collect_votes(conn, 1, "inst", "inp", "out", teachers)

        assert call_count == 2, "2 票一致應提前停止，不呼叫第 3 位"
        assert len(votes) == 2
        assert all(v["approved"] for v in votes)

    def test_two_rejected_stops_early(self):
        """2 票全 rejected → 不呼叫第 3 個 teacher"""
        teachers = [_make_teacher(i) for i in range(3)]
        call_count = 0
        low = _APPROVED_THRESHOLD - 1.0

        def mock_call(teacher, *a, **kw):
            nonlocal call_count
            call_count += 1
            return {"score": low, "reason": "bad"}

        with patch("layer_2_chamber.backend.services.multi_judge._call_teacher", side_effect=mock_call):
            conn = MagicMock()
            votes = _collect_votes(conn, 1, "inst", "inp", "out", teachers)

        assert call_count == 2
        assert len(votes) == 2
        assert not any(v["approved"] for v in votes)

    def test_disagreement_calls_third(self):
        """1 approved + 1 rejected → 需要第 3 票"""
        teachers = [_make_teacher(i) for i in range(3)]
        scores = [_APPROVED_THRESHOLD + 1.0, _APPROVED_THRESHOLD - 1.0, _APPROVED_THRESHOLD + 1.0]
        call_count = 0

        def mock_call(teacher, *a, **kw):
            nonlocal call_count
            s = scores[call_count]
            call_count += 1
            return {"score": s, "reason": "ok"}

        with patch("layer_2_chamber.backend.services.multi_judge._call_teacher", side_effect=mock_call):
            conn = MagicMock()
            votes = _collect_votes(conn, 1, "inst", "inp", "out", teachers)

        assert call_count == 3, "1v1 分歧時應呼叫第 3 位"
        assert len(votes) == 3
