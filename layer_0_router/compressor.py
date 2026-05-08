# layer_0_router/compressor.py
"""Gemma 壓縮器：把長 context 壓成簡短摘要供 Qwen 使用。

模型/參數從 snapshot 讀取（透過 _config.load_active_snapshot）。
"""

import json
import logging
import urllib.request

from shiba_config import CONFIG

from ._config import load_active_snapshot, split_inference

logger = logging.getLogger(__name__)

OLLAMA_BASE = CONFIG.services.ollama_base_url
COMPRESS_TIMEOUT = 30  # client timeout 固定 30s
_MIN_LEN_TO_COMPRESS = 200

_COMPRESS_PROMPT = """\
以下是對話記憶 context，請用繁體中文壓縮為 100 字以內的重點摘要，保留關鍵指令與結果，去除贅述：

{context}

摘要："""


def compress_context(context: str) -> str:
    """
    壓縮 context 字串。短於 200 字直接回傳；Ollama 離線或 DB 失敗時回傳截斷版。
    """
    if len(context) < _MIN_LEN_TO_COMPRESS:
        return context

    try:
        snap = load_active_snapshot("compressor")
        options, keep_alive = split_inference(snap.get("inference"))
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

        body = json.dumps(body_dict).encode()

        req = urllib.request.Request(
            f"{OLLAMA_BASE}/api/generate",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=COMPRESS_TIMEOUT) as resp:
            data = json.loads(resp.read())
            return data.get("response", "").strip() or context[:300]

    except Exception as e:
        logger.warning("壓縮失敗，回傳截斷版：%s", e)
        return context[:300] + "..."
