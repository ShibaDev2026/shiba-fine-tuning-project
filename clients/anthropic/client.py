"""Anthropic Messages API 共用呼叫 client。

特性（與 clients/gemini 一致）：
- 模型 id 由呼叫端參數帶入，不寫死
- 錯誤分類：QUOTA（429）/ PERMANENT（4xx 非 429）/ TRANSIENT（5xx）
- TRANSIENT 重試 1 次（中間 sleep 10s），仍失敗則 raise AITransientError + 告警
- PERMANENT 立即 raise AIPermanentError + 告警，呼叫端 except 後負責整批熔斷
- QUOTA 走 PR-B 介面：回傳 status 字串 `rate_limit_minute` / `rate_limit_day`，scheduler 處理退避
- 每次呼叫（含每次 retry）都寫 `ai_api_call_logs`，成功失敗都記

為何不用官方 anthropic SDK：避免引入額外相依，且 Messages API REST 介面穩定。
"""

from __future__ import annotations

import json
import logging
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

# 與 clients/gemini 相同 import root 風格
_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from shiba_alert import send_alert  # noqa: E402

from clients.api_log import log_api_call  # noqa: E402
from clients.base import AIPermanentError, AITransientError  # noqa: E402

logger = logging.getLogger(__name__)

_TRANSIENT_RETRY_SLEEP_SECONDS = 10

