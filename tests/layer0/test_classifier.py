import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from layer_0_router.classifier import classify_prompt


def _mock_ollama(response_text: str):
    import json
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps({
        "response": response_text,
        "done": True,
    }).encode()
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    return mock_resp


def test_classify_local():
    with patch("urllib.request.urlopen") as mock_open:
        mock_open.return_value = _mock_ollama('{"decision": "local", "reason": "git 操作"}')
        result = classify_prompt("幫我 git commit")
    assert result["decision"] == "local"
    assert "reason" in result


def test_classify_claude():
    with patch("urllib.request.urlopen") as mock_open:
        mock_open.return_value = _mock_ollama('{"decision": "claude", "reason": "複雜架構"}')
        result = classify_prompt("設計一個分散式系統架構")
    assert result["decision"] == "claude"


def test_classify_fallback_on_error():
    with patch("urllib.request.urlopen", side_effect=Exception("連線失敗")):
        result = classify_prompt("任何問題")
    assert result["decision"] == "claude"
    assert result["reason"] == "fallback"
