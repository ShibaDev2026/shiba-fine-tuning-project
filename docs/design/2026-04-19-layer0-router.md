# Layer 0 Router Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立路由層，讓 UserPromptSubmit hook 在 Claude 回應前先分類任務複雜度，簡單任務直接呼叫本地 Qwen 並注入回應，複雜任務 fallback Claude。

**Architecture:** `session_start_hook.py` 在 RAG 注入後，呼叫 `layer_0_router/router.py`；Router 用 Gemma E2B 分類 prompt（local/claude），若 local 則壓縮 context（Gemma E4B）並呼叫 Qwen，將 Qwen 回應注入 `additionalContext`；Claude 看到注入後可直接採用或補充。

**Tech Stack:** Python 3.11、Ollama（gemma3:2b / gemma3:4b / qwen3:30b-a3b）、`urllib.request`（無額外依賴）

---

## 前置：Pull Gemma 模型

```bash
ollama pull gemma3:2b
ollama pull gemma3:4b
```

預期：兩個模型出現在 `ollama list`

---

## 檔案結構

```
layer_0_router/
├── __init__.py
├── classifier.py      ← Gemma E2B：分類 local / claude
├── compressor.py      ← Gemma E4B：壓縮 context 字串
└── router.py          ← 主入口：classify → compress → call Qwen → 格式化輸出

layer_1_memory/hooks/session_start_hook.py   ← 整合 router（Task 4）

tests/layer0/
├── test_classifier.py
├── test_compressor.py
└── test_router.py
```

---

## 常數（所有 task 共用）

```python
CLASSIFIER_MODEL = "gemma3:2b"
COMPRESSOR_MODEL = "gemma3:4b"
LOCAL_MODEL = "qwen3:30b-a3b"        # 未來換成 fine-tuned shiba-block1/2
OLLAMA_BASE = "http://localhost:11434"
ROUTER_TIMEOUT = 10   # 秒，分類器超時則 fallback claude
QWEN_TIMEOUT = 30     # 秒，Qwen 回應超時則 fallback claude
```

---

## Task 1：Classifier（Gemma E2B 分類）

**Files:**
- Create: `layer_0_router/classifier.py`
- Create: `tests/layer0/test_classifier.py`

**分類規則（prompt 給 Gemma 的 instruction）：**
- `local`：git 操作、終端指令、程式碼生成、debug、簡短 QA（單一明確任務）
- `claude`：需要複雜推理、多步驟架構設計、不確定性高的任務

- [ ] **Step 1: 寫測試（mock Ollama）**

```python
# tests/layer0/test_classifier.py
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from layer_0_router.classifier import classify_prompt


def _mock_ollama(response_text: str):
    """建立模擬 Ollama 回應的 context manager"""
    import json
    from io import BytesIO
    from unittest.mock import MagicMock

    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps({
        "response": response_text,
        "done": True,
    }).encode()
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    return mock_resp


def test_classify_local(monkeypatch):
    """Gemma 回傳 local → 回傳 local"""
    with patch("urllib.request.urlopen") as mock_open:
        mock_open.return_value = _mock_ollama('{"decision": "local", "reason": "git 操作"}')
        result = classify_prompt("幫我 git commit")
    assert result["decision"] == "local"
    assert "reason" in result


def test_classify_claude(monkeypatch):
    """Gemma 回傳 claude → 回傳 claude"""
    with patch("urllib.request.urlopen") as mock_open:
        mock_open.return_value = _mock_ollama('{"decision": "claude", "reason": "複雜架構"}')
        result = classify_prompt("設計一個分散式系統架構")
    assert result["decision"] == "claude"


def test_classify_fallback_on_error():
    """Ollama 離線 → fallback claude"""
    with patch("urllib.request.urlopen", side_effect=Exception("連線失敗")):
        result = classify_prompt("任何問題")
    assert result["decision"] == "claude"
    assert result["reason"] == "fallback"
```

- [ ] **Step 2: 跑測試確認失敗**

```bash
/Users/surpend/.local-brain/venv/bin/python -m pytest tests/layer0/test_classifier.py -v
```

預期：ImportError（classifier 不存在）

- [ ] **Step 3: 實作 classifier.py**

```python
# layer_0_router/classifier.py
"""Gemma E2B：分類任務為 local（Qwen 處理）或 claude（Claude 處理）"""

import json
import logging
import urllib.request
from typing import Literal

logger = logging.getLogger(__name__)

CLASSIFIER_MODEL = "gemma3:2b"
OLLAMA_BASE = "http://localhost:11434"
ROUTER_TIMEOUT = 10

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
```

- [ ] **Step 4: 跑測試確認通過**

```bash
/Users/surpend/.local-brain/venv/bin/python -m pytest tests/layer0/test_classifier.py -v
```

