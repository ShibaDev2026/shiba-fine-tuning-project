"""Gemini API 共用呼叫 client。

特性：
- 用 `google-genai` 官方 SDK，模型 id 由呼叫端透過參數帶入（不寫死）。
- 錯誤分類三類：QUOTA（429）/ PERMANENT（4xx 非 429）/ TRANSIENT（5xx）。
- TRANSIENT 重試 1 次（中間 sleep 10s），仍失敗則 raise AITransientError + 告警。
- PERMANENT 立即 raise AIPermanentError + 告警，呼叫端 except 後負責整批熔斷。
- QUOTA 走 PR-B 介面：回傳 status 字串 `rate_limit_minute` / `rate_limit_day`，scheduler 處理退避。
- 每次呼叫（含每次 retry）都寫 `ai_api_call_logs`，成功失敗都記。
"""

from __future__ import annotations

import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# 為了能直接 import 根目錄的 shiba_alert（與 teacher_service.py 內 import 風格一致）
_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from shiba_alert import send_alert  # noqa: E402

from clients.api_log import log_api_call  # noqa: E402
from clients.base import AIPermanentError, AITransientError  # noqa: E402

logger = logging.getLogger(__name__)

# 失敗重試前固定 sleep 10s（避開伺服器尚未恢復就連打）
_TRANSIENT_RETRY_SLEEP_SECONDS = 10

# Gemini Developer API endpoint pattern（用於 ai_api_call_logs.api_base 紀錄）
_GEMINI_API_BASE_PATTERN = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model_id}:generateContent"
)


def _now_iso() -> str:
    """UTC ISO8601 含毫秒"""
    return datetime.now(timezone.utc).isoformat()


