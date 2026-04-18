import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from layer_0_router.compressor import compress_context


def _mock_ollama(response_text: str):
    import json
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps({"response": response_text, "done": True}).encode()
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    return mock_resp


def test_compress_returns_string():
    with patch("urllib.request.urlopen") as mock_open:
        mock_open.return_value = _mock_ollama("壓縮後的摘要內容")
        result = compress_context("一段很長的歷史 context 字串" * 20)
    assert isinstance(result, str)
    assert len(result) > 0


def test_compress_short_context_skip():
    """短 context（< 200 字）直接回傳，不呼叫 Ollama"""
    with patch("urllib.request.urlopen") as mock_open:
        result = compress_context("短字串")
    mock_open.assert_not_called()
    assert result == "短字串"


def test_compress_fallback_on_error():
    """Ollama 離線 → 回傳原始截斷版本"""
    long_ctx = "x" * 500
    with patch("urllib.request.urlopen", side_effect=Exception("離線")):
        result = compress_context(long_ctx)
    assert result == long_ctx[:300] + "..."
