"""AI 呼叫共用錯誤分類與基底例外。

為什麼集中在 base：未來 anthropic / openai client 比照同分類，呼叫端用單一 except
即可處理所有 AI 廠商錯誤（達成「整批熔斷」介面一致性）。
"""

from enum import Enum


class AIErrorCategory(str, Enum):
    """AI 呼叫錯誤的三大類別。"""

    PERMANENT = "permanent"   # 4xx 非 429：請求格式錯、無權限、資源不存在 → 立即停 + 告警
    TRANSIENT = "transient"   # 5xx：服務暫態錯誤 → 重試 1 次仍失敗則停 + 告警
    QUOTA = "quota"           # 429：配額相關，由 scheduler / RPM slot 處理，不熔斷


class AIClientError(Exception):
    """AI 呼叫例外基底。

    Attributes:
        category: 錯誤類別（PERMANENT / TRANSIENT / QUOTA）
        vendor:   廠商代號（gemini / anthropic / openai ...）
        model_id: 觸發例外的模型
        status_code: HTTP 狀態碼（若可取得）
        message:  原始錯誤訊息
    """

    def __init__(
        self,
        category: AIErrorCategory,
        vendor: str,
        model_id: str,
        message: str,
        status_code: int | None = None,
    ) -> None:
        self.category = category
        self.vendor = vendor
        self.model_id = model_id
        self.status_code = status_code
        self.message = message
        super().__init__(
            f"[{vendor}:{model_id}] {category.value} "
            f"(http={status_code}): {message}"
        )


class AIPermanentError(AIClientError):
    """永久錯誤：呼叫端應整批熔斷。"""

    def __init__(self, vendor: str, model_id: str, message: str, status_code: int | None = None):
        super().__init__(AIErrorCategory.PERMANENT, vendor, model_id, message, status_code)


class AITransientError(AIClientError):
    """暫態錯誤：經單次重試後仍失敗，呼叫端應整批熔斷。"""

    def __init__(self, vendor: str, model_id: str, message: str, status_code: int | None = None):
        super().__init__(AIErrorCategory.TRANSIENT, vendor, model_id, message, status_code)


class AIQuotaError(AIClientError):
    """配額錯誤：保留為例外類別供未來使用；目前 Gemini client 仍以 status 字串回傳以相容 PR-B 機制。"""

    def __init__(
        self,
        vendor: str,
        model_id: str,
        message: str,
        *,
        kind: str,
        retry_after_seconds: int,
        status_code: int | None = 429,
    ):
        super().__init__(AIErrorCategory.QUOTA, vendor, model_id, message, status_code)
        self.kind = kind  # 'minute' | 'day'
        self.retry_after_seconds = retry_after_seconds


# ── 共用 retry 策略 ────────────────────────────────────────────────────────
# 5xx 暫態錯誤 exponential backoff：每次重試前 sleep 秒數
# 失敗 case 最壞情況多耗 5+15+30+60=110s。
# 觀測 Google 503 spike 有兩種型態：
#   - 秒級 spike：[2,5,10] 即可吸收（C.2 smoke 實測 2s 恢復）
#   - 分鐘級 spike：PT 上班時段 17s backoff 仍會撐不過（C.2 全量第 10 筆觸發）
# 加大到 [5,15,30,60] 提高長 spike 容忍度；首次重試 5s 換掉 2s，
# 對短 spike 多 3s 延遲是可接受成本，換取長 spike 不再頻繁整批熔斷。
# 各 vendor client 共用此常數，確保暫態處理策略一致。
TRANSIENT_RETRY_BACKOFF_SECONDS = [5, 15, 30, 60]
