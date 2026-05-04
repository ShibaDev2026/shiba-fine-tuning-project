"""
shiba_alert.py — 跨層集中告警出口（B7 架構）。

由 background.py (Layer 2) 與 trigger_policy.py (Layer 3) 共用。
所有告警至此統一發送：
  - CRITICAL log（便於 grep / CloudWatch 監控）
  - 可選 webhook（SHIBA_ALERT_WEBHOOK env）
"""

import json
import logging
import os
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


def send_alert(alert_type: str, message: str, context: dict | None = None) -> None:
    """
    B7 集中式 alert 出口。
    - 無論是否有 webhook，都以 CRITICAL 等級寫入 log（方便 grep / CloudWatch）。
    - 若環境變數 SHIBA_ALERT_WEBHOOK 已設，POST JSON 至該 URL；失敗不拋異常。
    """
    payload = {
        "alert_type": alert_type,
        "message": message,
        "context": context or {},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    logger.critical(
        "[SHIBA-ALERT] type=%s msg=%s ctx=%s",
        alert_type, message, json.dumps(context or {}),
    )

    webhook_url = os.environ.get("SHIBA_ALERT_WEBHOOK", "").strip()
    if not webhook_url:
        return

    try:
        import urllib.request
        body = json.dumps(payload).encode()
        req = urllib.request.Request(
            webhook_url,
            data=body,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=5):
            pass
    except Exception as e:
        logger.warning("Alert webhook 傳送失敗 url=%s：%s", webhook_url, e)