預期：3 tests PASSED

- [ ] **Step 5: Commit**

```bash
git add layer_0_router/classifier.py tests/layer0/test_classifier.py
git commit -m "feat(layer0): Gemma E2B 任務分類器"
```

---

## Task 2：Compressor（Gemma E4B 壓縮）

**Files:**
- Create: `layer_0_router/compressor.py`
- Create: `tests/layer0/test_compressor.py`

- [ ] **Step 1: 寫測試**

```python
# tests/layer0/test_compressor.py
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from layer_0_router.compressor import compress_context


def _mock_ollama(response_text: str):
    import json
    from unittest.mock import MagicMock
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps({"response": response_text, "done": True}).encode()
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    return mock_resp


def test_compress_returns_string():
    with patch("urllib.request.urlopen") as mock_open:
        mock_open.return_value = _mock_ollama("壓縮後的摘要內容")
        result = compress_context("一段很長的歷史 context 字串" * 20)
    assert isinstance(result, str)
    assert len(result) > 0


def test_compress_short_context_skip():
    """短 context（< 200 字）直接回傳，不呼叫 Ollama"""
    with patch("urllib.request.urlopen") as mock_open:
        result = compress_context("短字串")
    mock_open.assert_not_called()
    assert result == "短字串"


def test_compress_fallback_on_error():
    """Ollama 離線 → 回傳原始截斷版本"""
    long_ctx = "x" * 500
    with patch("urllib.request.urlopen", side_effect=Exception("離線")):
        result = compress_context(long_ctx)
    assert result == long_ctx[:300] + "..."
```

- [ ] **Step 2: 實作 compressor.py**

```python
# layer_0_router/compressor.py
"""Gemma E4B：壓縮長 context 為簡短摘要，供 Qwen 使用"""

import json
import logging
import urllib.request

logger = logging.getLogger(__name__)

COMPRESSOR_MODEL = "gemma3:4b"
OLLAMA_BASE = "http://localhost:11434"
COMPRESS_TIMEOUT = 15
_MIN_LEN_TO_COMPRESS = 200   # 短於此長度直接回傳

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
```

- [ ] **Step 3: 跑測試確認通過**

```bash
/Users/surpend/.local-brain/venv/bin/python -m pytest tests/layer0/test_compressor.py -v
```

預期：3 tests PASSED

- [ ] **Step 4: Commit**

```bash
git add layer_0_router/compressor.py tests/layer0/test_compressor.py
git commit -m "feat(layer0): Gemma E4B context 壓縮器"
```

---

## Task 3：Router 主協調器

**Files:**
- Create: `layer_0_router/__init__.py`
- Create: `layer_0_router/router.py`
- Create: `tests/layer0/test_router.py`

- [ ] **Step 1: 寫測試**

```python
# tests/layer0/test_router.py
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from layer_0_router.router import route


def test_route_claude_skips_qwen():
    """分類為 claude → 直接回傳 None（不呼叫 Qwen）"""
    with patch("layer_0_router.router.classify_prompt") as mock_cls, \
         patch("layer_0_router.router._call_qwen") as mock_qwen:
        mock_cls.return_value = {"decision": "claude", "reason": "複雜"}
        result = route(prompt="複雜問題", rag_context="")
    assert result is None
    mock_qwen.assert_not_called()


def test_route_local_returns_qwen_response():
    """分類為 local → 呼叫 Qwen 並回傳格式化結果"""
    with patch("layer_0_router.router.classify_prompt") as mock_cls, \
         patch("layer_0_router.router.compress_context") as mock_compress, \
         patch("layer_0_router.router._call_qwen") as mock_qwen:
        mock_cls.return_value = {"decision": "local", "reason": "git 操作"}
        mock_compress.return_value = "壓縮後的 context"
        mock_qwen.return_value = "git commit -m 'feat: xxx'"

        result = route(prompt="幫我 git commit", rag_context="過去做過 git commit")

    assert result is not None
    assert "git commit" in result
    assert "🤖" in result  # 有本地建議標記


def test_route_local_qwen_timeout_returns_none():
    """Qwen 呼叫失敗 → 回傳 None（fallback Claude）"""
    with patch("layer_0_router.router.classify_prompt") as mock_cls, \
         patch("layer_0_router.router.compress_context") as mock_compress, \
         patch("layer_0_router.router._call_qwen", return_value=None):
        mock_cls.return_value = {"decision": "local", "reason": "簡單"}
        mock_compress.return_value = ""
        result = route(prompt="任何", rag_context="")
    assert result is None
```

- [ ] **Step 2: 實作 router.py**

