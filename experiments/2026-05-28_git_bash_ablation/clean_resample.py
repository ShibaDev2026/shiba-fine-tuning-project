"""
Phase A — 乾淨子集重抽樣（取代 ablation 被 over-merge 污染的 30 筆）。

背景：原 samples.csv 從 over-merged exchange 抽，user_text 與 gold_commands 錯配
（如 #5「維護 readme」配到 RAGAS commit）。根因＝branch_messages.seq 退化（82% branch）。
本腳本只從「乾淨 exchange」（無 seq 污染）抽樣，並用本地蒸餾器過濾出真指令請求。

乾淨判準（不受 seq bug 影響的 exchange）：
  status='completed' AND ended_at >= started_at（無時間倒置）
  AND message_count <= 4 AND 跨度 < 1h AND has_tool_use=1（單一指令往返的典型形狀）

流程：
  1. 撈乾淨 exchange，重建（user 請求 + 依序工具指令），複用 distill_validate.reconstruct
  2. 本地 qwen3:30b 蒸餾 → is_command_request 過濾（保守準）
  3. is_command_request=1 才入選 → 寫 clean_samples.csv（infer.py 可直接吃）
     instruction = 使用者原始請求（responder 真正會收到的）；gold_commands = 實際工具指令

純讀 DB + 本地 Ollama。輸出 clean_samples.csv（n≥30 真指令請求）。
"""
from __future__ import annotations

import argparse
import csv
import random
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from shiba_config import CONFIG  # noqa: E402
from sample import parse_command, redact  # noqa: E402
from distill_validate import build_distill_input, distill, reconstruct  # noqa: E402

HERE = Path(__file__).parent
OUT_CSV = HERE / "clean_samples.csv"

CLEAN_SQL = """
    SELECT e.id AS exchange_id, e.session_id AS session_id
    FROM exchanges e
    WHERE e.status = 'completed'
      AND e.ended_at >= e.started_at
      AND e.message_count <= 4
      AND (julianday(e.ended_at) - julianday(e.started_at)) * 24 < 1.0
      AND e.has_tool_use = 1
    ORDER BY e.id
"""


def first_bash_command(conn: sqlite3.Connection, exchange_id: int) -> str | None:
    """取該 exchange 第一條成功的 Bash 指令當 gold（與 ablation 一致）。"""
    rows = conn.execute(
        """SELECT te.input_cmd
           FROM exchange_messages em JOIN tool_executions te ON te.message_id = em.message_id
           WHERE em.exchange_id = ? AND te.tool_name = 'Bash' AND te.is_error = 0
           ORDER BY em.seq, te.id""",
        (exchange_id,),
    ).fetchall()
    for r in rows:
        cmd = parse_command(r["input_cmd"])
        if cmd:
            return cmd
    return None


def main() -> None:
    p = argparse.ArgumentParser(description="乾淨子集重抽樣 + 蒸餾過濾")
    p.add_argument("--model", default="qwen3:30b-a3b", help="蒸餾過濾用模型（保守準）")
    p.add_argument("--target", type=int, default=35, help="目標真指令請求數")
    p.add_argument("--scan-limit", type=int, default=120, help="最多掃幾筆乾淨候選（控時）")
    p.add_argument("--seed", type=int, default=20260529)
    args = p.parse_args()

    conn = sqlite3.connect(f"file:{CONFIG.paths.db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    candidates = [dict(r) for r in conn.execute(CLEAN_SQL).fetchall()]
    print(f"乾淨候選 {len(candidates)} 筆；隨機掃描上限 {args.scan_limit}，目標 {args.target} 筆真指令")

    rng = random.Random(args.seed)
    rng.shuffle(candidates)

    picked: list[dict] = []
    seen_gold: set[str] = set()  # 依 gold 去重，避免 /loop 重複 prompt 灌水（沿用 ablation sample.py 慣例）
    scanned = 0
    try:
        for c in candidates:
            if len(picked) >= args.target or scanned >= args.scan_limit:
                break
            scanned += 1
            ex_id = c["exchange_id"]
            gold = first_bash_command(conn, ex_id)
            if not gold:
                continue  # 無可用 Bash 指令 → 跳過（gold 缺失）
            gold_key = " ".join(redact(gold).split())  # 正規化（去 PII + 收斂空白）當去重 key
            if gold_key in seen_gold:
                continue  # 同一 gold 已收，跳過不浪費蒸餾呼叫
            rec = reconstruct(conn, ex_id)
            if not rec["user_text"].strip():
                continue
            try:
                d, _ = distill(args.model, build_distill_input(rec))
            except Exception as e:  # noqa: BLE001
                print(f"  ex {ex_id} 蒸餾失敗：{e}")
                continue
            is_cmd = d.get("is_command_request")
            mark = "✓真指令" if is_cmd == 1 else f"✗({d.get('request_type')})"
            print(f"  [掃{scanned}] ex{ex_id} {mark} | {d.get('intent','')[:40]}")
            if is_cmd == 1:
                seen_gold.add(gold_key)
                picked.append({
                    "session_id": c["session_id"],
                    "exchange_id": ex_id,
                    "instruction": redact(rec["user_text"].strip())[:500],
                    "gold_commands": redact(gold),
                    "distilled_intent": d.get("intent", ""),
                    "command_template": d.get("command_template", ""),
                })
    finally:
        conn.close()

    print(f"\n命中真指令請求 {len(picked)} 筆（掃了 {scanned} 筆乾淨候選）")
    with OUT_CSV.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["sample_id", "session_id", "exchange_id", "instruction",
                    "gold_commands", "distilled_intent", "command_template"])
        for i, s in enumerate(picked, 1):
            w.writerow([i, s["session_id"], s["exchange_id"], s["instruction"],
                        s["gold_commands"], s["distilled_intent"], s["command_template"]])
    print(f"✓ 寫入 {OUT_CSV}（{len(picked)} 筆）")
    if len(picked) < 30:
        print(f"⚠ 不足 30 筆，提高 --scan-limit 再跑")


if __name__ == "__main__":
    main()
