"""
teacher_service.py — Teacher CRUD 與評分呼叫

職責：
1. Teacher CRUD（新增/查詢/切換啟用）
2. 從 macOS Keychain 取得 API Key（不存 key 本身）
3. 透過 OpenAI-compatible client 呼叫 Teacher 評分（單次）
4. 記錄 teacher_usage_logs（配額追蹤）

評分聚合策略由 services/multi_judge.py 主導（A4 後）：
  三方投票（≥8 算一票 approved）→ 3/3 approved weight=1.0；2/3 soft label weight=0.5；
  ≤1/3 rejected。Shiba 採納（router_decisions.user_accepted=1）→ 強制 approved（high_value）
"""

import json
import logging
import os
import subprocess
from datetime import date, datetime, timezone
from typing import Any

import sqlite3

logger = logging.getLogger(__name__)

# 評分 prompt 模板（含 few-shot 校準範例，F1）
_SCORE_PROMPT = """你是一個訓練資料品質評審。請評估以下訓練樣本的品質。

評分標準（0-10）：
- 10：完美，instruction 清晰，output 正確完整，可直接用於訓練
- 8-9：良好，有小瑕疵但不影響訓練效果
- 6-7：可接受，需人工複審
- 4-5：有問題，output 不完整或有錯誤
- 0-3：不適合訓練，output 明顯錯誤或無關

---校準範例---
```yaml
high_quality:
  - score: 9
    reason: "instruction 清晰，output 包含完整 stash 流程且命令正確"
    instruction: "暫存目前修改並切換至 hotfix 分支"
    output: |
      git stash save "WIP: feature-x"
      git checkout hotfix/critical-bug
      # 完成後：git checkout feature-x && git stash pop

  - score: 10
    reason: "精確重現 NoneType 根因，修復方式正確且有防禦性處理"
    instruction: "修復 TypeError: NoneType object is not subscriptable"
    input: "data = get_user(id); return data['name']"
    output: |
      data = get_user(id)
      if data is None:
          raise ValueError(f"User {{id}} not found")
      return data['name']

  - score: 9
    reason: "SQLite WAL 啟用函式簡潔正確，幂等設計合理"
    instruction: "新增 SQLite WAL 模式啟用函式（需幂等）"
    output: |
      def enable_wal(conn):
          conn.execute("PRAGMA journal_mode=WAL")
          conn.commit()

low_quality:
  - score: 4
    reason: "output 只有單行指令，缺少衝突解決說明，不完整"
    instruction: "執行 git rebase 並解決衝突"
    output: "git rebase main"

  - score: 3
    reason: "git commit -a 會包含所有追蹤檔案，不符合只提交特定檔案的需求"
    instruction: "只提交 src/api.py 的修改"
    output: "git commit -a -m 'fix: update api'"

  - score: 2
    reason: "output 與 instruction 完全無關，未回答問題"
    instruction: "計算 list 中所有偶數的總和"
    input: "nums = [1, 2, 3, 4, 5, 6]"
    output: "可以使用 Python 的 filter 函式來過濾清單中的元素。"
```
---

待評樣本：
Instruction: {instruction}
Input: {input}
Output: {output}

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
    keychain_ref: str | None = None,
    priority: int = 0,
    daily_limit: int = 250,
    daily_request_limit: int | None = None,
    daily_token_limit: int | None = None,
    quota_reset_period: str = "daily",
) -> int:
    """新增或更新 Teacher（依 name UPSERT）"""
    # daily_request_limit 預設與 daily_limit 一致（向後相容）
    if daily_request_limit is None:
        daily_request_limit = daily_limit

    existing = conn.execute(
        "SELECT id FROM teachers WHERE name = ?", (name,)
    ).fetchone()

    if existing:
        conn.execute(
            """UPDATE teachers SET model_id=?, api_base=?, keychain_ref=?,
               priority=?, daily_limit=?, daily_request_limit=?,
               daily_token_limit=?, quota_reset_period=? WHERE id=?""",
            (model_id, api_base, keychain_ref, priority, daily_limit,
             daily_request_limit, daily_token_limit, quota_reset_period,
             existing["id"]),
        )
        conn.commit()
        return existing["id"]

    cur = conn.execute(
        """INSERT INTO teachers
               (name, model_id, api_base, keychain_ref, priority, daily_limit,
                daily_request_limit, daily_token_limit, quota_reset_period)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (name, model_id, api_base, keychain_ref, priority, daily_limit,
         daily_request_limit, daily_token_limit, quota_reset_period),
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
    """檢查 Teacher 今日配額是否還有餘裕（達限時自動標記）"""
    used = get_today_usage(conn, teacher["id"])
    if used >= teacher["daily_limit"]:
        _mark_daily_limit_reached(conn, teacher["id"])
        return False
    return True


