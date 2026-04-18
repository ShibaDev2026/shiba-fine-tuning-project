"""
teacher_service.py — Teacher CRUD 與評分呼叫

職責：
1. Teacher CRUD（新增/查詢/切換啟用）
2. 從 macOS Keychain 取得 API Key（不存 key 本身）
3. 透過 OpenAI-compatible client 呼叫 Teacher 評分
4. 記錄 teacher_usage_logs（配額追蹤）

評分流程（SEAL + CLAUDE.md）：
  Gemini 2.5 Flash 初裁 → ≥8 auto approved，6-7 送第二裁判，<6 rejected
  兩裁判差距 > 2 標記 needs_review
"""

import json
import logging
import subprocess
from datetime import date, datetime, timezone
from typing import Any

import sqlite3

logger = logging.getLogger(__name__)

# ── 評分門檻（對應 CLAUDE.md Layer 2 評分流程）────────────────────────
_SCORE_AUTO_APPROVE = 8.0
_SCORE_AUTO_REJECT = 6.0
_SCORE_DISAGREEMENT_THRESHOLD = 2.0

# 評分 prompt 模板
_SCORE_PROMPT = """你是一個訓練資料品質評審。請評估以下訓練樣本的品質。

Instruction: {instruction}
Input: {input}
Output: {output}

評分標準（0-10）：
- 10：完美，instruction 清晰，output 正確完整，可直接用於訓練
- 8-9：良好，有小瑕疵但不影響訓練效果
- 6-7：可接受，需人工複審
- 4-5：有問題，output 不完整或有錯誤
- 0-3：不適合訓練，output 明顯錯誤或無關

請只回覆 JSON：{{"score": <0-10的數字>, "reason": "<一句評分理由>"}}"""


# ── Teacher CRUD ─────────────────────────────────────────────────────────

def get_active_teachers(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """取得所有啟用中的 Teacher，依 priority 排序"""
    return conn.execute(
        "SELECT * FROM teachers WHERE is_active = 1 ORDER BY priority"
    ).fetchall()


def get_teacher_by_id(conn: sqlite3.Connection, teacher_id: int) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM teachers WHERE id = ?", (teacher_id,)
    ).fetchone()


