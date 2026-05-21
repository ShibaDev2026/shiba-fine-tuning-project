"""modules/advanced_compressor/service.py — Gemma 壓縮（PR-O-8 拆出）。

呼叫 Ollama Gemma snapshot 將 context 壓成 100 字摘要；
失敗時 raise，由 layer_0_router.compressor 統一 fallback 至截斷版。
"""

from __future__ import annotations

import json
import logging
import urllib.request

from shiba_config import CONFIG

from layer_0_router._config import load_active_snapshot, split_inference

logger = logging.getLogger(__name__)

OLLAMA_BASE = CONFIG.services.ollama_base_url
COMPRESS_TIMEOUT = 30

_COMPRESS_PROMPT = """\
以下是對話記憶 context，請用繁體中文壓縮為 100 字以內的重點摘要，保留關鍵指令與結果，去除贅述：

{context}

摘要："""


def compress_context_advanced(context: str) -> str:
    """呼叫 Gemma 壓縮 context；snapshot/Ollama 任一失敗 → raise（由 caller fallback）。"""
    snap = load_active_snapshot("compressor")
    options, keep_alive, think = split_inference(snap.get("inference"))
    system = (snap.get("prompt") or {}).get("system")

    body_dict = {
        "model": snap["ollama_tag"],
        "prompt": _COMPRESS_PROMPT.format(context=context[:1000]),
        "stream": False,
        "options": options,
    }
    if system:
        body_dict["system"] = system
    if keep_alive:
        body_dict["keep_alive"] = keep_alive
    if think is not None:
        body_dict["think"] = think

    body = json.dumps(body_dict).encode()
    req = urllib.request.Request(
        f"{OLLAMA_BASE}/api/generate",
        data=body,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=COMPRESS_TIMEOUT) as resp:
        data = json.loads(resp.read())
        return (data.get("response", "") or "").strip()
