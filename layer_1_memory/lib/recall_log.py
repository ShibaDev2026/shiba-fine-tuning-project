"""recall_log.py — Layer 1 RAG 召回日誌（每日 append log）。

職責（SRP，純檔案 IO）：
- append_cause：召回時 append「問題 + 召回原因(score)」到 recall_logs/<yyyyMMdd>.txt，
  並寫 pending 標記（內容=該日檔絕對路徑）供 Stop hook 補回答。
- append_answer：Stop hook 讀 pending 標記指向的日檔，append Claude 回答 + 收尾，清標記。
- _prune：append 時順手刪超期日檔（解析檔名日期，非 mtime）。

設計約束：
- scrub 以 callable 注入（DIP）：本模組不依賴 layer_2；呼叫端傳脫敏函式（fail-closed
  由呼叫端決定——scrub 不可用時根本別呼叫）。
- side-effect only：任何寫檔失敗皆只進 logger、不冒泡，避免連坐破壞 hook 的 stdout 契約。
- pending 內容存「日檔路徑」而非僅 session→檔對應，故跨午夜（cause 在昨日檔、answer 在
  今日觸發）仍能把回答 append 回 cause 所在的同一個檔。
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable

_logger = logging.getLogger(__name__)

# feed_model=false 下，召回與回答只是共現、非因果——每筆回答尾端標註，避免誤讀。
_FEED_NOTE = "[註] feed_model=false：上方召回未餵給 Claude，本回答未受其影響，僅並列供比對"


def _ts(when: datetime) -> str:
    """毫秒時間戳：YYYY-MM-DD HH:MM:SS.SSS"""
    return when.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


def _day_file(log_dir: Path, when: datetime) -> Path:
    """日檔路徑：<log_dir>/yyyyMMdd.txt（append 當下日期決定，跨日自動換檔）"""
    return log_dir / f"{when:%Y%m%d}.txt"


def _pending_path(log_dir: Path, session_id: str) -> Path:
    """pending 標記檔：每 session 一個，內容=cause 寫入的日檔路徑"""
    return log_dir / f".pending_{(session_id or 'unknown')[:8]}"


def has_pending(log_dir: Path, session_id: str) -> bool:
    """本 session 是否有待補回答的 pending 標記。

    Stop hook 用：無 pending（本輪未召回）即可跳過、不必解析 transcript。
    """
    return _pending_path(log_dir, session_id).exists()


def _one_line(text: str) -> str:
    """多行召回內容收斂成單行（日誌可讀）；保留全文、不截斷"""
    return " ".join((text or "").split())


def _format_cause(
    ts: str,
    sid8: str,
    question: str,
    source: str,
    hits: list[dict],
    scrub: Callable[[str], str],
) -> str:
    """組「問題 + 召回原因」區塊；vector 標 cosine 分數、fts5 標 rank。"""
    lines = [
        f"[{ts}] [INFO][session={sid8}] 問題：{scrub(question)}",
        f"[召回原因] source={source}",
    ]
    for i, h in enumerate(hits, 1):
        score = h.get("score")
        if isinstance(score, (int, float)):
            tag = f"score={score:.3f}"
            text = f"問題：{h.get('instruction', '')} / 指令：{h.get('commands', '')}"
        else:
            tag = f"score=fts5#{i}"  # FTS5 無 cosine 分數，標 rank
            text = h.get("snippet", "")
        lines.append(f"  · {tag}  {scrub(_one_line(text))}")
    return "\n".join(lines) + "\n"


def append_cause(
    log_dir: Path,
    session_id: str,
    question: str,
    source: str,
    hits: list[dict],
    scrub: Callable[[str], str],
    retention_days: int = 30,
    when: datetime | None = None,
) -> None:
    """召回時 append cause 區塊到今日日檔，並寫 pending 標記。side-effect only。"""
    when = when or datetime.now()
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        _prune(log_dir, retention_days, when)
        day = _day_file(log_dir, when)
        block = _format_cause(
            _ts(when), (session_id or "unknown")[:8], question, source, hits, scrub
        )
        with day.open("a", encoding="utf-8") as f:
            f.write(block)
        # pending 內容=日檔絕對路徑，供跨午夜時 answer 仍 append 回同檔
        _pending_path(log_dir, session_id).write_text(str(day), encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        _logger.warning("recall_log append_cause 失敗：%s", exc)


def append_answer(
    log_dir: Path,
    session_id: str,
    answer: str,
    scrub: Callable[[str], str],
    when: datetime | None = None,
) -> bool:
    """Stop hook 補回答：有 pending 才補（本輪有召回）。回傳是否補了。side-effect only。"""
    when = when or datetime.now()
    pending = _pending_path(log_dir, session_id)
    if not pending.exists():
        return False  # 本輪無召回，無 cause 可配對
    try:
        target_str = pending.read_text(encoding="utf-8").strip()
        target = Path(target_str) if target_str else _day_file(log_dir, when)
        block = (
            f"[{_ts(when)}] [INFO][session={(session_id or 'unknown')[:8]}] [Claude 回答]\n"
            f"{scrub(answer)}\n{_FEED_NOTE}\n[=== END ===]\n\n"
        )
        with target.open("a", encoding="utf-8") as f:
            f.write(block)
        return True
    except Exception as exc:  # noqa: BLE001
        _logger.warning("recall_log append_answer 失敗：%s", exc)
        return False
    finally:
        try:
            pending.unlink(missing_ok=True)
        except Exception:  # noqa: BLE001
            pass


def _prune(log_dir: Path, retention_days: int, today: datetime) -> None:
    """刪超期日檔：解析檔名 yyyyMMdd，早於 today-retention_days 者刪。"""
    if retention_days <= 0:
        return
    cutoff = (today - timedelta(days=retention_days)).date()
    for p in log_dir.glob("*.txt"):
        try:
            file_date = datetime.strptime(p.stem, "%Y%m%d").date()
        except ValueError:
            continue  # 非日檔命名，略過
        if file_date < cutoff:
            try:
                p.unlink()
            except Exception as exc:  # noqa: BLE001
                _logger.warning("recall_log prune 刪檔失敗 %s：%s", p, exc)
