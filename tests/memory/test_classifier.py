# tests/memory/test_classifier.py
"""classifier.py 單元測試"""

import sys
from pathlib import Path
from dataclasses import dataclass, field

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "layer_1_memory"))

from lib.classifier import classify_session, classify_text
from lib.parser import ParsedSession, ParsedBranch, ParsedMessage


def _make_session(*user_texts: str) -> ParsedSession:
    """建立測試用 ParsedSession（只含 user 訊息）"""
    msgs = [
        ParsedMessage(
            uuid=f"u{i}",
            parent_uuid=None,
            role="user",
            content=text,
            has_tool_use=False,
            tool_names=[],
            raw_entry={},
        )
        for i, text in enumerate(user_texts)
    ]
    branch = ParsedBranch(
        branch_idx=0,
        is_active=True,
        leaf_uuid=None,
        messages=msgs,
        exchange_count=len(msgs),
        files_modified=[],
        commits=0,
    )
    return ParsedSession(
        session_uuid="test-uuid",
        project_hash="abc123",
        project_path="/project",
        branches=[branch],
        exchange_count=len(msgs),
        files_modified=0,
        commits=0,
        tool_counts={},
        all_messages=msgs,
    )


def test_classify_debugging():
    s = _make_session("這個 function 有 error，幫我 fix")
    assert "debugging" in classify_session(s)


def test_classify_git_ops():
    s = _make_session("幫我寫 git commit message")
    assert "git_ops" in classify_session(s)


def test_classify_terminal_ops():
    s = _make_session("docker compose up 失敗了")
    assert "terminal_ops" in classify_session(s)


def test_classify_architecture():
    s = _make_session("幫我設計這個系統的 schema 架構")
    assert "architecture" in classify_session(s)


def test_classify_knowledge_qa():
    # 避免觸發 fine_tuning_ops 關鍵字，用純概念問句
    s = _make_session("Python 的 GIL 是什麼？如何解釋執行緒鎖定？")
    assert "knowledge_qa" in classify_session(s)


def test_classify_returns_list():
    """回傳值必須是 list"""
    s = _make_session("任意問題")
    assert isinstance(classify_session(s), list)


def test_classify_text_returns_list():
    """classify_text 純文字版也應回傳 list"""
    result = classify_text("git commit 之後發現有 error")
    assert isinstance(result, list)
    assert len(result) >= 1
