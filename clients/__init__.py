"""AI 廠商呼叫共用層。

依廠商分子模組：
- clients.gemini  → Google Gemini（Developer API / Vertex AI）
- 未來 clients.anthropic、clients.openai 比照同規範

共用：
- clients.base   → AIErrorCategory、AIClientError 基底（暫態 / 永久 / 配額分類）
"""

from clients.base import (
    AIClientError,
    AIErrorCategory,
    AIPermanentError,
    AIQuotaError,
    AITransientError,
)

__all__ = [
    "AIClientError",
    "AIErrorCategory",
    "AIPermanentError",
    "AIQuotaError",
    "AITransientError",
]
