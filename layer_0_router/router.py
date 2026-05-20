# layer_0_router/router.py
"""Layer 0 Router：分類 → 壓縮 → 呼叫 Qwen → 格式化注入字串"""

import json
import logging
import time
import urllib.request

from shiba_config import CONFIG

from ._config import is_local_enabled, load_active_snapshot, split_inference
from .classifier import classify_prompt
from .compressor import compress_context
from .telemetry import record_decision

logger = logging.getLogger(__name__)

OLLAMA_BASE = CONFIG.services.ollama_base_url
QWEN_TIMEOUT = 30  # client timeout 固定 30s（不吃 yaml）


def route(prompt: str, rag_context: str, session_id: str | None = None) -> str | None:
    """
    主路由邏輯。
    - offline kill switch（router_config.ollama_status='offline'）→ 直接回 None
    - local → 壓縮 context → 呼叫 Qwen → 回傳注入字串
    - claude 或任何失敗 → 回傳 None（由 session_start_hook 走正常 RAG 流程）
    決策同步寫入 router_decisions（P0-1 採納率追蹤）。
    """
    t0 = time.monotonic()

    if not is_local_enabled():
        logger.info("路由決策：claude（offline kill switch）")
        _record(session_id, prompt, "claude", "offline_killswitch", None, t0, None, None)
        return None

    classification = classify_prompt(prompt)
    decision = classification["decision"]
    reason = classification.get("reason")

    if decision != "local":
        logger.info("路由決策：claude（%s）", reason)
        _record(session_id, prompt, "claude", reason, None, t0, None, None)
        return None

    logger.info("路由決策：local（%s）", reason)

    compressed = compress_context(rag_context) if rag_context else ""

    result = _call_qwen(prompt=prompt, context=compressed)
    if result is None:
        logger.warning("Qwen 回應失敗，fallback Claude")
        _record(session_id, prompt, "claude", "qwen_error", None, t0, None, None)
        return None

    qwen_response, tokens_prompt, tokens_response = result
    injection = f"🤖 本地 Qwen 建議回答：\n{qwen_response}\n\n（如不符需求，Claude 將補充）"
    _record(session_id, prompt, "local", reason, qwen_response, t0, tokens_prompt, tokens_response)
    return injection


def _record(
    session_id: str | None,
    prompt: str,
    classification: str,
    reason: str | None,
    output: str | None,
    t0: float,
    tokens_prompt: int | None,
    tokens_response: int | None,
) -> None:
    """靜默寫入 telemetry，不中斷主流程。"""
    try:
        record_decision(
            session_id=session_id,
            prompt=prompt,
            classification=classification,
            reason=reason,
            local_output=output,
            latency_ms=int((time.monotonic() - t0) * 1000),
            tokens_prompt=tokens_prompt,
            tokens_response=tokens_response,
        )
    except Exception as e:
        logger.warning("Telemetry 寫入失敗（不影響路由）：%s", e)


def _call_qwen(prompt: str, context: str) -> tuple[str, int | None, int | None] | None:
    """
    呼叫本地 Qwen（Ollama /api/chat）。
    回傳 (response_text, tokens_prompt, tokens_response)；失敗時回傳 None。
    """
    try:
        snap = load_active_snapshot("responder")
        options, keep_alive, think = split_inference(snap.get("inference"))
        system = (snap.get("prompt") or {}).get("system")

        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        if context:
            messages.append({"role": "system", "content": f"相關記憶：{context}"})
        messages.append({"role": "user", "content": prompt})

        body_dict = {
            "model": snap["ollama_tag"],
            "messages": messages,
            "stream": False,
            "options": options,
        }
        if keep_alive:
            body_dict["keep_alive"] = keep_alive
        if think is not None:
            body_dict["think"] = think

        body = json.dumps(body_dict).encode()

        req = urllib.request.Request(
            f"{OLLAMA_BASE}/api/chat",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=QWEN_TIMEOUT) as resp:
            data = json.loads(resp.read())
            text = data["message"]["content"].strip()
            tok_p = data.get("prompt_eval_count")
            tok_r = data.get("eval_count")
            return text, tok_p, tok_r

    except Exception as e:
        logger.warning("Qwen 呼叫失敗：%s", e)
        return None