class GeminiClient:
    """Gemini API 共用 client。

    用法：
        client = GeminiClient(api_key)
        text, in_t, out_t, status = client.generate(
            model_id="gemini-2.5-flash-lite",
            prompt="...",
            max_tokens=200,
            force_json=False,
            caller_module="c1_generate_answers",
        )
    """

    VENDOR = "gemini"
    SOURCE_TYPE = "remote"

    def __init__(self, api_key: str) -> None:
        # 延遲 import，避免未安裝 SDK 的環境匯入 clients package 就炸
        from google import genai

        self._client = genai.Client(api_key=api_key)

    # ── 對外介面 ────────────────────────────────────────────────────────
    def generate(
        self,
        model_id: str,
        prompt: str,
        max_tokens: int = 150,
        force_json: bool = True,
        *,
        caller_module: str | None = None,
        teacher_id: int | None = None,
        sample_id: int | None = None,
    ) -> tuple[str | None, int, int, str]:
        """呼叫 Gemini 生成內容。回傳 (text, input_tokens, output_tokens, status)。

        status 可能值：
          - "success"
          - "rate_limit_minute" / "rate_limit_day"（429，沿用 PR-B 介面）

        失敗時（非 429）會 raise：
          - AIPermanentError：4xx 非 429（呼叫端應整批熔斷）
          - AITransientError：5xx 連續重試 1 次仍失敗（呼叫端應整批熔斷）

        每次嘗試（含重試）都會寫 ai_api_call_logs。
        """
        log_ctx = {
            "caller_module": caller_module,
            "teacher_id": teacher_id,
            "sample_id": sample_id,
        }

        try:
            return self._invoke_once(model_id, prompt, max_tokens, force_json, log_ctx)
        except _RetryableServerError as e:
            logger.warning(
                "Gemini 5xx 暫態錯誤（將於 %ds 後重試 1 次）model=%s code=%s",
                _TRANSIENT_RETRY_SLEEP_SECONDS, model_id, e.code,
            )
            time.sleep(_TRANSIENT_RETRY_SLEEP_SECONDS)
            try:
                return self._invoke_once(model_id, prompt, max_tokens, force_json, log_ctx)
            except _RetryableServerError as e2:
                msg = f"5xx 重試 1 次仍失敗：{e2.message}"
                self._raise_transient(model_id, msg, e2.code)
            raise AssertionError("unreachable")

    # ── 內部：一次嘗試 ──────────────────────────────────────────────────
    def _invoke_once(
        self,
        model_id: str,
        prompt: str,
        max_tokens: int,
        force_json: bool,
        log_ctx: dict,
    ) -> tuple[str | None, int, int, str]:
        from google.genai import errors as genai_errors
        from google.genai import types as genai_types

        config_kwargs: dict[str, Any] = {
            "temperature": 0.1,
            "max_output_tokens": max_tokens,
        }
        if force_json:
            config_kwargs["response_mime_type"] = "application/json"

        api_base = _GEMINI_API_BASE_PATTERN.format(model_id=model_id)
        sent_at = _now_iso()
        sent_ts = time.perf_counter()

        try:
            response = self._client.models.generate_content(
                model=model_id,
                contents=prompt,
                config=genai_types.GenerateContentConfig(**config_kwargs),
            )
        except genai_errors.ClientError as e:
            received_at = _now_iso()
            latency_ms = int((time.perf_counter() - sent_ts) * 1000)
            if e.code == 429:
                # 429 不熔斷：照 PR-B 寫 rate_limit_* 狀態
                kind, retry = _parse_quota_details(e.details)
                logger.info(
                    "Gemini 429 model=%s kind=%s retry_after=%ds",
                    model_id, kind, retry,
                )
                status_str = "rate_limit_day" if kind == "day" else "rate_limit_minute"
                self._write_log(
                    api_base=api_base, model_id=model_id, prompt=prompt,
                    response_text=None, input_tokens=0, output_tokens=0,
                    http_status=429, status=status_str,
                    error_category="quota", error_message=e.message or str(e),
                    sent_at=sent_at, received_at=received_at, latency_ms=latency_ms,
                    log_ctx=log_ctx,
                )
                return None, 0, 0, status_str
            # 4xx 非 429 → 永久錯誤
            self._write_log(
                api_base=api_base, model_id=model_id, prompt=prompt,
                response_text=None, input_tokens=0, output_tokens=0,
                http_status=e.code, status="permanent_error",
                error_category="permanent", error_message=e.message or str(e),
                sent_at=sent_at, received_at=received_at, latency_ms=latency_ms,
                log_ctx=log_ctx,
            )
            self._raise_permanent(model_id, e.message or str(e), e.code)
        except genai_errors.ServerError as e:
            received_at = _now_iso()
            latency_ms = int((time.perf_counter() - sent_ts) * 1000)
            # 5xx：先寫 log（本次失敗），再丟給上層 retry-once
            self._write_log(
                api_base=api_base, model_id=model_id, prompt=prompt,
                response_text=None, input_tokens=0, output_tokens=0,
                http_status=e.code, status="transient_error",
                error_category="transient", error_message=e.message or str(e),
                sent_at=sent_at, received_at=received_at, latency_ms=latency_ms,
                log_ctx=log_ctx,
            )
            raise _RetryableServerError(code=e.code, message=e.message or str(e)) from e
        except Exception as e:
            received_at = _now_iso()
            latency_ms = int((time.perf_counter() - sent_ts) * 1000)
            # 未知例外保守視為永久錯誤
            self._write_log(
                api_base=api_base, model_id=model_id, prompt=prompt,
                response_text=None, input_tokens=0, output_tokens=0,
                http_status=None, status="permanent_error",
                error_category="permanent",
                error_message=f"未知例外：{type(e).__name__}: {e}",
                sent_at=sent_at, received_at=received_at, latency_ms=latency_ms,
                log_ctx=log_ctx,
            )
            self._raise_permanent(model_id, f"未知例外：{type(e).__name__}: {e}", None)

        # 成功路徑
        received_at = _now_iso()
        latency_ms = int((time.perf_counter() - sent_ts) * 1000)
        text = (response.text or "").strip() if response.text else ""
        usage = getattr(response, "usage_metadata", None)
        input_t = getattr(usage, "prompt_token_count", 0) or 0
        output_t = getattr(usage, "candidates_token_count", 0) or 0
        self._write_log(
            api_base=api_base, model_id=model_id, prompt=prompt,
            response_text=text, input_tokens=input_t, output_tokens=output_t,
            http_status=200, status="success",
            error_category=None, error_message=None,
            sent_at=sent_at, received_at=received_at, latency_ms=latency_ms,
            log_ctx=log_ctx,
        )
        return text, input_t, output_t, "success"

    # ── 內部：log 寫入 ──────────────────────────────────────────────────
    def _write_log(
        self, *,
        api_base: str, model_id: str, prompt: str,
        response_text: str | None, input_tokens: int, output_tokens: int,
        http_status: int | None, status: str,
        error_category: str | None, error_message: str | None,
        sent_at: str, received_at: str | None, latency_ms: int | None,
        log_ctx: dict,
    ) -> None:
        log_api_call(
            vendor=self.VENDOR,
            source_type=self.SOURCE_TYPE,
            api_base=api_base, model_id=model_id,
            request_text=prompt, response_text=response_text,
            input_tokens=input_tokens, output_tokens=output_tokens,
            http_status=http_status, status=status,
            error_category=error_category, error_message=error_message,
            request_sent_at=sent_at, response_received_at=received_at,
            latency_ms=latency_ms,
            **log_ctx,
        )

    # ── 告警 + 例外丟出 ────────────────────────────────────────────────
    def _raise_permanent(self, model_id: str, message: str, code: int | None) -> None:
        send_alert(
            "ai_permanent_failure",
            f"Gemini 永久錯誤 model={model_id} code={code}: {message}",
            context={"vendor": self.VENDOR, "model_id": model_id, "code": code},
        )
        raise AIPermanentError(self.VENDOR, model_id, message, status_code=code)

    def _raise_transient(self, model_id: str, message: str, code: int | None) -> None:
        send_alert(
            "ai_transient_failure",
            f"Gemini 暫態錯誤（重試 1 次仍失敗）model={model_id} code={code}: {message}",
            context={"vendor": self.VENDOR, "model_id": model_id, "code": code},
        )
        raise AITransientError(self.VENDOR, model_id, message, status_code=code)


class _RetryableServerError(Exception):
    """內部：將 SDK ServerError 包裝後丟給 generate() 統一處理重試。"""

    def __init__(self, code: int, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


def _parse_quota_details(details: Any) -> tuple[str, int]:
    """從 SDK 提供的 429 error details 解析配額類型與 retry 秒數。

    對齊 teacher_service._parse_google_429 邏輯：
      kind: 'day'    — quotaId 含 'PerDay' 或 retryDelay >= 3600
            'minute' — quotaId 含 'PerMinute' 或 retryDelay < 3600
      失敗時保守視為 'minute'（短回退較安全，誤判為 day 會封鎖整天）
    """
    kind = "unknown"
    retry = 60
    try:
        error = details.get("error", {}) if isinstance(details, dict) else {}
        for d in error.get("details", []):
            t = d.get("@type", "")
            if "QuotaFailure" in t:
                for v in d.get("violations", []):
                    qid = v.get("quotaId", "")
                    metric = v.get("quotaMetric", "")
                    if "PerDay" in qid or "PerDay" in metric:
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
    except (AttributeError, KeyError, ValueError, TypeError):
        pass

    if kind == "unknown":
        kind = "day" if retry >= 3600 else "minute"
    return kind, retry
