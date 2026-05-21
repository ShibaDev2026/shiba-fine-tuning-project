# layer_0_router/compressor.py
"""Context 壓縮入口（PR-O-8 拆出）。

核心預設行為：簡單截斷（< 200 字直接回傳；過長 → 取前 300 字 + "..."）。
advanced_compressor feature on → 註冊 "compress_context" hook 走 Gemma 壓縮；
未註冊或失敗 → 退回截斷版（不阻塞主流程）。
"""

import logging

logger = logging.getLogger(__name__)

_MIN_LEN_TO_COMPRESS = 200
_TRUNCATE_LEN = 300


def _truncate(context: str) -> str:
    """核心 fallback：短 context 原樣回，長 context 截到 _TRUNCATE_LEN + "..."。"""
    if len(context) < _MIN_LEN_TO_COMPRESS:
        return context
    return context[:_TRUNCATE_LEN] + "..."


def compress_context(context: str) -> str:
    """壓縮 context；feature off → 截斷；feature on → 走 hook（Gemma）。"""
    if len(context) < _MIN_LEN_TO_COMPRESS:
        return context

    from core.feature_registry import get_hook
    hook = get_hook("compress_context")
    if hook is None:
        return _truncate(context)

    try:
        result = hook(context)
        return result or _truncate(context)
    except Exception as e:
        logger.warning("advanced 壓縮失敗，fallback 截斷：%s", e)
        return _truncate(context)
