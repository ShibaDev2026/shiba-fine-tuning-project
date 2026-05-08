# layer_0_router/classifier.py
"""Gemma 分類器：判斷任務走 local（Qwen）或 claude。

模型/參數從 router_config + model_registry snapshot 讀取（透過 _config.load_active_snapshot），
不再 hardcode 模型字串。
"""

import json
import logging
import urllib.request

from shiba_config import CONFIG

from ._config import load_active_snapshot, split_inference

logger = logging.getLogger(__name__)

OLLAMA_BASE = CONFIG.services.ollama_base_url
ROUTER_TIMEOUT = 30  # client timeout 固定 30s（不吃 yaml；模型切換 swap 由前端倒數提示）

_CLASSIFY_PROMPT = """\
你是一個任務路由器。判斷以下任務應該交給本地小模型（local）還是 Claude（claude）處理。

本地模型適合：git 操作、終端指令執行、程式碼生成（明確需求）、debug（有具體錯誤訊息）、簡短 QA。
Claude 適合：複雜架構設計、多步驟推理、不確定性高的任務、需要大量背景知識的問題。

任務：{prompt}

只回覆 JSON，不要有其他文字：{{"decision": "local" 或 "claude", "reason": "一句話理由"}}"""


def classify_prompt(prompt: str) -> dict:
    """
    回傳 {'decision': 'local'|'claude', 'reason': str}。
    Ollama 離線、DB 失敗或解析失敗時 fallback claude。
    """
    try:
        snap = load_active_snapshot("classifier")
        options, keep_alive, think = split_inference(snap.get("inference"))
        system = (snap.get("prompt") or {}).get("system")

        body_dict = {
            "model": snap["ollama_tag"],
            "prompt": _CLASSIFY_PROMPT.format(prompt=prompt[:300]),
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
