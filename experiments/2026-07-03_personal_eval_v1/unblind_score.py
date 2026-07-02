#!/usr/bin/env python3
"""解盲計分：grades.json（{qid:{X:0-2,Y:0-2}}）× mapping.json → 兩臂總分、分組分、翻車數、判定"""
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
grades = json.loads((HERE / "grades.json").read_text(encoding="utf-8"))
mapping = json.loads((HERE / "mapping.json").read_text(encoding="utf-8"))
eval_set = json.loads((HERE / "eval_set.json").read_text(encoding="utf-8"))
group_of = {q["id"]: q["group"] for q in eval_set["questions"]}

totals = {"A": 0, "B": 0}
by_group = {}
flips = []  # B 相對 A 由 2 → 0
per_q = {}
for qid, g in grades.items():
    a = g["X"] if mapping[qid]["X"] == "A" else g["Y"]
    b = g["X"] if mapping[qid]["X"] == "B" else g["Y"]
    totals["A"] += a
    totals["B"] += b
    grp = by_group.setdefault(group_of[qid], {"A": 0, "B": 0})
    grp["A"] += a
    grp["B"] += b
    per_q[qid] = {"A": a, "B": b}
    if a == 2 and b == 0:
        flips.append(qid)

diff = totals["B"] - totals["A"]
if diff >= 5:
    verdict = "B 勝（召回前提成立）"
elif diff <= -5:
    verdict = "召回有害"
else:
    verdict = "無實質差異 → 前提 FAIL（召回不加分）"

print(json.dumps({"totals": totals, "diff_B_minus_A": diff, "by_group": by_group,
                  "flips_2to0": flips, "verdict": verdict, "per_q": per_q},
                 ensure_ascii=False, indent=1))