def upsert_teacher(
    conn: sqlite3.Connection,
    name: str,
    model_id: str,
    api_base: str,
    keychain_ref: str,
    priority: int = 0,
    daily_limit: int = 250,
) -> int:
    """新增或更新 Teacher（依 name UPSERT）"""
    existing = conn.execute(
        "SELECT id FROM teachers WHERE name = ?", (name,)
    ).fetchone()

    if existing:
        conn.execute(
            """UPDATE teachers SET model_id=?, api_base=?, keychain_ref=?,
               priority=?, daily_limit=? WHERE id=?""",
            (model_id, api_base, keychain_ref, priority, daily_limit, existing["id"]),
        )
        conn.commit()
        return existing["id"]

    cur = conn.execute(
        """INSERT INTO teachers (name, model_id, api_base, keychain_ref, priority, daily_limit)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (name, model_id, api_base, keychain_ref, priority, daily_limit),
    )
    conn.commit()
    return cur.lastrowid


def get_today_usage(conn: sqlite3.Connection, teacher_id: int) -> int:
    """取得今日已使用次數"""
    today = date.today().isoformat()
    row = conn.execute(
        """SELECT COUNT(*) as cnt FROM teacher_usage_logs
           WHERE teacher_id = ? AND used_at >= ?""",
        (teacher_id, today),
    ).fetchone()
    return row["cnt"] if row else 0


def is_quota_available(conn: sqlite3.Connection, teacher: sqlite3.Row) -> bool:
    """檢查 Teacher 今日配額是否還有餘裕"""
    used = get_today_usage(conn, teacher["id"])
    return used < teacher["daily_limit"]


# ── Keychain ─────────────────────────────────────────────────────────────

def get_api_key(keychain_ref: str) -> str | None:
    """
    從 macOS Keychain 取得 API Key。
    keychain_ref 為 Keychain item 的 service name。
    """
    try:
        result = subprocess.run(
            ["security", "find-generic-password", "-s", keychain_ref, "-w"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
        logger.warning("Keychain 找不到 ref=%s", keychain_ref)
        return None
    except Exception as e:
        logger.error("Keychain 存取失敗 ref=%s: %s", keychain_ref, e)
        return None


# ── 評分呼叫 ─────────────────────────────────────────────────────────────

def score_sample(
    conn: sqlite3.Connection,
    sample_id: int,
    instruction: str,
    input_text: str,
    output: str,
) -> dict:
    """
    用可用的 Teacher 評分單筆樣本。
    實作 CLAUDE.md 評分流程：
      ≥8 → approved；6-7 → needs_review；<6 → rejected
      若有第二裁判且差距 > 2 → needs_review

    回傳 {'score': float, 'status': str, 'reason': str, 'teacher_id': int}
    """
    teachers = get_active_teachers(conn)
    if not teachers:
        return {"score": None, "status": "pending", "reason": "無可用 Teacher", "teacher_id": None}

    # 初裁
    first_teacher = _pick_available_teacher(conn, teachers)
    if not first_teacher:
        return {"score": None, "status": "pending", "reason": "所有 Teacher 配額已滿", "teacher_id": None}

    first_result = _call_teacher(first_teacher, instruction, input_text, output)
    if first_result is None:
        return {"score": None, "status": "pending", "reason": "Teacher API 呼叫失敗", "teacher_id": first_teacher["id"]}

    _log_usage(conn, first_teacher["id"], sample_id)
    first_score = first_result["score"]

    # API 呼叫失敗（非配額問題）→ 嘗試 fallback teacher
    if first_result is None:
        fallback = _pick_available_teacher(conn, teachers, exclude_id=first_teacher["id"])
        if fallback:
            first_result = _call_teacher(fallback, instruction, input_text, output)
            if first_result:
                _log_usage(conn, fallback["id"], sample_id)
                first_teacher = fallback
        if first_result is None:
            return {"score": None, "status": "pending", "reason": "所有 Teacher API 呼叫失敗", "teacher_id": first_teacher["id"]}
    first_score = first_result["score"]

    # 快速路徑：自動 approved 或 rejected
    if first_score >= _SCORE_AUTO_APPROVE:
        _update_sample_score(conn, sample_id, first_score, first_result["reason"], "approved")
        return {"score": first_score, "status": "approved", "reason": first_result["reason"], "teacher_id": first_teacher["id"]}

    if first_score < _SCORE_AUTO_REJECT:
        _update_sample_score(conn, sample_id, first_score, first_result["reason"], "rejected")
        return {"score": first_score, "status": "rejected", "reason": first_result["reason"], "teacher_id": first_teacher["id"]}

    # 6-7 分：送第二裁判
    second_teacher = _pick_available_teacher(conn, teachers, exclude_id=first_teacher["id"])
    if not second_teacher:
        # 無第二裁判，直接 needs_review
        _update_sample_score(conn, sample_id, first_score, first_result["reason"], "needs_review")
        return {"score": first_score, "status": "needs_review", "reason": "需人工複審（無第二裁判）", "teacher_id": first_teacher["id"]}

    second_result = _call_teacher(second_teacher, instruction, input_text, output)
    if second_result is None:
        _update_sample_score(conn, sample_id, first_score, first_result["reason"], "needs_review")
        return {"score": first_score, "status": "needs_review", "reason": "第二裁判呼叫失敗", "teacher_id": first_teacher["id"]}

    _log_usage(conn, second_teacher["id"], sample_id)
    second_score = second_result["score"]

    # 差距 > 2 → needs_review
    if abs(first_score - second_score) > _SCORE_DISAGREEMENT_THRESHOLD:
        avg = (first_score + second_score) / 2
        reason = f"兩裁判分歧（{first_score} vs {second_score}）"
        _update_sample_score(conn, sample_id, avg, reason, "needs_review")
        return {"score": avg, "status": "needs_review", "reason": reason, "teacher_id": first_teacher["id"]}

    # 取平均，重新判定
    avg = (first_score + second_score) / 2
    status = "approved" if avg >= _SCORE_AUTO_APPROVE else "needs_review"
    _update_sample_score(conn, sample_id, avg, second_result["reason"], status)
    return {"score": avg, "status": status, "reason": second_result["reason"], "teacher_id": first_teacher["id"]}


def _pick_available_teacher(
    conn: sqlite3.Connection,
    teachers: list[sqlite3.Row],
    exclude_id: int | None = None,
) -> sqlite3.Row | None:
    """選出第一個有配額的 Teacher（priority 順序）"""
    for t in teachers:
        if exclude_id and t["id"] == exclude_id:
            continue
        if is_quota_available(conn, t):
            return t
    return None


def _call_teacher(
    teacher: sqlite3.Row,
    instruction: str,
    input_text: str,
    output: str,
) -> dict | None:
    """
    呼叫 Teacher API（OpenAI-compatible）。
    回傳 {'score': float, 'reason': str} 或 None（失敗時）。
    """
    api_key = get_api_key(teacher["keychain_ref"])
    if not api_key:
        logger.warning("Teacher %s 無法取得 API Key", teacher["name"])
        return None

    try:
        prompt = _SCORE_PROMPT.format(
            instruction=instruction[:500],
            input=input_text[:200],
            output=output[:500],
        )
        # Gemini 原生 REST（直接呼叫 /v1beta/models/，不走 OpenAI-compat）
        if "generativelanguage.googleapis.com" in teacher["api_base"]:
            raw = _call_gemini_rest(api_key, teacher["model_id"], prompt)
        else:
            raw = _call_openai_compat(api_key, teacher["api_base"], teacher["model_id"], prompt)

        if raw is None:
            return None
        data = json.loads(_strip_markdown(raw))
        score = float(data["score"])
        reason = str(data.get("reason", ""))
        return {"score": max(0.0, min(10.0, score)), "reason": reason}

    except Exception as e:
        logger.error("Teacher %s 評分失敗：%s", teacher["name"], e)
        return None


def _call_gemini_rest(api_key: str, model_id: str, prompt: str) -> str | None:
    """Gemini 原生 REST API 呼叫（/v1beta/models/{model}:generateContent?key=...）"""
    import urllib.request

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_id}:generateContent?key={api_key}"
    body = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"maxOutputTokens": 150, "temperature": 0.1},
    }).encode()

    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
            return data["candidates"][0]["content"]["parts"][0]["text"].strip()
    except Exception as e:
        logger.error("Gemini REST 呼叫失敗：%s", e)
        return None


def _call_openai_compat(api_key: str, api_base: str, model_id: str, prompt: str) -> str | None:
    """OpenAI-compatible 端點呼叫（Mistral 等其他 Teacher）"""
    from openai import OpenAI
    client = OpenAI(api_key=api_key, base_url=api_base)
    try:
        resp = client.chat.completions.create(
            model=model_id,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=150,
            temperature=0.1,
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        logger.error("OpenAI-compat 呼叫失敗：%s", e)
        return None


def _strip_markdown(text: str) -> str:
    """移除 LLM 回傳的 markdown code block wrapper"""
    text = text.strip()
    if text.startswith("```"):
        # 移除開頭的 ```json 或 ```
        text = text[text.index("\n") + 1:] if "\n" in text else text[3:]
    if text.endswith("```"):
        text = text[:-3]
    return text.strip()


def _update_sample_score(
    conn: sqlite3.Connection,
    sample_id: int,
    score: float,
    reason: str,
    status: str,
) -> None:
    conn.execute(
        """UPDATE training_samples
           SET score=?, score_reason=?, status=?, reviewed_at=datetime('now')
           WHERE id=?""",
        (score, reason, status, sample_id),
    )
    conn.commit()


def _log_usage(
    conn: sqlite3.Connection, teacher_id: int, sample_id: int
) -> None:
    conn.execute(
        "INSERT INTO teacher_usage_logs (teacher_id, sample_id) VALUES (?, ?)",
        (teacher_id, sample_id),
    )
    conn.commit()
