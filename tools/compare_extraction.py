"""
compare_extraction.py — 路徑 A v1 vs v2 A/B 對比腳本

用途：
  驗證 _extract_path_a_v2 的樣本覆蓋率與品質等於或優於 v1（layer1_bridge）。
  純讀 DB，不寫入任何資料，可重複執行。

使用方式：
  cd /Users/surpend/Developer/01_project/shiba-fine-tuning-project
  /Users/surpend/.local-brain/venv/bin/python3 -m tools.compare_extraction --report
"""

import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from layer_2_chamber.backend.extraction.pipeline import _extract_path_a_v2

# DB 路徑（與 shiba.yaml 同一路徑）
_DB_PATH = Path.home() / ".local-brain" / "shiba-brain.db"


def _get_conn(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _fetch_v1_sessions(conn: sqlite3.Connection) -> dict[str, dict]:
    """從 training_samples 讀取 v1 已抽取的 session（source='layer1_bridge'）"""
    rows = conn.execute(
        "SELECT session_id, instruction, output FROM training_samples WHERE source = 'layer1_bridge'"
    ).fetchall()
    return {r["session_id"]: {"instruction": r["instruction"], "output": r["output"]} for r in rows}


def _fetch_v2_sessions(conn: sqlite3.Connection) -> dict[str, dict]:
    """
    呼叫 _extract_path_a_v2（純讀，不 commit），回傳 session_uuid → {instruction, output}。
    v2 的 NOT IN 過濾已在 SQL 內，但因為沒有任何 v2 紀錄，等於全量跑一遍。
    """
    samples = _extract_path_a_v2(conn)
    return {s.session_id: {"instruction": s.instruction, "output": s.output} for s in samples}


def _diff_sample(v1: dict, v2: dict) -> dict | None:
    """比較同一 session 的 instruction 與 output，有差異才回傳 diff 描述"""
    diffs = {}
    if v1["instruction"] != v2["instruction"]:
        diffs["instruction"] = {"v1_len": len(v1["instruction"]), "v2_len": len(v2["instruction"])}
    if v1["output"] != v2["output"]:
        diffs["output"] = {"v1_len": len(v1["output"]), "v2_len": len(v2["output"])}
    return diffs if diffs else None


def report(db_path: Path) -> None:
    conn = _get_conn(db_path)

    print("讀取 v1 (layer1_bridge) sessions …")
    v1 = _fetch_v1_sessions(conn)
    print(f"讀取 v2 (layer1_bridge_v2) sessions …")
    v2 = _fetch_v2_sessions(conn)

    v1_keys = set(v1)
    v2_keys = set(v2)
    common = v1_keys & v2_keys
    only_v1 = v1_keys - v2_keys
    only_v2 = v2_keys - v1_keys

    print()
    print("=" * 50)
    print(f"  v1 sessions sampled : {len(v1_keys)}")
    print(f"  v2 sessions sampled : {len(v2_keys)}")
    print(f"  only_in_v1          : {len(only_v1)}  （v2 漏抓，需人工確認）")
    print(f"  only_in_v2          : {len(only_v2)}  （v1 邊界 bug 漏掉的）")
    print(f"  common              : {len(common)}")
    print("=" * 50)

    # 通過判準
    if len(v1_keys) > 0:
        miss_rate = len(only_v1) / len(v1_keys)
        pass_criterion = miss_rate < 0.05
        print(f"  漏抓率 only_v1/v1   : {miss_rate:.1%}  {'✓ PASS' if pass_criterion else '✗ FAIL (>5%)'}")
    print()

    # common 中有差異的樣本（抽 5 筆）
    diff_cases = []
    for uuid in list(common):
        d = _diff_sample(v1[uuid], v2[uuid])
        if d:
            diff_cases.append({"session_uuid": uuid, "diff": d})

    print(f"  common 中 instruction/output 有差異的 session：{len(diff_cases)} 筆")
    if diff_cases:
        print("  （前 5 筆 diff 摘要）")
        for case in diff_cases[:5]:
            print(f"    session: {case['session_uuid']}")
            for field, info in case["diff"].items():
                print(f"      {field}: v1={info['v1_len']}chars  v2={info['v2_len']}chars")

    # only_v1 前 3 筆摘要（供人工抽查）
    if only_v1:
        print()
        print(f"  only_in_v1 前 3 筆 instruction 摘要（請確認為 v1 誤抓或 v2 應補充的）：")
        for uuid in list(only_v1)[:3]:
            snippet = v1[uuid]["instruction"][:80].replace("\n", " ")
            print(f"    {uuid}: {snippet!r}")

    conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Path A v1 vs v2 A/B 對比")
    parser.add_argument("--report", action="store_true", help="輸出對比報告")
    parser.add_argument("--db", default=str(_DB_PATH), help=f"DB 路徑（預設 {_DB_PATH}）")
    args = parser.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"ERROR: DB 不存在：{db_path}", file=sys.stderr)
        sys.exit(1)

    if args.report:
        report(db_path)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
