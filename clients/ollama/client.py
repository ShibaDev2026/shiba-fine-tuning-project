"""Ollama 本地 AI API 共用呼叫 client。

特性：
- 本地服務無 API Key、無配額、無 RPM 限制；source_type='local' 寫入 ai_api_call_logs
- 錯誤分類三類（不同於 remote）：
    PERMANENT — local_model_not_found（HTTP 404，模型未 pull）
    TRANSIENT — local_service_unavailable（連線拒絕：Ollama 未啟動）
    PERMANENT — local_generation_empty（HTTP 200 但 response 欄位為空字串）
- TRANSIENT 重試 1 次（中間 sleep 10s），仍失敗則 raise AITransientError + 告警
- PERMANENT 立即 raise AIPermanentError + 告警，呼叫端 except 後負責整批熔斷
- 不設 HTTP timeout：qwen3 thinking mode 單筆可達 60-180s，截斷會無法寫 log
- 每次呼叫（含每次 retry）都寫 ai_api_call_logs，成功失敗都記
"""

from __future__ import annotations

import json
import logging
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

# 為了能直接 import 根目錄的 shiba_alert（與 gemini/client.py 一致）
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

# Ollama 預設本地端點
_DEFAULT_HOST = "http://localhost:11434"


def _now_iso() -> str:
    """UTC ISO8601 含毫秒"""
    return datetime.now(timezone.utc).isoformat()


