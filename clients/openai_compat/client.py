"""OpenAI-compatible 端點共用 client（Ollama /v1 / Mistral / OpenAI 等）。

特性（與 clients/gemini、clients/anthropic 一致）：
- 模型 id 由呼叫端參數帶入
- 錯誤分類：QUOTA（429）/ PERMANENT（4xx 非 429 + 未知例外）/ TRANSIENT（連線層 / 5xx 視為暫態）
- TRANSIENT 重試 1 次（sleep 10s），仍失敗則 raise AITransientError + 告警
- PERMANENT 立即 raise AIPermanentError + 告警
- QUOTA 回傳 `rate_limit_minute`（OpenAI-compat 端點 429 通常是短暫，scheduler 退避）
- source_type 依 api_base 自動判斷：localhost/127.0.0.1/*.local → 'local'；否則 'remote'
- 每次呼叫都寫 ai_api_call_logs

為何不直接讓呼叫端用 openai SDK：避免每個 vendor 重複處理 log/錯誤分類；
也讓 Ollama 走 /v1 與 OpenAI 真實 API 共用同一條治理路徑。
"""

from __future__ import annotations

import logging
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from shiba_alert import send_alert  # noqa: E402

from clients.api_log import log_api_call  # noqa: E402
from clients.base import (  # noqa: E402
    TRANSIENT_RETRY_BACKOFF_SECONDS,
    AIPermanentError,
    AITransientError,
)

logger = logging.getLogger(__name__)

