# layer_0_router/router.py
"""Layer 0 Router：分類 → 壓縮 → 呼叫 Qwen → 格式化注入字串"""

import json
import logging
import urllib.request

from .classifier import classify_prompt
from .compressor import compress_context

logger = logging.getLogger(__name__)

LOCAL_MODEL = "qwen3:30b-a3b"  # 未來換成 shiba-block1:YYYYMMDD
OLLAMA_BASE = "http://localhost:11434"
QWEN_TIMEOUT = 30


def route(prompt: str, rag_context: str) -> str | None:
    """
    主路由邏輯。
    - local → 壓縮 context → 呼叫 Qwen → 回傳注入字串
    - claude 或任何失敗 → 回傳 None（由 session_start_hook 走正常 RAG 流程）
    """
    classification = classify_prompt(prompt)
    if classification["decision"] != "local":
        logger.info("路由決策：claude（%s）", classification["reason"])
        return None

    logger.info("路由決策：local（%s）", classification["reason"])

    compressed = compress_context(rag_context) if rag_context else ""

    qwen_response = _call_qwen(prompt=prompt, context=compressed)
    if not qwen_response:
        logger.warning("Qwen 回應失敗，fallback Claude")
        return None

    return f"🤖 本地 Qwen 建議回答：\n{qwen_response}\n\n（如不符需求，Claude 將補充）"


def _call_qwen(prompt: str, context: str) -> str | None:
    """
    呼叫本地 Qwen（Ollama /api/chat）。
    回傳回應字串；失敗時回傳 None。
    """
    messages = []
    if context:
        messages.append({"role": "system", "content": f"相關記憶：{context}"})
    messages.append({"role": "user", "content": prompt})

    try:
        body = json.dumps({
            "model": LOCAL_MODEL,
            "messages": messages,
            "stream": False,
            "options": {"temperature": 0.7, "think": False, "num_predict": 512},
        }).encode()

        req = urllib.request.Request(
            f"{OLLAMA_BASE}/api/chat",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=QWEN_TIMEOUT) as resp:
            data = json.loads(resp.read())
            return data["message"]["content"].strip()

    except Exception as e:
        logger.warning("Qwen 呼叫失敗：%s", e)
        return None