class OllamaClient:
    """Ollama 本地 API 共用 client。

    用法：
        client = OllamaClient()
        text, in_t, out_t, status = client.generate(
            model_id="qwen3:30b-a3b",
            prompt="...",
            max_tokens=200,
            caller_module="c2_e2e_evaluation.generate",
        )
    """

    VENDOR = "ollama"
    SOURCE_TYPE = "local"

    def __init__(self, host: str = _DEFAULT_HOST) -> None:
        self._host = host.rstrip("/")
        self._endpoint = f"{self._host}/api/generate"

    # ── 對外介面 ────────────────────────────────────────────────────────
    def generate(
        self,
        model_id: str,
        prompt: str,
        max_tokens: int = 2048,
        temperature: float = 0.1,
        *,
        caller_module: str | None = None,
        teacher_id: int | None = None,
        sample_id: int | None = None,
    ) -> tuple[str | None, int, int, str]:
        """呼叫本地 Ollama 生成內容。回傳 (text, input_tokens, output_tokens, status)。

        status 可能值：
          - "success"

        失敗時 raise：
          - AIPermanentError：404 model_not_found / 空回應（呼叫端應整批熔斷）
          - AITransientError：連線拒絕重試 1 次仍失敗（呼叫端應整批熔斷）

        max_tokens 預設 2048：qwen3 thinking mode 也吃 num_predict 配額；
        設太小會導致 response 欄位空字串。
        """
        log_ctx = {
            "caller_module": caller_module,
            "teacher_id": teacher_id,
            "sample_id": sample_id,
        }

        try:
            return self._invoke_once(model_id, prompt, max_tokens, temperature, log_ctx)
        except _RetryableConnectionError as e:
            last_error = e

        for attempt_idx, delay in enumerate(TRANSIENT_RETRY_BACKOFF_SECONDS, start=1):
            logger.warning(
                "Ollama 連線拒絕（第 %d/%d 次重試前等 %ds）host=%s model=%s",
                attempt_idx, len(TRANSIENT_RETRY_BACKOFF_SECONDS),
                delay, self._host, model_id,
            )
            time.sleep(delay)
            try:
                return self._invoke_once(model_id, prompt, max_tokens, temperature, log_ctx)
            except _RetryableConnectionError as e:
                last_error = e

        msg = f"重試 {len(TRANSIENT_RETRY_BACKOFF_SECONDS)} 次仍連線拒絕：{last_error.message}"
        self._raise_transient(model_id, msg, code=None)
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
        body = json.dumps({
            "model": model_id,
            "prompt": prompt,
            "stream": False,
            "options": {
                # thinking tokens 也計入 num_predict，需留足空間給正文
                "num_predict": max(max_tokens, 2048),
                "temperature": temperature,
            },
        }).encode()

        req = urllib.request.Request(
            self._endpoint,
            data=body,
            headers={"Content-Type": "application/json"},
        )

        sent_at = _now_iso()
        sent_ts = time.perf_counter()

        try:
            # 本地服務不設 timeout：thinking mode 可達 60-180s，截斷會 kill 正常請求且無 log
            with urllib.request.urlopen(req, timeout=None) as resp:
                raw = resp.read()
                http_status = resp.status
        except urllib.error.HTTPError as e:
            received_at = _now_iso()
            latency_ms = int((time.perf_counter() - sent_ts) * 1000)
            if e.code == 404:
                # 模型未 pull：永久錯誤
                self._write_log(
                    api_base=self._host, model_id=model_id, prompt=prompt,
                    response_text=None, input_tokens=0, output_tokens=0,
                    http_status=404, status="permanent_error",
                    error_category="local_model_not_found",
                    error_message=f"模型未 pull：{model_id}",
                    sent_at=sent_at, received_at=received_at, latency_ms=latency_ms,
                    log_ctx=log_ctx,
                )
                self._raise_permanent(model_id, f"模型未 pull：{model_id}", 404)
            # 其他 HTTPError 視為永久錯誤
            self._write_log(
                api_base=self._host, model_id=model_id, prompt=prompt,
                response_text=None, input_tokens=0, output_tokens=0,
                http_status=e.code, status="permanent_error",
                error_category="local_http_error",
                error_message=str(e),
                sent_at=sent_at, received_at=received_at, latency_ms=latency_ms,
                log_ctx=log_ctx,
            )
            self._raise_permanent(model_id, f"HTTP {e.code}: {e}", e.code)
        except urllib.error.URLError as e:
            received_at = _now_iso()
            latency_ms = int((time.perf_counter() - sent_ts) * 1000)
            # 連線拒絕 / DNS 解析失敗：先寫 log，再丟給上層 retry-once
            self._write_log(
                api_base=self._host, model_id=model_id, prompt=prompt,
                response_text=None, input_tokens=0, output_tokens=0,
                http_status=None, status="transient_error",
                error_category="local_service_unavailable",
                error_message=f"Ollama 服務未啟動或無法連線：{e.reason}",
                sent_at=sent_at, received_at=received_at, latency_ms=latency_ms,
                log_ctx=log_ctx,
            )
            raise _RetryableConnectionError(message=str(e.reason)) from e
        except Exception as e:
            received_at = _now_iso()
            latency_ms = int((time.perf_counter() - sent_ts) * 1000)
            # 未知例外保守視為永久錯誤
            self._write_log(
                api_base=self._host, model_id=model_id, prompt=prompt,
                response_text=None, input_tokens=0, output_tokens=0,
                http_status=None, status="permanent_error",
                error_category="local_unknown",
                error_message=f"未知例外：{type(e).__name__}: {e}",
                sent_at=sent_at, received_at=received_at, latency_ms=latency_ms,
                log_ctx=log_ctx,
            )
            self._raise_permanent(model_id, f"未知例外：{type(e).__name__}: {e}", None)

        # 成功路徑（HTTP 200，但 response 內容仍需檢查是否為空）
        received_at = _now_iso()
        latency_ms = int((time.perf_counter() - sent_ts) * 1000)
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            self._write_log(
                api_base=self._host, model_id=model_id, prompt=prompt,
                response_text=raw.decode(errors="replace")[:500] if raw else None,
                input_tokens=0, output_tokens=0,
                http_status=http_status, status="permanent_error",
                error_category="local_invalid_json",
                error_message=f"回應非 JSON：{e}",
                sent_at=sent_at, received_at=received_at, latency_ms=latency_ms,
                log_ctx=log_ctx,
            )
            self._raise_permanent(model_id, f"回應非 JSON：{e}", http_status)

        text = (data.get("response") or "").strip()
        input_t = int(data.get("prompt_eval_count") or 0)
        output_t = int(data.get("eval_count") or 0)
        done_reason = data.get("done_reason", "")

        if not text:
            # 空回應視為永久錯誤：可能是 num_predict 被 thinking 耗盡，或模型異常
            # 雖然語意上更接近「資料品質」，但呼叫端應整批熔斷（連續空回應沒意義）
            self._write_log(
                api_base=self._host, model_id=model_id, prompt=prompt,
                response_text="",
                input_tokens=input_t, output_tokens=output_t,
                http_status=http_status, status="permanent_error",
                error_category="local_generation_empty",
                error_message=f"response 欄位為空字串（done_reason={done_reason}）",
                sent_at=sent_at, received_at=received_at, latency_ms=latency_ms,
                log_ctx=log_ctx,
            )
            self._raise_permanent(
                model_id,
                f"response 空字串（done_reason={done_reason}，可能 num_predict 被 thinking 耗盡）",
                http_status,
            )

        # 成功
        self._write_log(
            api_base=self._host, model_id=model_id, prompt=prompt,
            response_text=text,
            input_tokens=input_t, output_tokens=output_t,
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
            f"Ollama 永久錯誤 model={model_id} code={code}: {message}",
            context={"vendor": self.VENDOR, "model_id": model_id, "code": code,
                     "source_type": self.SOURCE_TYPE},
        )
        raise AIPermanentError(self.VENDOR, model_id, message, status_code=code)

    def _raise_transient(self, model_id: str, message: str, code: int | None) -> None:
        send_alert(
            "ai_transient_failure",
            f"Ollama 暫態錯誤（重試 1 次仍失敗）model={model_id}: {message}",
            context={"vendor": self.VENDOR, "model_id": model_id, "code": code,
                     "source_type": self.SOURCE_TYPE},
        )
        raise AITransientError(self.VENDOR, model_id, message, status_code=code)


class _RetryableConnectionError(Exception):
    """內部：將連線拒絕等暫態錯誤包裝後丟給 generate() 統一處理重試。"""

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)
