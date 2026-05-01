"""
refiner_service.py — Qwen 本地精煉器

在 extraction → teacher scoring 之間插入：
1. regex PII scrub（不呼叫 LLM）
2. Qwen 自包含性判斷 + 必要時改寫 + 草擬 expected_answer

Ollama 離線時自動 fallback（直接標為 pending，跳過精煉）。
"""

import json
import logging
import re
import sqlite3
import urllib.error
import urllib.request
from datetime import datetime, timezone

from ..core.config import (
    OLLAMA_BASE_URL,
    REFINER_BATCH_LIMIT,
    REFINER_MODEL,
    REFINER_OPTIONS,
    REFINER_TIMEOUT,
)

logger = logging.getLogger(__name__)

# ── PII 正則模式（優先順序：具體 → 通用）───────────────────────────────
_PII_PATTERNS = [
    (re.compile(r'/Users/[^/\s]+/[^\s"\']{3,}'), '<PROJECT_PATH>'),
    (re.compile(r'\b(?:192\.168|127\.\d+)\.\d+\.\d+\b'), '<LOCAL_IP>'),
    (re.compile(r'(?:password|passwd|api[_-]?key|secret|token)\s*[=:]\s*\S+', re.I), '<REDACTED>'),
    (re.compile(r'(?:export\s+)?[A-Z][A-Z0-9_]{3,}\s*=\s*\S+'), '<REDACTED>'),
    (re.compile(r'\b[a-z][a-z0-9-]{2,}\.local\b', re.I), '<MACHINE_NAME>'),
]

# ── 精煉 Prompt 模板 ─────────────────────────────────────────────────
_REFINE_PROMPT = """\
你是一個訓練資料預處理助手。分析以下 instruction，判斷它是否「自包含」
（新的語言模型在沒有額外上下文的情況下，能理解並回答）。

【Instruction】
{instruction}

【Input（上下文，可為空）】
{input}

判斷規則：
- 含「我的專案」「這個錯誤」「剛才的程式碼」等隱含指稱 → 不自包含
- 本身是完整技術問題或任務 → 自包含
- 含 <PROJECT_PATH> 等佔位符但問題可理解 → 自包含

若不自包含：改寫為自包含版本（保留技術意圖，抽象化專案細節，不加新假設）。
草擬 expected_answer（≤100字）作為評分參考。

只回覆 JSON，不加任何其他文字：
{{
  "is_self_contained": true/false,
  "rewritten_instruction": "改寫後或 null",
  "expected_answer": "簡短預期答案"
}}"""


# ── PII Scrubbing ─────────────────────────────────────────────────────

def scrub_pii(text: str) -> str:
    """對單一字串套用所有 PII 正則替換"""
    for pattern, replacement in _PII_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def scrub_sample_fields(
    instruction: str, input_text: str, output: str
) -> tuple[str, str, str, bool]:
    """
    對三個 Alpaca 欄位做 PII scrub。
    回傳 (scrubbed_instruction, scrubbed_input, scrubbed_output, was_changed)
    """
    si = scrub_pii(instruction)
    inp = scrub_pii(input_text)
    sout = scrub_pii(output)
    was_changed = (si != instruction) or (inp != input_text) or (sout != output)
    return si, inp, sout, was_changed


# ── Ollama 呼叫 ───────────────────────────────────────────────────────

def _is_ollama_available(base_url: str) -> bool:
    """HEAD /api/tags 確認 Ollama 可用"""
    try:
        req = urllib.request.Request(f"{base_url}/api/tags", method="HEAD")
        with urllib.request.urlopen(req, timeout=3):
            return True
    except (urllib.error.URLError, OSError, TimeoutError):
        return False


