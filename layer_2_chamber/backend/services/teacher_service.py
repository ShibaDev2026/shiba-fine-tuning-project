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
from datetime import date, datetime, timedelta, timezone
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

def _vendor_of(teacher: sqlite3.Row) -> str | None:
    """安全取廠牌：欄位不存在或為 NULL 時回 None（讓下游用 client 預設）。"""
    try:
        v = teacher["vendor"]
    except (KeyError, IndexError):
        return None
    return v or None


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
    """
    檢查 Teacher 是否可用（三層檢查，PR-B）：
      1. 每日配額未耗盡（is_daily_limit_reached=0 且 used < daily_limit）
      2. 不在短暫回退中（transient_backoff_until <= now 或為 NULL）
      3. RPM 窗口未滿（由 _consume_rpm_slot 在實際呼叫前原子檢查）

    本函式只做 1+2 兩層 cheap check；第 3 層在 _consume_rpm_slot 內做。
    """
    teacher_id = teacher["id"]

    # 1. 每日配額（DB 標記優先，避免重複 COUNT(*)）
    if teacher["is_daily_limit_reached"]:
        return False
    used = get_today_usage(conn, teacher_id)
    if used >= teacher["daily_limit"]:
        _mark_daily_limit_reached(conn, teacher_id)
        return False

    # 2. 短暫回退（RPM 觸發後的冷卻期；過期則清除）
    try:
        backoff_until = teacher["transient_backoff_until"]
    except (KeyError, IndexError):
        backoff_until = None  # 舊 row 無此欄位（migration 未跑時 fallback）
    if backoff_until:
        try:
            until = datetime.fromisoformat(backoff_until)
            if until.tzinfo is None:
                until = until.replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) < until:
                return False
            # 已過期 → 清除標記
            conn.execute(
                "UPDATE teachers SET transient_backoff_until=NULL WHERE id=?",
                (teacher_id,),
            )
            conn.commit()
        except ValueError:
            pass  # 解析失敗，當作未設定

    return True


def _consume_rpm_slot(conn: sqlite3.Connection, teacher: sqlite3.Row) -> bool:
    """
    PR-B：原子推進 RPM 窗口並 +1 計數；超限時設 transient_backoff_until。

    回傳 True = 取得 slot 可發起請求；False = 窗口已滿，呼叫端應改試下一個 teacher。

    rpm_limit IS NULL → 不限速率（local Ollama、低用量 teacher），直接回 True。
    """
    try:
        rpm_limit = teacher["rpm_limit"]
    except (KeyError, IndexError):
        return True  # 舊 row：fail open
    if rpm_limit is None:
        return True

    teacher_id = teacher["id"]
    now = datetime.now(timezone.utc)

    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT rpm_window_start, rpm_count_in_window FROM teachers WHERE id=?",
            (teacher_id,),
        ).fetchone()
        win_start_str = row["rpm_window_start"] if row else None
        count = (row["rpm_count_in_window"] or 0) if row else 0

        win_start = None
        win_expired = True
        if win_start_str:
            try:
                win_start = datetime.fromisoformat(win_start_str)
                if win_start.tzinfo is None:
                    win_start = win_start.replace(tzinfo=timezone.utc)
                win_expired = (now - win_start).total_seconds() > 60.0
            except ValueError:
                win_expired = True

        if win_expired:
            new_start = now
            new_count = 1
        else:
            new_start = win_start
            new_count = count + 1

        if new_count > rpm_limit:
            # 觸頂 → 設回退到本窗口結束
            backoff_end = new_start + timedelta(seconds=60)
            conn.execute(
                "UPDATE teachers SET transient_backoff_until=? WHERE id=?",
                (backoff_end.isoformat(), teacher_id),
            )
            conn.commit()
            logger.info(
                "Teacher %d RPM 窗口滿（%d/%d），backoff to %s",
                teacher_id, count, rpm_limit, backoff_end.isoformat(),
            )
            return False

        conn.execute(
            "UPDATE teachers SET rpm_window_start=?, rpm_count_in_window=? WHERE id=?",
            (new_start.isoformat(), new_count, teacher_id),
        )
        conn.commit()
        return True
    except sqlite3.OperationalError as e:
        # BEGIN IMMEDIATE 競爭失敗或其他 DB 異常 → fail open，避免阻塞主流程
        logger.warning("Teacher %d RPM consume 失敗（fail open）：%s", teacher_id, e)
        try:
            conn.rollback()
        except sqlite3.OperationalError:
            pass
        return True


