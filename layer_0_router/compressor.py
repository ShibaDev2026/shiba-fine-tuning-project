# layer_0_router/compressor.py
"""Gemma E4B：壓縮長 context 為簡短摘要，供 Qwen 使用"""

import json
import logging
import urllib.request

logger = logging.getLogger(__name__)

COMPRESSOR_MODEL = "gemma3:4b"
OLLAMA_BASE = "http://localhost:11434"
COMPRESS_TIMEOUT = 30  # 預留 model swap 時間
_MIN_LEN_TO_COMPRESS = 200

_COMPRESS_PROMPT = """\
以下是對話記憶 context，請用繁體中文壓縮為 100 字以內的重點摘要，保留關鍵指令與結果，去除贅述：

{context}

摘要："""


def compress_context(context: str) -> str:
    """
    壓縮 context 字串。短於 200 字直接回傳；Ollama 離線時回傳截斷版。
    """
    if len(context) < _MIN_LEN_TO_COMPRESS:
        return context

    try:
        body = json.dumps({
            "model": COMPRESSOR_MODEL,
            "prompt": _COMPRESS_PROMPT.format(context=context[:1000]),
            "stream": False,
            "options": {"temperature": 0.1, "think": False, "num_predict": 150},
        }).encode()

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
