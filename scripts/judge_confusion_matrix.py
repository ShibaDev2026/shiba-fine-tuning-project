#!/usr/bin/env python3
"""scripts/judge_confusion_matrix.py — D3 judge 可信度診斷（一次性）。

量化本地 panel（multi_judge）評分可信度：以 Claude in-session **盲評** + Shiba 人類標記
為 ground truth，對比 panel 的 approved/rejected 判定，算混淆矩陣（TPR/TNR/precision）。

⚠ 性質誠實切窄（對齊 Tier B [[project-grading-harness]]）：
  矩陣量的是 **panel vs Claude（經 Shiba 錨校準）**，非 panel vs 絕對真值。
  Claude 自身也是 LLM judge → 先用 Shiba 標記（唯一人類錨）盲評驗證 Claude，
  報 Claude-vs-Shiba agreement；agreement 夠高才有資格把 Claude 當其餘樣本的 GT。
  FP 清單＝「panel approved 但 Claude 判 bad」＝**複查候選，非已證爛**。

破循環：Claude 盲評時不看 panel status（盲檔不含），grader≠author。
PII（強約束）：盲評文本一律經 grading_harness.scrub_for_export，Claude 只讀 scrubbed；
  assert_clean 殘留則該筆 skip 並計數（不靜默吞）。oracle 檔不含任何原文（只 sid/status/shiba_gt）。

用法：
  1) python3 scripts/judge_confusion_matrix.py export --blind b.json --oracle o.json
  2) （Claude 讀 b.json 盲評，產生 verdicts.json: {"<sid>": "good"|"bad", ...}）
  3) python3 scripts/judge_confusion_matrix.py compute --oracle o.json --verdicts verdicts.json
"""
from __future__ import annotations

import argparse
import json
import random
import sqlite3
import sys
from pathlib import Path

_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT))

from shiba_config import CONFIG  # noqa: E402
# PII gate 重用（剛強化過的 fail-closed scrub，見 [[project-grading-harness]]）
from layer_2_chamber.backend.services.grading_harness import (  # noqa: E402
    scrub_for_export,
    assert_clean,
)

_POOL_STATUS = ("approved", "rejected")


def _shiba_label(conn: sqlite3.Connection, session_id: str | None) -> str | None:
    """以 router_decisions.user_accepted 派生人類 GT：1→good、0→bad、衝突/無→None。

    一個 session 可能對多筆 router_decisions；取該 session 的 distinct user_accepted：
    僅單一非空值才採信（good/bad），同時出現 0 與 1 視為衝突 → None（讓 Claude 評）。
    """
    if not session_id:
        return None
    vals = {
        r[0] for r in conn.execute(
            "SELECT DISTINCT user_accepted FROM router_decisions "
            "WHERE session_id=? AND user_accepted IS NOT NULL",
            (session_id,),
        ).fetchall()
    }
    if vals == {1}:
        return "good"
    if vals == {0}:
        return "bad"
    return None  # 無標記或 0/1 衝突 → 不當人類 GT