```python
# layer_0_router/router.py
"""Layer 0 Router：分類 → 壓縮 → 呼叫 Qwen → 格式化注入字串"""

import json
import logging
import urllib.request

from .classifier import classify_prompt
from .compressor import compress_context

logger = logging.getLogger(__name__)

LOCAL_MODEL = "qwen3:30b-a3b"
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

    # 壓縮 RAG context，控制 Qwen 的 context 長度
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
```

```python
# layer_0_router/__init__.py
```

- [ ] **Step 3: 跑測試確認通過**

```bash
/Users/surpend/.local-brain/venv/bin/python -m pytest tests/layer0/ -v
```

預期：9 tests PASSED（3 + 3 + 3）

- [ ] **Step 4: Commit**

```bash
git add layer_0_router/ tests/layer0/
git commit -m "feat(layer0): router 主協調器（classify → compress → Qwen）"
```

---

## Task 4：整合 session_start_hook.py

**Files:**
- Modify: `layer_1_memory/hooks/session_start_hook.py`

在現有 `main()` 函式的 RAG 注入之後，呼叫 router 並合併輸出。

- [ ] **Step 1: 在 session_start_hook.py 的 import 區加入 router path**

在 `sys.path.insert(0, str(_LAYER1_DIR))` 之後加入：

```python
# 加入專案根目錄（layer_0_router 所在位置）
_PROJECT_DIR = _LAYER1_DIR.parent
sys.path.insert(0, str(_PROJECT_DIR))
```

- [ ] **Step 2: 在 main() 的 RAG 結果後整合 router**

找到現有 `if memory_context:` 區塊，替換為：

```python
        # 嘗試 Layer 0 路由（Ollama 離線時靜默跳過）
        router_context = None
        try:
            from layer_0_router.router import route
            router_context = route(prompt=query, rag_context=memory_context or "")
        except Exception as e:
            logger.warning("Layer 0 router 失敗，跳過：%s", e)

        # 合併 router 建議 + RAG 記憶
        parts = []
        if router_context:
            parts.append(router_context)
        if memory_context:
            parts.append(memory_context)

        combined_context = "\n\n".join(parts) if parts else ""

        if combined_context:
            logger.info(
                "context 注入 %d 字元（session=%s，router=%s）",
                len(combined_context),
                payload.get("session_id", ""),
                "local" if router_context else "rag-only",
            )
            output = {
                "hookSpecificOutput": {
                    "hookEventName": "UserPromptSubmit",
                    "additionalContext": combined_context,
                }
            }
            print(json.dumps(output, ensure_ascii=False))
        else:
            logger.debug("無 context，輸出空物件")
            print(empty_output)
```

- [ ] **Step 3: 確認 hook 基本功能正常（mock router）**

```bash
echo '{"prompt": "幫我 git commit", "session_id": "test-123", "cwd": "/tmp"}' | \
  /Users/surpend/.local-brain/venv/bin/python \
  /Users/surpend/Developer/01_project/shiba-fine-tuning-project/layer_1_memory/hooks/session_start_hook.py
```

預期：輸出 `{}` 或含 `additionalContext` 的 JSON（不 crash 即可）

- [ ] **Step 4: Commit**

```bash
git add layer_1_memory/hooks/session_start_hook.py
git commit -m "feat(layer0): 整合 session_start_hook（router + RAG 合併注入）"
```

---

## 副作用清單

- `ollama pull gemma3:2b`（~1.7GB）、`gemma3:4b`（~2.5GB）：需磁碟空間與下載時間
- Gemma 分類每次 UserPromptSubmit 觸發，增加約 1-3 秒延遲（ROUTER_TIMEOUT=10s）
- Qwen 呼叫最多 30 秒（QWEN_TIMEOUT）：若 Qwen 忙碌（已載入大模型），可能延遲
- `OLLAMA_MAX_LOADED_MODELS=1`：Gemma 呼叫時若 Qwen 已載入，會觸發 model swap（耗時）
  → **建議**：Gemma E2B + E4B 輕量，swap 時間可接受，但高峰期可能拖慢 hook
- session_start_hook 失敗不影響 Claude 正常對話（所有路徑都有 try/except fallback）

---

## 驗證指令

```bash
# 1. 跑所有 layer0 測試
/Users/surpend/.local-brain/venv/bin/python -m pytest tests/layer0/ -v

# 2. 確認 Gemma 模型可用
ollama run gemma3:2b "回覆 ok" --nowordwrap 2>/dev/null | head -3

# 3. 端對端測試 hook
echo '{"prompt": "幫我 git commit -m feat", "session_id": "e2e-test", "cwd": "/tmp"}' | \
  /Users/surpend/.local-brain/venv/bin/python \
  /Users/surpend/Developer/01_project/shiba-fine-tuning-project/layer_1_memory/hooks/session_start_hook.py
```