def _mark_transient_backoff(
    conn: sqlite3.Connection, teacher_id: int, retry_after_seconds: int,
) -> None:
    """設定短暫回退結束時間（RPM 超限後使用，不動每日配額標記）"""
    until = datetime.now(timezone.utc) + timedelta(seconds=max(retry_after_seconds, 1))
    conn.execute(
        "UPDATE teachers SET transient_backoff_until=? WHERE id=?",
        (until.isoformat(), teacher_id),
    )
    conn.commit()
    logger.info(
        "Teacher %d 短暫回退 %ds（至 %s）",
        teacher_id, retry_after_seconds, until.isoformat(),
    )


def _parse_google_429(body_bytes: bytes) -> tuple[str, int]:
    """
    解析 Google Gemini 429 回應體，回傳 (kind, retry_after_seconds)。

    kind: 'day'   — QuotaFailure.quotaId 含 'PerDay' 或 retryDelay >= 3600
          'minute'— QuotaFailure.quotaId 含 'PerMinute' 或 retryDelay < 3600
          'minute'為解析失敗時的保守預設（短回退較安全，誤判為 day 會封鎖整天）
    """
    kind = "unknown"
    retry = 60
    try:
        data = json.loads(body_bytes)
        for d in data.get("error", {}).get("details", []):
            t = d.get("@type", "")
            if "QuotaFailure" in t:
                for v in d.get("violations", []):
                    qid = v.get("quotaId", "")
                    if "PerDay" in qid or "PerDay" in v.get("quotaMetric", ""):
                        kind = "day"
                        break
                    if "PerMinute" in qid:
                        kind = "minute"
            elif "RetryInfo" in t:
                delay = d.get("retryDelay", "60s")
                if isinstance(delay, str):
                    if delay.endswith("s") and delay[:-1].replace(".", "").isdigit():
                        retry = int(float(delay[:-1]))
                    elif delay.endswith("m") and delay[:-1].isdigit():
                        retry = int(delay[:-1]) * 60
    except (json.JSONDecodeError, KeyError, ValueError):
        pass

    if kind == "unknown":
        kind = "day" if retry >= 3600 else "minute"
    return kind, retry


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

    # PR-B：呼叫前原子搶 RPM slot；搶不到代表本分鐘已用完，跳過
    if not _consume_rpm_slot(conn, teacher):
        _log_usage(conn, teacher["id"], sample_id, 0, 0, "rate_limit_minute")
        return None

    if "generativelanguage.googleapis.com" in teacher["api_base"]:
        # 評分輸出僅 JSON {score, reason}，關掉 thinking 避免 max_output_tokens 被 thinking 吃光
        raw, input_t, output_t, status = _call_gemini_rest(
            api_key, teacher["model_id"], prompt,
            caller_module="teacher_service",
            teacher_id=teacher["id"], sample_id=sample_id,
            disable_thinking=True,
        )
    elif "api.anthropic.com" in teacher["api_base"]:
        raw, input_t, output_t, status = _call_anthropic(
            api_key, teacher["api_base"], teacher["model_id"], prompt,
            caller_module="teacher_service",
            teacher_id=teacher["id"], sample_id=sample_id,
        )
    else:
        # 本地 qwen3 系列 thinking 也吃 num_predict 配額，需留足空間給正文
        # vendor 由 teacher row 帶入（DB 存 'local' / 'mistral' / 'openai'），未設則 fallback
        raw, input_t, output_t, status = _call_openai_compat(
            api_key, teacher["api_base"], teacher["model_id"], prompt,
            max_tokens=2048,
            vendor=_vendor_of(teacher),
            caller_module="teacher_service",
            teacher_id=teacher["id"], sample_id=sample_id,
        )

    # PR-B：429 分流（rate_limit_minute = 短暫回退；rate_limit_day = 整天封鎖）
    # 保留 'quota_exceeded' 作 legacy 別名，視同 day（安全偏保守）
    if status in ("rate_limit_minute",):
        _log_usage(conn, teacher["id"], sample_id, 0, 0, "rate_limit_minute")
        _mark_transient_backoff(conn, teacher["id"], retry_after_seconds=60)
        return None
    if status in ("rate_limit_day", "quota_exceeded"):
        _log_usage(conn, teacher["id"], sample_id, 0, 0, "quota_exceeded")
        _mark_daily_limit_reached(conn, teacher["id"])
        _mark_quota_exhausted(conn, teacher["id"], "daily")
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
    *,
    caller_module: str | None = None,
    teacher_id: int | None = None,
    sample_id: int | None = None,
    disable_thinking: bool = False,
) -> tuple[str | None, int, int, str]:
    """Gemini API 呼叫（thin wrapper → clients.gemini.GeminiClient）。

    回傳 (text, input_tokens, output_tokens, status)；介面與原 REST 版相容。

    例外不吞，讓 AIPermanentError / AITransientError 往上冒，達成整批熔斷
    （呼叫端 multi_judge / score_pending_samples / c1 須各自決定 try/except 範圍）。

    caller_module / teacher_id / sample_id 會寫入 ai_api_call_logs，便於追溯來源。
    """
    # 延遲 import，避免循環依賴與啟動成本
    from clients.gemini import GeminiClient

    return GeminiClient(api_key).generate(
        model_id=model_id,
        prompt=prompt,
        max_tokens=max_tokens,
        force_json=force_json,
        caller_module=caller_module,
        teacher_id=teacher_id,
        sample_id=sample_id,
        disable_thinking=disable_thinking,
    )


