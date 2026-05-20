"""Anthropic Messages API 共用 client。

外部使用：
    from clients.anthropic import AnthropicClient

設計與 clients/gemini 對齊：vendor 分包、回傳 tuple、錯誤分三類（PERMANENT/TRANSIENT/QUOTA）。
"""

from .client import AnthropicClient

__all__ = ["AnthropicClient"]