# ── Keychain ─────────────────────────────────────────────────────────────

def _env_key_name(keychain_ref: str) -> str:
    """將 keychain_ref 轉成 env 變數名（大寫、非英數底線 → 底線）。
    e.g. "shiba-gemini-flash-api-key" → "SHIBA_TEACHER_KEY_SHIBA_GEMINI_FLASH_API_KEY"
    """
    safe = "".join(c if c.isalnum() else "_" for c in keychain_ref)
    return f"SHIBA_TEACHER_KEY_{safe.upper()}"


def get_api_key(keychain_ref: str) -> str | None:
    """
    取得 Teacher API Key。先試 macOS Keychain，失敗 fallback 環境變數。

    - Host（macOS）：subprocess 呼叫 `security find-generic-password` 讀 Keychain
    - Docker / Linux：Keychain 不存在，直接走 env fallback
      env 名稱規則見 `_env_key_name`，docker-compose 透過 `.env` 注入
    """
    # 1) macOS Keychain（host 環境）
    try:
        result = subprocess.run(
            ["security", "find-generic-password", "-s", keychain_ref, "-w"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except FileNotFoundError:
        # `security` 指令不存在（非 macOS，例如 docker container）— 靜默改走 env
        pass
    except Exception as e:
        logger.warning("Keychain 存取例外 ref=%s: %s（嘗試 env fallback）", keychain_ref, e)

    # 2) 環境變數 fallback
    env_name = _env_key_name(keychain_ref)
    value = os.environ.get(env_name)
    if value:
        return value.strip()

    logger.warning("API Key 找不到：Keychain 與 env(%s) 皆無 ref=%s", env_name, keychain_ref)
    return None


# ── 評分呼叫 ─────────────────────────────────────────────────────────────

def _call_teacher(
    teacher: sqlite3.Row,
    instruction: str,
    input_text: str,
    output: str,
    conn: sqlite3.Connection,
    sample_id: int,
) -> dict | None:
    """
    呼叫 Teacher API，回傳 {'score': float, 'reason': str} 或 None（失敗）。
    內部完整處理 log_usage + requests_today 計數更新（C2/C3）。
    """
    # C3：keychain_ref = NULL → 本地模型，跳過 Keychain
    if teacher["keychain_ref"] is not None:
        api_key = get_api_key(teacher["keychain_ref"])
        if not api_key:
            logger.warning("Teacher %s 無法取得 API Key", teacher["name"])
            _log_usage(conn, teacher["id"], sample_id, 0, 0, "error")
            return None
    else:
        api_key = "none"  # 本地 Ollama 不需要真實 key

    prompt = _SCORE_PROMPT.format(
        instruction=instruction[:500],
        input=input_text[:200],
        output=output[:500],
    )
    if "generativelanguage.googleapis.com" in teacher["api_base"]:
        raw, input_t, output_t, status = _call_gemini_rest(api_key, teacher["model_id"], prompt)
    else:
        raw, input_t, output_t, status = _call_openai_compat(
            api_key, teacher["api_base"], teacher["model_id"], prompt
        )

    if status == "quota_exceeded":
        _log_usage(conn, teacher["id"], sample_id, 0, 0, "quota_exceeded")
        _mark_daily_limit_reached(conn, teacher["id"])
        _mark_quota_exhausted(conn, teacher["id"], "requests")
        return None

    if raw is None:
        _log_usage(conn, teacher["id"], sample_id, 0, 0, "error")
        return None

    try:
        data = json.loads(_strip_markdown(raw))
        score = float(data["score"])
        reason = str(data.get("reason", ""))
    except (json.JSONDecodeError, ValueError, KeyError) as e:
        logger.error("Teacher %s 回應解析失敗（raw=%s…）：%s", teacher["name"], raw[:100], e)
        _log_usage(conn, teacher["id"], sample_id, 0, 0, "error")
        return None

    # C2：記錄 log + 更新 teachers 今日計數
    _log_usage(conn, teacher["id"], sample_id, input_t, output_t, "success")
    _record_teacher_usage(conn, teacher["id"], input_t, output_t)

    return {"score": max(0.0, min(10.0, score)), "reason": reason}


def _call_gemini_rest(
    api_key: str,
    model_id: str,
    prompt: str,
    force_json: bool = True,
    max_tokens: int = 150,
) -> tuple[str | None, int, int, str]:
    """Gemini 原生 REST API 呼叫，回傳 (text, input_tokens, output_tokens, status)"""
    import urllib.request
    import urllib.error

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_id}:generateContent?key={api_key}"
    gen_config: dict = {"maxOutputTokens": max_tokens, "temperature": 0.1}
    if force_json:
        gen_config["responseMimeType"] = "application/json"
    body = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": gen_config,
    }).encode()

    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
            text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
            usage = data.get("usageMetadata", {})
            input_t = usage.get("promptTokenCount", 0)
            output_t = usage.get("candidatesTokenCount", 0)
            return text, input_t, output_t, "success"
    except urllib.error.HTTPError as e:
        if e.code == 429:
            return None, 0, 0, "quota_exceeded"
        logger.error("Gemini REST 失敗 HTTP %s", e.code)
        return None, 0, 0, "error"
    except Exception as e:
        logger.error("Gemini REST 呼叫失敗：%s", e)
        return None, 0, 0, "error"


