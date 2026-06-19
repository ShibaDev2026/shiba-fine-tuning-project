"""
Step 1 — 抽樣：從 exchanges + tool_executions 抽 30 筆 (請求 → 真實 git/bash 指令) 配對。

修正紀錄（2026-05-28 實查）：
  exchange_embeddings 不可用——含 git 僅 12 筆且全是重複的 `git stash pop`。
  真正配對在 exchanges(user_text_preview=請求) → exchange_messages → tool_executions(input_cmd=果)。

純讀 DB，不寫任何表、不碰 production code。
輸出：samples.csv（sample_id, session_uuid, exchange_id, instruction, gold_commands）
"""
from __future__ import annotations

import argparse
import csv
import json
import random
import re
import sqlite3
import sys
from pathlib import Path

# 專案根加入 sys.path，借用 shiba_config 解析 DB 路徑 + golden_set_builder 黑名單
PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from shiba_config import CONFIG  # noqa: E402
from modules.ragas.golden_set_builder import _BLACKLIST  # noqa: E402

OUT_CSV = Path(__file__).parent / "samples.csv"

# ── 非真人請求的 user_text_preview 前綴（系統注入 / 工具 stdout / 中斷標記）──
_NOISE_PREFIXES = (
    "✓ ", "Caveat:", "<local-command", "<command-", "[Request interrupted",
    "<system-reminder", "API Error", "[", "{",
)

# ── PII redaction 樣式（不得輸出 home dir / email / token）──
_HOME_RE = re.compile(r"/Users/[^/\s\"']+")
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_TOKEN_RE = re.compile(r"\b(?:sk|ghp|gho|pat|key)[-_][A-Za-z0-9]{16,}\b", re.IGNORECASE)


def redact(text: str) -> str:
    """去機敏：home dir → <HOME>，email → <EMAIL>，token 樣式 → <TOKEN>"""
    text = _HOME_RE.sub("<HOME>", text)
    text = _EMAIL_RE.sub("<EMAIL>", text)
    text = _TOKEN_RE.sub("<TOKEN>", text)
    return text


def is_real_request(instruction: str | None) -> bool:
    """判斷 user_text_preview 是否為真人請求（過濾系統注入 / 過短 / 黑名單）"""
    if not instruction:
        return False
    s = instruction.strip()
    if len(s) < 8:
        return False
    if s.lower() in {w.lower() for w in _BLACKLIST}:
        return False
    if any(s.startswith(p) for p in _NOISE_PREFIXES):
        return False
    return True


def parse_command(input_cmd: str | None) -> str | None:
    """tool_executions.input_cmd 是 JSON {"command":..,"description":..} → 取 command"""
    if not input_cmd:
        return None
    try:
        obj = json.loads(input_cmd)
    except (json.JSONDecodeError, TypeError):
        return None
    cmd = obj.get("command") if isinstance(obj, dict) else None
    return cmd.strip() if isinstance(cmd, str) and cmd.strip() else None


def norm_key(cmd: str) -> str:
    """去重鍵：小寫 + 摺疊空白 + 截前 80 字（避免 12× 重複 git stash pop）"""
    return re.sub(r"\s+", " ", cmd.lower()).strip()[:80]


def fetch_candidates(conn: sqlite3.Connection) -> list[dict]:
    """JOIN 取所有 git/bash Bash 指令候選（純讀）"""
    sql = """
        SELECT e.id AS exchange_id,
               e.session_id AS session_id,
               e.user_text_preview AS instruction,
               te.input_cmd AS input_cmd
        FROM exchanges e
        JOIN exchange_messages em ON em.exchange_id = e.id
        JOIN tool_executions te  ON te.message_id = em.message_id
        WHERE e.status = 'completed'
          AND te.tool_name = 'Bash'
          AND te.is_error = 0
          AND (te.input_cmd LIKE '%git %' OR te.input_cmd LIKE '%bash %')
        ORDER BY e.id
    """
    return [dict(r) for r in conn.execute(sql).fetchall()]


def main() -> None:
    p = argparse.ArgumentParser(description="抽 git/bash 樣本")
    p.add_argument("--n", type=int, default=30, help="抽樣數")
    p.add_argument("--seed", type=int, default=20260528, help="隨機種子（可重現）")
    args = p.parse_args()

    db_path = CONFIG.paths.db
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        rows = fetch_candidates(conn)
    finally:
        conn.close()

    seen_cmd: set[str] = set()
    seen_exchange: set[int] = set()
    pool: list[dict] = []
    for r in rows:
        if r["exchange_id"] in seen_exchange:
            continue  # 一個 exchange 只取一筆，避免單一 exchange 灌量
        if not is_real_request(r["instruction"]):
            continue
        cmd = parse_command(r["input_cmd"])
        if not cmd:
            continue
        key = norm_key(cmd)
        if key in seen_cmd:
            continue  # 指令去重
        seen_cmd.add(key)
        seen_exchange.add(r["exchange_id"])
        pool.append({
            "session_id": r["session_id"],
            "exchange_id": r["exchange_id"],
            "instruction": redact(r["instruction"].strip()),
            "gold_commands": redact(cmd),
        })

    print(f"候選去重後 {len(pool)} 筆，抽 {args.n} 筆（seed={args.seed}）")
    if len(pool) < args.n:
        print(f"⚠ 候選不足 {args.n}，全取 {len(pool)} 筆")

    rng = random.Random(args.seed)
    picked = rng.sample(pool, min(args.n, len(pool)))

    with OUT_CSV.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["sample_id", "session_id", "exchange_id", "instruction", "gold_commands"])
        for i, s in enumerate(picked, 1):
            w.writerow([i, s["session_id"], s["exchange_id"], s["instruction"], s["gold_commands"]])

    print(f"✓ 寫入 {OUT_CSV}（{len(picked)} 筆）")


if __name__ == "__main__":
    main()
