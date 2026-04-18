import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from layer_0_router.router import route


def test_route_claude_skips_qwen():
    """分類為 claude → 直接回傳 None（不呼叫 Qwen）"""
    with patch("layer_0_router.router.classify_prompt") as mock_cls, \
         patch("layer_0_router.router._call_qwen") as mock_qwen:
        mock_cls.return_value = {"decision": "claude", "reason": "複雜"}
        result = route(prompt="複雜問題", rag_context="")
    assert result is None
    mock_qwen.assert_not_called()


def test_route_local_returns_qwen_response():
    """分類為 local → 呼叫 Qwen 並回傳格式化結果"""
    with patch("layer_0_router.router.classify_prompt") as mock_cls, \
         patch("layer_0_router.router.compress_context") as mock_compress, \
         patch("layer_0_router.router._call_qwen") as mock_qwen:
        mock_cls.return_value = {"decision": "local", "reason": "git 操作"}
        mock_compress.return_value = "壓縮後的 context"
        mock_qwen.return_value = "git commit -m 'feat: xxx'"

        result = route(prompt="幫我 git commit", rag_context="過去做過 git commit")

    assert result is not None
    assert "git commit" in result
    assert "🤖" in result


def test_route_local_qwen_timeout_returns_none():
    """Qwen 呼叫失敗 → 回傳 None（fallback Claude）"""
    with patch("layer_0_router.router.classify_prompt") as mock_cls, \
         patch("layer_0_router.router.compress_context") as mock_compress, \
         patch("layer_0_router.router._call_qwen", return_value=None):
        mock_cls.return_value = {"decision": "local", "reason": "簡單"}
        mock_compress.return_value = ""
        result = route(prompt="任何", rag_context="")
    assert result is None