# retry-after 大於此秒數視為長期配額（day），否則短暫（minute）
_LONG_RETRY_THRESHOLD = 300


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class AnthropicClient:
    """Anthropic Messages API 共用 client。

    用法：
        client = AnthropicClient(api_key, api_base="https://api.anthropic.com/v1")
        text, in_t, out_t, status = client.generate(
            model_id="claude-sonnet-4-6",
            prompt="...",
            max_tokens=200,
            caller_module="teacher_service",
        )
    """

    VENDOR = "anthropic"
    SOURCE_TYPE = "remote"

    def __init__(self, api_key: str, api_base: str = "https://api.anthropic.com/v1") -> None:
        self._api_key = api_key
        self._api_base = api_base.rstrip("/")

    # ── 對外介面 ────────────────────────────────────────────────────────
    def generate(
        self,
        model_id: str,
        prompt: str,
        max_tokens: int = 150,
        *,
        effort: str = "medium",
        caller_module: str | None = None,
        teacher_id: int | None = None,
        sample_id: int | None = None,
    ) -> tuple[str | None, int, int, str]:
        """呼叫 Anthropic Messages 端點生成內容。

        回傳 (text, input_tokens, output_tokens, status)；status 可能值：
          - "success"
          - "rate_limit_minute" / "rate_limit_day"（429）

        失敗時（非 429）會 raise AIPermanentError / AITransientError（呼叫端整批熔斷）。

        effort：'low'/'medium'/'high'，Sonnet 4.6 官方推薦 medium 兼顧成本與品質
        （API 預設為 high）。
        """
        log_ctx = {
            "caller_module": caller_module,
            "teacher_id": teacher_id,
            "sample_id": sample_id,
        }

        try:
            return self._invoke_once(model_id, prompt, max_tokens, effort, log_ctx)
        except _RetryableServerError as e:
            logger.warning(
                "Anthropic 5xx 暫態錯誤（將於 %ds 後重試 1 次）model=%s code=%s",
                _TRANSIENT_RETRY_SLEEP_SECONDS, model_id, e.code,
            )
            time.sleep(_TRANSIENT_RETRY_SLEEP_SECONDS)
            try:
                return self._invoke_once(model_id, prompt, max_tokens, effort, log_ctx)
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
        effort: str,
        log_ctx: dict,
    ) -> tuple[str | None, int, int, str]:
        url = f"{self._api_base}/messages"
        body = json.dumps({
            "model": model_id,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.1,
            "output_config": {"effort": effort},
        }).encode()

        req = urllib.request.Request(
            url,
            data=body,
            headers={
                "Content-Type": "application/json",
                "x-api-key": self._api_key,
                "anthropic-version": "2023-06-01",
            },
        )

        sent_at = _now_iso()
        sent_ts = time.perf_counter()

        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                raw = resp.read()
                http_status = resp.status
        except urllib.error.HTTPError as e:
            received_at = _now_iso()
            latency_ms = int((time.perf_counter() - sent_ts) * 1000)
            err_body = ""
            try:
                err_body = e.read().decode("utf-8", errors="replace")
            except Exception:
                pass

            if e.code == 429:
                # 429 不熔斷：解析 retry-after 區分短暫 vs 長期
                kind, retry = _parse_429_retry_after(e)
                logger.info(
                    "Anthropic 429 model=%s kind=%s retry_after=%ds",
                    model_id, kind, retry,
                )
                status_str = "rate_limit_day" if kind == "day" else "rate_limit_minute"
                self._write_log(
                    api_base=url, model_id=model_id, prompt=prompt,
                    response_text=None, input_tokens=0, output_tokens=0,
                    http_status=429, status=status_str,
                    error_category="quota", error_message=err_body or str(e),
                    sent_at=sent_at, received_at=received_at, latency_ms=latency_ms,
                    log_ctx=log_ctx,
                )
                return None, 0, 0, status_str

            if 500 <= e.code < 600:
                # 5xx：寫 log（本次失敗），丟給上層 retry-once
                self._write_log(
                    api_base=url, model_id=model_id, prompt=prompt,
                    response_text=None, input_tokens=0, output_tokens=0,
                    http_status=e.code, status="transient_error",
                    error_category="transient", error_message=err_body or str(e),
                    sent_at=sent_at, received_at=received_at, latency_ms=latency_ms,
                    log_ctx=log_ctx,
                )
                raise _RetryableServerError(code=e.code, message=err_body or str(e)) from e

            # 4xx 非 429 → 永久錯誤
            self._write_log(
                api_base=url, model_id=model_id, prompt=prompt,
                response_text=None, input_tokens=0, output_tokens=0,
                http_status=e.code, status="permanent_error",
                error_category="permanent", error_message=err_body or str(e),
                sent_at=sent_at, received_at=received_at, latency_ms=latency_ms,
                log_ctx=log_ctx,
            )
            self._raise_permanent(model_id, err_body or str(e), e.code)
        except urllib.error.URLError as e:
            # 連線層錯誤（DNS / 拒絕 / 中斷）視為暫態，走 retry-once
            received_at = _now_iso()
            latency_ms = int((time.perf_counter() - sent_ts) * 1000)
            self._write_log(
                api_base=url, model_id=model_id, prompt=prompt,
                response_text=None, input_tokens=0, output_tokens=0,
                http_status=None, status="transient_error",
                error_category="transient", error_message=f"URLError: {e.reason}",
                sent_at=sent_at, received_at=received_at, latency_ms=latency_ms,
                log_ctx=log_ctx,
            )
            raise _RetryableServerError(code=0, message=str(e.reason)) from e
        except Exception as e:
            received_at = _now_iso()
            latency_ms = int((time.perf_counter() - sent_ts) * 1000)
            # 未知例外保守視為永久錯誤
            self._write_log(
                api_base=url, model_id=model_id, prompt=prompt,
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
        try:
            data = json.loads(raw)
            # Messages API 回應 content 是 list[{type, text}]，取所有 text 串接
            text_parts = [
                blk.get("text", "")
                for blk in (data.get("content") or [])
                if blk.get("type") == "text"
            ]
            text = "".join(text_parts).strip()
            usage = data.get("usage", {}) or {}
            input_t = usage.get("input_tokens", 0) or 0
            output_t = usage.get("output_tokens", 0) or 0
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            # 200 但 body 解析失敗 → 視為永久錯誤（送告警）
            self._write_log(
                api_base=url, model_id=model_id, prompt=prompt,
                response_text=raw.decode("utf-8", errors="replace")[:2000],
                input_tokens=0, output_tokens=0,
                http_status=http_status, status="permanent_error",
                error_category="permanent",
                error_message=f"回應解析失敗：{type(e).__name__}: {e}",
                sent_at=sent_at, received_at=received_at, latency_ms=latency_ms,
                log_ctx=log_ctx,
            )
            self._raise_permanent(model_id, f"回應解析失敗：{e}", http_status)

        self._write_log(
            api_base=url, model_id=model_id, prompt=prompt,
            response_text=text, input_tokens=input_t, output_tokens=output_t,
            http_status=http_status, status="success",
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
            f"Anthropic 永久錯誤 model={model_id} code={code}: {message}",
            context={"vendor": self.VENDOR, "model_id": model_id, "code": code},
        )
        raise AIPermanentError(self.VENDOR, model_id, message, status_code=code)

    def _raise_transient(self, model_id: str, message: str, code: int | None) -> None:
        send_alert(
            "ai_transient_failure",
            f"Anthropic 暫態錯誤（重試 1 次仍失敗）model={model_id} code={code}: {message}",
            context={"vendor": self.VENDOR, "model_id": model_id, "code": code},
        )
        raise AITransientError(self.VENDOR, model_id, message, status_code=code)


class _RetryableServerError(Exception):
    """內部：將 5xx / URLError 包裝後丟給 generate() 統一處理重試。"""

    def __init__(self, code: int, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


def _parse_429_retry_after(http_error: urllib.error.HTTPError) -> tuple[str, int]:
    """解析 Anthropic 429 的 retry-after，回傳 (kind, retry_after_seconds)。

    Anthropic 用 HTTP header 傳遞速率資訊：
      retry-after：建議等待秒數
      anthropic-ratelimit-requests-reset / -tokens-reset：UTC 重置時間
    retry >= 300s 視為長期（保守當 day）；否則視為短暫（minute）。
    """
    retry = 60
    try:
        ra = http_error.headers.get("retry-after")
        if ra and ra.isdigit():
            retry = int(ra)
    except (AttributeError, ValueError):
        pass
    kind = "day" if retry >= _LONG_RETRY_THRESHOLD else "minute"
    return kind, retry