# 判定 source_type='local' 的 host pattern：localhost / 127.0.0.1 / host.docker.internal / *.local
_LOCAL_HOST_RE = re.compile(
    r"://(localhost|127\.0\.0\.1|0\.0\.0\.0|host\.docker\.internal|[^/:]+\.local)(:|/|$)",
    re.IGNORECASE,
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _detect_source_type(api_base: str) -> str:
    """根據 api_base 判斷 source_type；本地端點走 'local'，其餘 'remote'。"""
    return "local" if _LOCAL_HOST_RE.search(api_base or "") else "remote"


def _apply_thinking_control(prompt: str, vendor: str | None, disable_thinking: bool) -> str:
    """關閉本地裁判 thinking 以穩定吐 JSON。
    Qwen 系用 /no_think 軟開關；GLM 走 reasoning_content 分流、gemma 無強制 thinking，皆不注入。"""
    if disable_thinking and vendor and "qwen" in vendor.lower():
        return f"{prompt}\n/no_think"
    return prompt


class OpenAICompatClient:
    """OpenAI-compatible chat.completions 端點 client。

    用法：
        client = OpenAICompatClient(api_key, api_base="http://localhost:11434/v1")
        text, in_t, out_t, status = client.generate(
            model_id="qwen3.6:35b-a3b-nvfp4",
            prompt="...",
            max_tokens=2048,
            caller_module="teacher_service",
        )
    """

    DEFAULT_VENDOR = "openai_compat"

    def __init__(
        self,
        api_key: str,
        api_base: str,
        *,
        vendor: str | None = None,
    ) -> None:
        self._api_key = api_key
        self._api_base = api_base
        # vendor 由呼叫端覆寫（如 'local' / 'mistral' / 'openai'），不指定時 fallback
        self._vendor = vendor or self.DEFAULT_VENDOR
        self._source_type = _detect_source_type(api_base)

    # ── 對外介面 ────────────────────────────────────────────────────────
    def generate(
        self,
        model_id: str,
        prompt: str,
        max_tokens: int = 150,
        *,
        temperature: float = 0.0,
        disable_thinking: bool = False,
        caller_module: str | None = None,
        teacher_id: int | None = None,
        sample_id: int | None = None,
    ) -> tuple[str | None, int, int, str]:
        """呼叫 chat.completions 端點生成內容。

        回傳 (text, input_tokens, output_tokens, status)；status:
          - "success"
          - "rate_limit_minute"（429，OpenAI-compat 多為短暫；長期配額靠 daily_request_limit 觸發）

        失敗時 raise AIPermanentError / AITransientError（呼叫端整批熔斷）。
        """
        # Qwen 系注入 /no_think 使 thinking 關閉，確保純 JSON 輸出
        prompt = _apply_thinking_control(prompt, self._vendor, disable_thinking)
        log_ctx = {
            "caller_module": caller_module,
            "teacher_id": teacher_id,
            "sample_id": sample_id,
        }

        try:
            return self._invoke_once(model_id, prompt, max_tokens, temperature, log_ctx)
        except _RetryableServerError as e:
            last_error = e

        for attempt_idx, delay in enumerate(TRANSIENT_RETRY_BACKOFF_SECONDS, start=1):
            logger.warning(
                "OpenAI-compat 暫態錯誤（第 %d/%d 次重試前等 %ds）vendor=%s model=%s code=%s",
                attempt_idx, len(TRANSIENT_RETRY_BACKOFF_SECONDS),
                delay, self._vendor, model_id, last_error.code,
            )
            time.sleep(delay)
            try:
                return self._invoke_once(model_id, prompt, max_tokens, temperature, log_ctx)
            except _RetryableServerError as e:
                last_error = e

        msg = f"重試 {len(TRANSIENT_RETRY_BACKOFF_SECONDS)} 次仍失敗：{last_error.message}"
        self._raise_transient(model_id, msg, last_error.code)
        raise AssertionError("unreachable")

    # ── 內部：一次嘗試 ──────────────────────────────────────────────────
    def _invoke_once(
        self,
        model_id: str,
        prompt: str,
        max_tokens: int,
        temperature: float,
        log_ctx: dict,
    ) -> tuple[str | None, int, int, str]:
        # 延遲 import，避免未安裝 openai 的環境匯入 clients package 就炸
        from openai import (
            APIConnectionError,
            APIError,
            APIStatusError,
            OpenAI,
            RateLimitError,
        )

        client = OpenAI(api_key=self._api_key, base_url=self._api_base)

        sent_at = _now_iso()
        sent_ts = time.perf_counter()

        try:
            resp = client.chat.completions.create(
                model=model_id,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=max_tokens,
                temperature=temperature,
            )
        except RateLimitError as e:
            received_at = _now_iso()
            latency_ms = int((time.perf_counter() - sent_ts) * 1000)
            # OpenAI-compat 端點 429 統一視為短暫 RPM 等級；若實際是 daily，
            # 下次重試仍會再次 429，最終透過 daily_request_limit 上限觸發 daily 標記
            self._write_log(
                model_id=model_id, prompt=prompt,
                response_text=None, input_tokens=0, output_tokens=0,
                http_status=429, status="rate_limit_minute",
                error_category="quota", error_message=str(e),
                sent_at=sent_at, received_at=received_at, latency_ms=latency_ms,
                log_ctx=log_ctx,
            )
            return None, 0, 0, "rate_limit_minute"
        except APIConnectionError as e:
            # 連線層錯誤（DNS / 拒絕 / 中斷）→ 暫態，走 retry-once
            received_at = _now_iso()
            latency_ms = int((time.perf_counter() - sent_ts) * 1000)
            self._write_log(
                model_id=model_id, prompt=prompt,
                response_text=None, input_tokens=0, output_tokens=0,
                http_status=None, status="transient_error",
                error_category="transient",
                error_message=f"APIConnectionError: {e}",
                sent_at=sent_at, received_at=received_at, latency_ms=latency_ms,
                log_ctx=log_ctx,
            )
            raise _RetryableServerError(code=0, message=str(e)) from e
        except APIStatusError as e:
            received_at = _now_iso()
            latency_ms = int((time.perf_counter() - sent_ts) * 1000)
            code = getattr(e, "status_code", None) or 0
            if 500 <= code < 600:
                # 5xx → 暫態，走 retry-once
                self._write_log(
                    model_id=model_id, prompt=prompt,
                    response_text=None, input_tokens=0, output_tokens=0,
                    http_status=code, status="transient_error",
                    error_category="transient", error_message=str(e),
                    sent_at=sent_at, received_at=received_at, latency_ms=latency_ms,
                    log_ctx=log_ctx,
                )
                raise _RetryableServerError(code=code, message=str(e)) from e
            # 4xx 非 429 → 永久錯誤
            self._write_log(
                model_id=model_id, prompt=prompt,
                response_text=None, input_tokens=0, output_tokens=0,
                http_status=code, status="permanent_error",
                error_category="permanent", error_message=str(e),
                sent_at=sent_at, received_at=received_at, latency_ms=latency_ms,
                log_ctx=log_ctx,
            )
            self._raise_permanent(model_id, str(e), code)
        except APIError as e:
            # APIStatusError 之外的 APIError（極少見）→ 永久錯誤保守處理
            received_at = _now_iso()
            latency_ms = int((time.perf_counter() - sent_ts) * 1000)
            self._write_log(
                model_id=model_id, prompt=prompt,
                response_text=None, input_tokens=0, output_tokens=0,
                http_status=None, status="permanent_error",
                error_category="permanent",
                error_message=f"APIError: {type(e).__name__}: {e}",
                sent_at=sent_at, received_at=received_at, latency_ms=latency_ms,
                log_ctx=log_ctx,
            )
            self._raise_permanent(model_id, f"APIError: {e}", None)
        except Exception as e:
            received_at = _now_iso()
            latency_ms = int((time.perf_counter() - sent_ts) * 1000)
            self._write_log(
                model_id=model_id, prompt=prompt,
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
            text = (resp.choices[0].message.content or "").strip()
            usage = resp.usage
            input_t = usage.prompt_tokens if usage else 0
            output_t = usage.completion_tokens if usage else 0
        except (AttributeError, IndexError) as e:
            self._write_log(
                model_id=model_id, prompt=prompt,
                response_text=None, input_tokens=0, output_tokens=0,
                http_status=200, status="permanent_error",
                error_category="permanent",
                error_message=f"回應結構解析失敗：{type(e).__name__}: {e}",
                sent_at=sent_at, received_at=received_at, latency_ms=latency_ms,
                log_ctx=log_ctx,
            )
            self._raise_permanent(model_id, f"回應結構解析失敗：{e}", 200)

        self._write_log(
            model_id=model_id, prompt=prompt,
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
        model_id: str, prompt: str,
        response_text: str | None, input_tokens: int, output_tokens: int,
        http_status: int | None, status: str,
        error_category: str | None, error_message: str | None,
        sent_at: str, received_at: str | None, latency_ms: int | None,
        log_ctx: dict,
    ) -> None:
        log_api_call(
            vendor=self._vendor,
            source_type=self._source_type,
            api_base=self._api_base, model_id=model_id,
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
            f"OpenAI-compat 永久錯誤 vendor={self._vendor} model={model_id} "
            f"code={code}: {message}",
            context={
                "vendor": self._vendor,
                "model_id": model_id,
                "code": code,
                "api_base": self._api_base,
            },
        )
        raise AIPermanentError(self._vendor, model_id, message, status_code=code)

    def _raise_transient(self, model_id: str, message: str, code: int | None) -> None:
        send_alert(
            "ai_transient_failure",
            f"OpenAI-compat 暫態錯誤（重試 1 次仍失敗）vendor={self._vendor} "
            f"model={model_id} code={code}: {message}",
            context={
                "vendor": self._vendor,
                "model_id": model_id,
                "code": code,
                "api_base": self._api_base,
            },
        )
        raise AITransientError(self._vendor, model_id, message, status_code=code)


class _RetryableServerError(Exception):
    """內部：將連線錯誤 / 5xx 包裝後丟給 generate() 統一處理重試。"""

    def __init__(self, code: int, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")
