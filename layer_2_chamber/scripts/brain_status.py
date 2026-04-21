#!/usr/bin/env python3
"""
brain_status.py — Shiba Brain 系統診斷 CLI

執行：
    python layer_2_chamber/scripts/brain_status.py
"""
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from layer_2_chamber.backend.core.config import DB_PATH, init_layer2_db

BLOCK_THRESHOLD = 30
EXTERNAL_DATASET_DIR = Path.home() / ".local-brain" / "external_dataset"


def main():
    conn = init_layer2_db()
    print("=== Shiba Brain Status ===")
    print()
    _show_pipeline(conn)
    print()
    _show_teachers(conn)
    print()
    _show_external_dataset()
    conn.close()


def _show_pipeline(conn):
    rows = conn.execute("""
        SELECT status, adapter_block, COUNT(*) as cnt
        FROM training_samples
        GROUP BY status, adapter_block
    """).fetchall()

    by_status: dict = {}
    approved_by_block: dict = {1: 0, 2: 0}

    for r in rows:
        s = r["status"]
        b = r["adapter_block"]
        by_status[s] = by_status.get(s, 0) + r["cnt"]
        if s == "approved" and b in (1, 2):
            approved_by_block[b] += r["cnt"]

    print("[Pipeline]")
    print(f"  Pending samples    : {by_status.get('pending', 0)}")
    print(f"  Approved (all)     : {by_status.get('approved', 0)}")
    print(f"  Approved (Block 1) : {approved_by_block[1]} / {BLOCK_THRESHOLD} needed")
    print(f"  Approved (Block 2) : {approved_by_block[2]} / {BLOCK_THRESHOLD} needed")


def _show_teachers(conn):
    now_utc = datetime.now(timezone.utc)
    reset_str = now_utc.strftime("%Y-%m-%d 00:00")
    print(f"[Teachers]  今日 UTC reset: {reset_str}")

    rows = conn.execute("SELECT * FROM teachers ORDER BY priority").fetchall()
    if not rows:
        print("  （無 Teacher，請執行 setup_teachers.py --setup）")
        return

    for t in rows:
        name = t["name"]
        keychain_ref = t["keychain_ref"]

        # 取得配額資訊（相容 migration 前後）
        try:
            req_limit = t["daily_request_limit"]
        except Exception:
            req_limit = t["daily_limit"]

        try:
            token_limit = t["daily_token_limit"]
        except Exception:
            token_limit = None

        try:
            req_used = t["requests_today"] or 0
        except Exception:
            req_used = 0

        try:
            in_t = t["input_tokens_today"] or 0
            out_t = t["output_tokens_today"] or 0
            tokens_used = in_t + out_t
        except Exception:
            tokens_used = 0

        try:
            exhausted_at = t["quota_exhausted_at"]
        except Exception:
            exhausted_at = None

        # 判斷 key 是否設定
        if keychain_ref is not None:
            from layer_2_chamber.backend.services.teacher_service import get_api_key
            has_key = get_api_key(keychain_ref) is not None
        else:
            has_key = True  # 本地，無需 key

        if not t["is_active"]:
            icon = "○"
            detail = "停用"
        elif not has_key:
            icon = "✗"
            detail = "key not set"
        elif t["is_daily_limit_reached"]:
            icon = "✗"
            detail = "配額已滿"
        else:
            icon = "✓"
            if req_limit is None:
                req_str = "unlimited      "
                used_str = f"requests: ∞"
            else:
                req_str = f"{req_limit} req/day   "
                used_str = f"used: {req_used}"
            exhaust_str = f"exhausted: {exhausted_at[:10] if exhausted_at else '-'}"
            detail = f"{req_str} ({used_str}, {exhaust_str})"

        # token 附加資訊
        if token_limit:
            token_str = f"  tokens: {tokens_used:,}/{token_limit:,}"
        elif tokens_used > 0:
            token_str = f"  tokens: {tokens_used:,}"
        else:
            token_str = ""

        print(f"  {icon} {name:<24} {detail}{token_str}")


def _show_external_dataset():
    print("[External Dataset]")
    if not EXTERNAL_DATASET_DIR.exists():
        print(f"  {EXTERNAL_DATASET_DIR}  未配置，建議放入 Alpaca JSONL")
        return

    jsonl_files = sorted(EXTERNAL_DATASET_DIR.glob("*.jsonl"))
    if not jsonl_files:
        print(f"  {EXTERNAL_DATASET_DIR}  目錄存在但無 .jsonl 檔案")
        return

    total = 0
    for f in jsonl_files:
        try:
            count = sum(1 for line in f.open(encoding="utf-8") if line.strip())
            total += count
            print(f"  ✓ {f.name:<35} {count:>6} 筆")
        except Exception as e:
            print(f"  ✗ {f.name:<35} 讀取失敗：{e}")
    print(f"  合計：{total} 筆外部樣本")


if __name__ == "__main__":
    main()
