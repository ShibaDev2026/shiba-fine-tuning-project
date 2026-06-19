#!/usr/bin/env python3
"""scripts/grading_harness_cli.py — grading harness 子指令入口。

  status : 印 per event_type 進度（續跑判斷）
  bridge : 題庫 questions → training_samples needs_review 列（Tier B 種子，--source S）
  export : 匯出平衡批次 JSON 給 Claude 本 session 評（--tier A|B --size N --out PATH [--status S]）
  ingest : 回寫 Claude 評分 JSON（--in PATH）
  local  : drain 本地批量評分（需先 `lms server start --port 1234`）
  freeze : 凍結 gold（委派 scripts/freeze_golden_set.main）
"""
import argparse
import json
import sqlite3
import sys
from pathlib import Path

_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT))

from shiba_config import CONFIG
from layer_2_chamber.backend.services import grading_harness as gh


def _conn():
    conn = sqlite3.connect(str(CONFIG.paths.db))
    conn.row_factory = sqlite3.Row
    return conn


def main(argv=None):
    p = argparse.ArgumentParser(description="grading harness CLI")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    e = sub.add_parser("export")
    e.add_argument("--tier", choices=["A", "B"], required=True)
    e.add_argument("--size", type=int, default=14)
    e.add_argument("--out", required=True)
    e.add_argument("--status", default="pending",
                   help="撈哪個狀態（Tier A 評本地池用 pending；Tier B 親評用 needs_review）")
    b = sub.add_parser("bridge")
    b.add_argument("--source", required=True,
                   help="橋接列寫入的 source（須為 valid CHECK 值，如 layer1_bridge_v2）")
    i = sub.add_parser("ingest")
    i.add_argument("--in", dest="inp", required=True)
    sub.add_parser("local")
    fz = sub.add_parser("freeze")
    fz.add_argument("--dry-run", action="store_true")
    args = p.parse_args(argv)

    if args.cmd == "status":
        print(json.dumps(gh.harness_progress(_conn()), ensure_ascii=False, indent=2))
    elif args.cmd == "export":
        batch = gh.export_gold_candidates(
            _conn(), tier=args.tier, batch_size=args.size, status=args.status)
        Path(args.out).write_text(json.dumps(batch, ensure_ascii=False, indent=2))
        print(f"exported {len(batch['candidates'])} candidates "
              f"(skipped {batch['skipped']}) → {args.out}")
    elif args.cmd == "bridge":
        print(gh.bridge_questions(_conn(), source=args.source))
    elif args.cmd == "ingest":
        graded = json.loads(Path(args.inp).read_text())
        print(gh.ingest_grades(_conn(), graded))
    elif args.cmd == "local":
        print(gh.drain_pending(_conn))
    elif args.cmd == "freeze":
        from scripts.freeze_golden_set import main as freeze_main
        freeze_main(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