def _call_qwen(prompt: str, base_url: str, model: str, timeout: int) -> str | None:
    """POST /api/generate，回傳模型原始文字，失敗回傳 None"""
    payload = json.dumps({
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": REFINER_OPTIONS,
    }).encode()

    req = urllib.request.Request(
        f"{base_url}/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
            return data.get("response", "")
    except Exception as exc:
        logger.warning("Qwen 呼叫失敗：%s", exc)
        return None


def _parse_qwen_response(raw: str) -> dict | None:
    """
    解析 Qwen 回傳文字為 dict。
    處理 markdown code fence（```json ... ```）。
    """
    if not raw:
        return None
    # 去除 code fence
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(lines[1:-1]) if len(lines) > 2 else text
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        logger.warning("無法解析 Qwen JSON：%s", text[:200])
        return None


# ── 單筆精煉 ─────────────────────────────────────────────────────────

def refine_sample(
    instruction: str,
    input_text: str,
    output: str,
    base_url: str = OLLAMA_BASE_URL,
    model: str = REFINER_MODEL,
) -> dict:
    """
    單筆精煉流程：
    1. PII scrub
    2. 呼叫 Qwen（若不可用跳過）
    3. 解析回應
    回傳完整欄位 dict（含 qwen_available 旗標）
    """
    si, inp, sout, pii_changed = scrub_sample_fields(instruction, input_text, output)

    result = {
        "instruction": si,
        "input": inp,
        "output": sout,
        "refined_instruction": None,
        "expected_answer": None,
        "pii_scrubbed": int(pii_changed),
        "qwen_available": False,
    }

    if not _is_ollama_available(base_url):
        return result

    result["qwen_available"] = True
    prompt = _REFINE_PROMPT.format(instruction=si, input=inp)
    raw = _call_qwen(prompt, base_url, model, REFINER_TIMEOUT)
    parsed = _parse_qwen_response(raw)
    if not parsed:
        return result

    if not parsed.get("is_self_contained", True):
        result["refined_instruction"] = parsed.get("rewritten_instruction")
    result["expected_answer"] = parsed.get("expected_answer")

    return result


# ── 批次精煉 ─────────────────────────────────────────────────────────

def refine_pending_raw_samples(conn_factory) -> dict:
    """
    批次處理 status='raw' 樣本（最多 REFINER_BATCH_LIMIT 筆）。
    Ollama 不可用時 fallback：直接設 status='pending'。
    回傳 {refined: int, fallback: int, failed: int}
    """
    conn: sqlite3.Connection = conn_factory()
    stats = {"refined": 0, "fallback": 0, "failed": 0}

    try:
        rows = conn.execute(
            """SELECT id, instruction, input, output
               FROM training_samples WHERE status = 'raw'
               ORDER BY id LIMIT ?""",
            (REFINER_BATCH_LIMIT,),
        ).fetchall()

        if not rows:
            return stats

        ollama_up = _is_ollama_available(OLLAMA_BASE_URL)

        for row in rows:
            sample_id = row["id"]
            try:
                if not ollama_up:
                    # Fallback：PII scrub only，直接升 pending
                    si, inp, sout, pii_changed = scrub_sample_fields(
                        row["instruction"], row["input"] or "", row["output"]
                    )
                    conn.execute(
                        """UPDATE training_samples
                           SET instruction=?, input=?, output=?,
                               pii_scrubbed=?, status='pending'
                           WHERE id=?""",
                        (si, inp, sout, int(pii_changed), sample_id),
                    )
                    stats["fallback"] += 1
                else:
                    refined = refine_sample(
                        row["instruction"], row["input"] or "", row["output"]
                    )
                    conn.execute(
                        """UPDATE training_samples
                           SET instruction=?, input=?, output=?,
                               refined_instruction=?, expected_answer=?,
                               pii_scrubbed=?, status='pending'
                           WHERE id=?""",
                        (
                            refined["instruction"],
                            refined["input"],
                            refined["output"],
                            refined["refined_instruction"],
                            refined["expected_answer"],
                            refined["pii_scrubbed"],
                            sample_id,
                        ),
                    )
                    stats["refined"] += 1

            except Exception as exc:
                logger.error("精煉 sample_id=%d 失敗：%s", sample_id, exc)
                stats["failed"] += 1

        conn.commit()
        logger.info("批次精煉完成：%s", stats)
        return stats

    finally:
        conn.close()
