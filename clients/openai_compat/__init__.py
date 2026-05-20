"""OpenAI-compatible 端點共用 client（Ollama OpenAI mode / Mistral / OpenAI 等）。

外部使用：
    from clients.openai_compat import OpenAICompatClient

設計與 clients/gemini、clients/anthropic 對齊。
"""

from .client import OpenAICompatClient

__all__ = ["OpenAICompatClient"]
