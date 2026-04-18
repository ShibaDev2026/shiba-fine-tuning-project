# layer_0_router/classifier.py
"""Gemma E2B：分類任務為 local（Qwen 處理）或 claude（Claude 處理）"""

import json
import logging
import urllib.request
from typing import Literal

logger = logging.getLogger(__name__)

CLASSIFIER_MODEL = "gemma3:2b"
OLLAMA_BASE = "http://localhost:11434"
ROUTER_TIMEOUT = 30  # 預留 model swap 時間（OLLAMA_MAX_LOADED_MODELS=1）

_CLASSIFY_PROMPT = """\
你是一個任務路由器。判斷以下任務應該交給本地小模型（local）還是 Claude（claude）處理。

本地模型適合：git 操作、終端指令執行、程式碼生成（明確需求）、debug（有具體錯誤訊息）、簡短 QA。
Claude 適合：複雜架構設計、多步驟推理、不確定性高的任務、需要大量背景知識的問題。

任務：{prompt}

只回覆 JSON，不要有其他文字：{{"decision": "local" 或 "claude", "reason": "一句話理由"}}"""


def classify_prompt(prompt: str) -> dict:
    """
    回傳 {'decision': 'local'|'claude', 'reason': str}。
    Ollama 離線或解析失敗時 fallback claude。
    """
    try:
        body = json.dumps({
            "model": CLASSIFIER_MODEL,
            "prompt": _CLASSIFY_PROMPT.format(prompt=prompt[:300]),
            "stream": False,
            "options": {"temperature": 0.0, "think": False},
        }).encode()

        req = urllib.request.Request(
            f"{OLLAMA_BASE}/api/generate",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=ROUTER_TIMEOUT) as resp:
            data = json.loads(resp.read())
            raw_text = data.get("response", "").strip()

        # 移除 markdown code block
        if raw_text.startswith("```"):
            raw_text = raw_text[raw_text.index("\n") + 1:] if "\n" in raw_text else raw_text[3:]
        raw_text = raw_text.rstrip("`").strip()

        result = json.loads(raw_text)
        decision = result.get("decision", "claude")
        if decision not in ("local", "claude"):
            decision = "claude"
        return {"decision": decision, "reason": result.get("reason", "")}

    except Exception as e:
        logger.warning("分類器失敗，fallback claude：%s", e)
        return {"decision": "claude", "reason": "fallback"}
