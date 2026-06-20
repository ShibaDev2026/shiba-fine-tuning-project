"""notify.py — macOS 桌面通知（方案 A，osascript）。

side-effect only：找不到 osascript / 執行失敗 / 非 macOS 皆回 False，不冒泡。
首次使用可能需在「系統設定→通知」允許 Script Editor，否則通知靜默不顯示（非本模組可控）。
"""
from __future__ import annotations

import logging
import shutil
import subprocess

_logger = logging.getLogger(__name__)


def _escape(s: str) -> str:
    """AppleScript 字串轉義：反斜線、雙引號；換行收斂成空白（通知為單行）。"""
    s = (s or "").replace("\\", "\\\\").replace('"', '\\"')
    return " ".join(s.split())


def _notify_args(title: str, body: str, osascript: str) -> list[str]:
    """組 osascript 指令參數（抽出供單測，不真的彈通知）。"""
    script = f'display notification "{_escape(body)}" with title "{_escape(title)}"'
    return [osascript, "-e", script]


def macos_notify(title: str, body: str, timeout: float = 5.0) -> bool:
    """發一則 macOS 通知；成功回 True，否則 False（不拋例外）。"""
    try:
        osa = shutil.which("osascript")
        if not osa:
            return False  # 非 macOS / 無 osascript
        subprocess.run(
            _notify_args(title, body, osa),
            timeout=timeout,
            capture_output=True,
            check=False,
        )
        return True
    except Exception as exc:  # noqa: BLE001
        _logger.warning("macos_notify 失敗：%s", exc)
        return False
