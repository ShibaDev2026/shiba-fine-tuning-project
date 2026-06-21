"""決定性實驗：分離「配對問題 vs 門檻問題」。

把『已知良好、連貫、自包含』的配對（gatekeeper_golden_samples 的 instruction+expected_output，
手撰、seed 標 9.5）丟現行本地 3-judge panel 評。
- 若完美配對 ≥8 → panel 會獎勵好配對 → 瓶頸是配對品質 → 過濾/重構設計成立。
- 若完美配對 <8 → 連完美對都過不了 → 瓶頸是 panel/門檻 → 任何配對修法到不了 30/block。

對照組：一個真實低分對（id=25, DB 6.0）。非破壞：只用 _collect_votes（不改 training_samples）。
"""
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from layer_2_chamber.backend.services.multi_judge import _collect_votes, _APPROVED_THRESHOLD
from layer_2_chamber.backend.services.teacher_service import (
    get_active_teachers, is_quota_available,
)

conn = sqlite3.connect("data/shiba-brain.db")
conn.row_factory = sqlite3.Row
teachers = get_active_teachers(conn)
available = [t for t in teachers if is_quota_available(conn, t)]
print(f"judges: {[t['name'] for t in available]}  門檻={_APPROVED_THRESHOLD}\n")


def grade(sid, instr, inp, out):
    votes = _collect_votes(conn, sid, instr, inp or "", out, available)
    if not votes:
        return None, []
    return sum(v["score"] for v in votes) / len(votes), [(round(v["score"], 1), v["approved"]) for v in votes]


print("=== A. 已知良好 gold 配對（instruction + expected_output, seed=9.5）===")
golds = conn.execute(
    "SELECT id, instruction, input, expected_output, event_type, score "
    "FROM gatekeeper_golden_samples WHERE is_active=1 LIMIT 5"
).fetchall()
ge8 = 0
for g in golds:
    avg, votes = grade(g["id"], g["instruction"], g["input"], g["expected_output"])
    crossed = avg is not None and avg >= _APPROVED_THRESHOLD
    ge8 += crossed
    print(f"  gold id={g['id']} [{g['event_type']}] seed={g['score']} → panel avg={avg} votes={votes} {'✓>=8' if crossed else ''}")
    print(f"    instr: {g['instruction'][:55]!r}")

print(f"\n  結論：{ge8}/{len(golds)} 個『完美配對』過 8.0 門檻")

print("\n=== B. 對照：真實低分對 id=25（DB 6.0）===")
r = conn.execute("SELECT id, instruction, input, output FROM training_samples WHERE id=25").fetchone()
avg, votes = grade(r["id"], r["instruction"], r["input"], r["output"])
print(f"  id=25 → panel avg={avg} votes={votes}")
conn.close()