def export_for_review(
    conn: sqlite3.Connection,
    blind_path: str,
    oracle_path: str,
    *,
    seed: int = 20260619,
) -> dict:
    """撈 approved+rejected 全池，產出盲檔（Claude 讀）+ oracle 檔（compute 讀）。

    盲檔：[{review_id, sid, instruction, input, output}]（全 scrubbed、打散順序、不含 status）。
    oracle 檔：[{sid, panel_status, shiba_gt}]（無原文，PII-free）。
    PII fail-closed：scrub 後 assert_clean 殘留 → 該筆 skip 並計數（sid only）。
    """
    # question_id IS NULL：排除 Tier B 題庫橋接列（對齊 L3 汙染防護同一判別子）。
    # 那些列的 approved 是 Claude 親評 gold（grading harness Tier B）、非本地 panel 判定，
    # 且 output 空（內容在 expected_answer）；納入會把「Claude vs Claude」污染進
    # 「panel vs Claude」矩陣。只留 question_id IS NULL 的真實 session 輸出。
    rows = conn.execute(
        f"""SELECT id, session_id, event_type, status, instruction, input, output
            FROM training_samples
            WHERE status IN {_POOL_STATUS}
              AND question_id IS NULL
            ORDER BY id""",
    ).fetchall()

    blind: list[dict] = []
    oracle: list[dict] = []
    skipped: list[int] = []  # PII 殘留被擋的 sid（只記 id，不記內容）
    for sid, session_id, event_type, status, instruction, inp, output in rows:
        s_instr = scrub_for_export(instruction)
        s_input = scrub_for_export(inp)
        s_output = scrub_for_export(output)
        try:  # fail-closed：殘留任一機敏 → 跳過該筆，不送 Claude
            assert_clean(s_instr)
            assert_clean(s_input)
            assert_clean(s_output)
        except ValueError:
            skipped.append(sid)
            continue
        blind.append({
            "review_id": None,  # export 末尾 shuffle 後回填
            "sid": sid,
            "event_type": event_type,
            "instruction": s_instr,
            "input": s_input,
            "output": s_output,
        })
        oracle.append({
            "sid": sid,
            "panel_status": status,
            "shiba_gt": _shiba_label(conn, session_id),
        })

    # 打散盲檔順序（破逐筆 anchoring），回填 review_id
    rng = random.Random(seed)
    rng.shuffle(blind)
    for i, rec in enumerate(blind, 1):
        rec["review_id"] = i

    Path(blind_path).write_text(
        json.dumps(blind, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    Path(oracle_path).write_text(
        json.dumps(oracle, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return {
        "exported": len(blind),
        "skipped_pii": skipped,
        "shiba_labeled": sum(1 for o in oracle if o["shiba_gt"] is not None),
    }


def compute_confusion(verdicts: dict[str, str], oracle: list[dict]) -> dict:
    """合併 GT（Shiba 標記優先 > Claude verdict），對 panel 判定算混淆矩陣。

    positive = good（該進訓練集）。panel: approved→pred good、rejected→pred bad。
    FP = panel approved ∩ GT bad（漏網/複查候選）；FN = panel rejected ∩ GT good（誤殺）。
    另算 Claude-vs-Shiba agreement（僅 shiba_gt 非空者）= Claude 自身錨定。
    """
    tp = tn = fp = fn = 0
    fp_sids: list[int] = []      # panel approved 但 GT bad
    fn_sids: list[int] = []      # panel rejected 但 GT good
    missing: list[int] = []      # 無 Shiba 也無 Claude verdict → 無法定 GT
    # Claude 自身錨定（對 Shiba 標記者，比 Claude 盲評 vs Shiba）
    anc_good_agree = anc_good_total = 0
    anc_bad_agree = anc_bad_total = 0

    for o in oracle:
        sid = o["sid"]
        shiba = o["shiba_gt"]
        claude = verdicts.get(str(sid)) or verdicts.get(sid)

        # Claude 自身錨定統計（Shiba 標記 ∩ Claude 也評了）
        if shiba is not None and claude is not None:
            if shiba == "good":
                anc_good_total += 1
                anc_good_agree += int(claude == "good")
            else:
                anc_bad_total += 1
                anc_bad_agree += int(claude == "bad")

        gt = shiba if shiba is not None else claude
        if gt is None:
            missing.append(sid)
            continue

        pred_good = (o["panel_status"] == "approved")
        gt_good = (gt == "good")
        if pred_good and gt_good:
            tp += 1
        elif pred_good and not gt_good:
            fp += 1
            fp_sids.append(sid)
        elif (not pred_good) and (not gt_good):
            tn += 1
        else:
            fn += 1
            fn_sids.append(sid)

    def _safe(n, d):
        return round(n / d, 4) if d else None

    total = tp + tn + fp + fn
    anc_total = anc_good_total + anc_bad_total
    return {
        "matrix": {"TP": tp, "FP": fp, "TN": tn, "FN": fn},
        "metrics": {
            "TPR_recall": _safe(tp, tp + fn),      # 好樣本被放行比例
            "TNR": _safe(tn, tn + fp),             # 爛樣本被擋下比例（D3 核心，文獻<25%）
            "precision": _safe(tp, tp + fp),
            "accuracy": _safe(tp + tn, total),
            "n_scored": total,
        },
        "fp_review_candidates": sorted(fp_sids),   # panel approved 但 Claude/Shiba 判 bad
        "fn_overkill": sorted(fn_sids),            # panel rejected 但判 good
        "missing_gt": sorted(missing),
        "claude_self_anchor": {
            "vs_shiba_good_agree": f"{anc_good_agree}/{anc_good_total}",
            "vs_shiba_bad_agree": f"{anc_bad_agree}/{anc_bad_total}",  # 抓 confirmed-bad 能力（最強錨）
            "overall_agree": _safe(anc_good_agree + anc_bad_agree, anc_total),
        },
    }


def main(argv=None):
    p = argparse.ArgumentParser(description="D3 judge 可信度診斷")
    sub = p.add_subparsers(dest="cmd", required=True)
    pe = sub.add_parser("export", help="撈全池 → 盲檔+oracle 檔")
    pe.add_argument("--blind", required=True)
    pe.add_argument("--oracle", required=True)
    pc = sub.add_parser("compute", help="verdicts + oracle → 混淆矩陣")
    pc.add_argument("--oracle", required=True)
    pc.add_argument("--verdicts", required=True)
    args = p.parse_args(argv)

    if args.cmd == "export":
        conn = sqlite3.connect(str(CONFIG.paths.db))
        try:
            res = export_for_review(conn, args.blind, args.oracle)
        finally:
            conn.close()
        print(json.dumps(res, ensure_ascii=False, indent=2))
    elif args.cmd == "compute":
        oracle = json.loads(Path(args.oracle).read_text(encoding="utf-8"))
        verdicts = json.loads(Path(args.verdicts).read_text(encoding="utf-8"))
        print(json.dumps(compute_confusion(verdicts, oracle), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