def _call_openai_compat(
    api_key: str,
    api_base: str,
    model_id: str,
    prompt: str,
    max_tokens: int = 150,
) -> tuple[str | None, int, int, str]:
    """OpenAI-compatible 端點呼叫（Ollama / Mistral 等），回傳 (text, input_tokens, output_tokens, status)"""
    from openai import OpenAI, RateLimitError
    client = OpenAI(api_key=api_key, base_url=api_base)
    try:
        resp = client.chat.completions.create(
            model=model_id,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=max_tokens,
            temperature=0.1,
        )
        content = resp.choices[0].message.content.strip()
        input_t = resp.usage.prompt_tokens if resp.usage else 0
        output_t = resp.usage.completion_tokens if resp.usage else 0
        return content, input_t, output_t, "success"
    except RateLimitError:
        return None, 0, 0, "quota_exceeded"
    except Exception as e:
        logger.error("OpenAI-compat 呼叫失敗：%s", e)
        return None, 0, 0, "error"


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


def _mark_daily_limit_reached(conn: sqlite3.Connection, teacher_id: int) -> None:
    conn.execute(
        "UPDATE teachers SET is_daily_limit_reached = 1 WHERE id = ?", (teacher_id,)
    )
    conn.commit()
    logger.warning("Teacher id=%s 已達每日額度上限，標記停用", teacher_id)


def _mark_quota_exhausted(
    conn: sqlite3.Connection,
    teacher_id: int,
    exhausted_type: str,  # 'requests' | 'tokens'
) -> None:
    """記錄配額耗盡時間與類型"""
    conn.execute(
        "UPDATE teachers SET quota_exhausted_at=datetime('now'), quota_exhausted_type=? WHERE id=?",
        (exhausted_type, teacher_id),
    )
    conn.commit()


def _record_teacher_usage(
    conn: sqlite3.Connection,
    teacher_id: int,
    input_tokens: int,
    output_tokens: int,
) -> None:
    """C2：更新 teachers 表今日計數器（requests_today / token 計數）"""
    conn.execute(
        """UPDATE teachers SET
               requests_today     = COALESCE(requests_today, 0) + 1,
               input_tokens_today = COALESCE(input_tokens_today, 0) + ?,
               output_tokens_today= COALESCE(output_tokens_today, 0) + ?
           WHERE id = ?""",
        (input_tokens, output_tokens, teacher_id),
    )
    conn.commit()


def _log_usage(
    conn: sqlite3.Connection,
    teacher_id: int,
    sample_id: int,
    input_tokens: int = 0,
    output_tokens: int = 0,
    response_status: str = "success",
) -> None:
    tokens_used = input_tokens + output_tokens
    conn.execute(
        """INSERT INTO teacher_usage_logs
               (teacher_id, sample_id, tokens_used, input_tokens, output_tokens, response_status)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (teacher_id, sample_id, tokens_used, input_tokens, output_tokens, response_status),
    )
    conn.commit()


def call_teacher_for_test(
    teacher: sqlite3.Row,
    prompt: str,
) -> tuple[str | None, int, int, str]:
    """
    對 Teacher 發送任意 prompt（前端測試用，不計入 usage log 與 requests_today）。
    回傳 (text, input_tokens, output_tokens, status)。
    """
    # C3：keychain_ref = NULL → 本地模型
    if teacher["keychain_ref"] is not None:
        api_key = get_api_key(teacher["keychain_ref"])
        if not api_key:
            return None, 0, 0, "no_key"
    else:
        api_key = "none"

    if "generativelanguage.googleapis.com" in teacher["api_base"]:
        return _call_gemini_rest(api_key, teacher["model_id"], prompt, force_json=False, max_tokens=200)
    else:
        return _call_openai_compat(api_key, teacher["api_base"], teacher["model_id"], prompt, max_tokens=200)