def _call_openai_compat(
    api_key: str,
    api_base: str,
    model_id: str,
    prompt: str,
    max_tokens: int = 150,
    *,
    vendor: str | None = None,
    caller_module: str | None = None,
    teacher_id: int | None = None,
    sample_id: int | None = None,
) -> tuple[str | None, int, int, str]:
    """OpenAI-compatible 端點呼叫（thin wrapper → clients.openai_compat.OpenAICompatClient）。

    source_type 由 client 依 api_base 自動判定（localhost / *.local → local，其餘 remote）。
    vendor 由呼叫端依 teacher 欄位帶入（'local' / 'mistral' / 'openai' ...）。
    """
    from clients.openai_compat import OpenAICompatClient

    return OpenAICompatClient(api_key, api_base, vendor=vendor).generate(
        model_id=model_id,
        prompt=prompt,
        max_tokens=max_tokens,
        caller_module=caller_module,
        teacher_id=teacher_id,
        sample_id=sample_id,
    )


def _call_anthropic(
    api_key: str,
    api_base: str,
    model_id: str,
    prompt: str,
    max_tokens: int = 150,
    effort: str = "medium",
    *,
    caller_module: str | None = None,
    teacher_id: int | None = None,
    sample_id: int | None = None,
) -> tuple[str | None, int, int, str]:
    """Anthropic Messages API 呼叫（thin wrapper → clients.anthropic.AnthropicClient）。

    effort 預設 medium（Sonnet 4.6 官方推薦的成本/品質平衡點，API 預設為 high）。
    例外（AIPermanentError / AITransientError）不吞，讓呼叫端決定整批熔斷範圍。
    """
    from clients.anthropic import AnthropicClient

    return AnthropicClient(api_key, api_base).generate(
        model_id=model_id,
        prompt=prompt,
        max_tokens=max_tokens,
        effort=effort,
        caller_module=caller_module,
        teacher_id=teacher_id,
        sample_id=sample_id,
    )


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
        return _call_gemini_rest(
            api_key, teacher["model_id"], prompt, force_json=False, max_tokens=200,
            caller_module="teacher_service.call_teacher_for_test", teacher_id=teacher["id"],
        )
    elif "api.anthropic.com" in teacher["api_base"]:
        return _call_anthropic(
            api_key, teacher["api_base"], teacher["model_id"], prompt, max_tokens=200,
            caller_module="teacher_service.call_teacher_for_test", teacher_id=teacher["id"],
        )
    else:
        return _call_openai_compat(
            api_key, teacher["api_base"], teacher["model_id"], prompt, max_tokens=200,
            vendor=_vendor_of(teacher),
            caller_module="teacher_service.call_teacher_for_test", teacher_id=teacher["id"],
        )
