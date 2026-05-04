"""multi_judge vendor 廠牌異質性測試（A：C1 早停升級）"""

import sqlite3
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_ROOT))

from layer_2_chamber.backend.services.multi_judge import _collect_votes, _vendor_of


def _make_teacher(tid: int, name: str, vendor: str, approved_score: float = 9.0) -> dict:
    """Helper：以 dict 模擬 sqlite3.Row 的 teacher 欄位存取"""
    class _FakeRow(dict):
        def __getitem__(self, key):
            return super().__getitem__(key)
        def keys(self):
            return super().keys()
    return _FakeRow(id=tid, name=name, vendor=vendor, _score=approved_score)


def _call_teacher_factory(teacher_scores: dict):
    """side_effect：依 teacher name 回傳預設分數"""
    def _call(teacher, instruction, input_text, output, conn, sample_id):
        score = teacher_scores.get(teacher["name"], 9.0)
        return {"score": score, "reason": "mock"}
    return _call


class TestSameVendorNoEarlyExit:
    def test_early_exit_blocked_when_same_vendor(self):
        """兩票都是 google 且結果一致 → 不早停，繼續抓第三票"""
        teachers = [
            _make_teacher(1, "Gemini Flash",      vendor="google"),
            _make_teacher(2, "Gemini Flash-Lite",  vendor="google"),
            _make_teacher(3, "Mistral 7B",         vendor="mistral"),
        ]
        # 三位都給 9.5 → 均為 approved
        scores = {"Gemini Flash": 9.5, "Gemini Flash-Lite": 9.5, "Mistral 7B": 9.5}

        with patch(
            "layer_2_chamber.backend.services.multi_judge._call_teacher",
            side_effect=_call_teacher_factory(scores),
        ):
            votes = _collect_votes(None, 1, "inst", "", "out", teachers)

        # 同 vendor → 不早停，三票全收
        assert len(votes) == 3


class TestTwoVendorsEarlyExit:
    def test_early_exit_allowed_when_two_vendors(self):
        """第一票 google + 第二票 xai 且結果一致 → 早停，只取兩票"""
        teachers = [
            _make_teacher(1, "Gemini Flash", vendor="google"),
            _make_teacher(2, "Grok Mini",    vendor="xai"),
            _make_teacher(3, "Mistral 7B",   vendor="mistral"),
        ]
        scores = {"Gemini Flash": 9.5, "Grok Mini": 9.5, "Mistral 7B": 9.5}

        with patch(
            "layer_2_chamber.backend.services.multi_judge._call_teacher",
            side_effect=_call_teacher_factory(scores),
        ):
            votes = _collect_votes(None, 1, "inst", "", "out", teachers)

        # 廠牌異質 + 兩票一致 → 早停，只有兩票
        assert len(votes) == 2
        assert {v["vendor"] for v in votes} == {"google", "xai"}


class TestAllSameVendorThreeVotes:
    def test_three_votes_same_vendor_still_counted(self):
        """全部 teacher 同一 vendor（e.g. 外部 API 只剩 local）→ 三票全收，不封鎖"""
        teachers = [
            _make_teacher(1, "Local 1", vendor="local"),
            _make_teacher(2, "Local 2", vendor="local"),
            _make_teacher(3, "Local 3", vendor="local"),
        ]
        scores = {"Local 1": 9.5, "Local 2": 9.5, "Local 3": 9.5}

        with patch(
            "layer_2_chamber.backend.services.multi_judge._call_teacher",
            side_effect=_call_teacher_factory(scores),
        ):
            votes = _collect_votes(None, 1, "inst", "", "out", teachers)

        # 全同 vendor 不封鎖 → 三票全收（避免外部 API 全當機時無法評分）
        assert len(votes) == 3
        assert all(v["vendor"] == "local" for v in votes)
