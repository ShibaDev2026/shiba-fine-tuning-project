"""compressor 測試（PR-O-8 後）：

預設無 hook → 走截斷 fallback；advanced_compressor feature on 時才呼叫 Ollama。
此檔測試 fallback 行為；advanced 路徑測試在 modules/advanced_compressor/tests/。
"""

import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from core.feature_registry import register_hook, reset_hooks
from layer_0_router.compressor import compress_context


def test_compress_short_context_skip():
    """短 context（< 200 字）直接回傳，不走 hook、不截斷。"""
    reset_hooks()
    assert compress_context("短字串") == "短字串"


def test_compress_no_hook_truncates():
    """無 hook 註冊 → 長 context 取前 300 字 + ...。"""
    reset_hooks()
    long_ctx = "x" * 500
    assert compress_context(long_ctx) == long_ctx[:300] + "..."


def test_compress_with_hook_uses_advanced():
    """hook 註冊 → 呼叫 advanced 路徑回傳結果。"""
    reset_hooks()
    register_hook("compress_context", lambda ctx: "ADV:" + ctx[:10])
    try:
        result = compress_context("x" * 500)
        assert result.startswith("ADV:")
    finally:
        reset_hooks()


def test_compress_hook_failure_falls_back():
    """hook 拋例外 → fallback 截斷版。"""
    reset_hooks()
    def boom(_):
        raise RuntimeError("ollama offline")
    register_hook("compress_context", boom)
    try:
        long_ctx = "x" * 500
        result = compress_context(long_ctx)
        assert result == long_ctx[:300] + "..."
    finally:
        reset_hooks()
