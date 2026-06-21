"""決定性實驗：refine instruction 後 re-grade，量化分數是否跨過 approval 門檻 8.0。

對每個低分 real-NL v2 樣本：用本地 judge panel 評「原 instruction」vs「refined instruction」
（output 不動），比較分數。非破壞：只呼叫 _collect_votes（回 votes，不改 training_samples
 的 status/score）；副作用僅 judge quota 計數（本地裁判，無害）。
"""
import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from layer_2_chamber.backend.services.refiner_service import refine_sample
from layer_2_chamber.backend.services.multi_judge import _collect_votes, _APPROVED_THRESHOLD
from layer_2_chamber.backend.services.teacher_service import (
    get_active_teachers, is_quota_available,
)

conn = sqlite3.connect("data/shiba-brain.db")
conn.row_factory = sqlite3.Row
teachers = get_active_teachers(conn)
available = [t for t in teachers if is_quota_available(conn, t)]
print(f"active judges: {[t['name'] for t in available]}  approval 門檻={_APPROVED_THRESHOLD}\n")

noise = re.compile(r'<command-|<local-command|<bash-|\[Request interrupted|<system-reminder>')
rows = conn.execute(
    "SELECT id, instruction, input, output, score, adapter_block FROM training_samples "
    "WHERE source='layer1_bridge_v2' AND score < 8 ORDER BY score DESC"
).fetchall()
real_low = [r for r in rows if r["instruction"] and not noise.search(r["instruction"])][:5]


def grade(sid, instr, inp, out):
    votes = _collect_votes(conn, sid, instr, inp or "", out, available)
    if not votes:
        return None, []
    avg = sum(v["score"] for v in votes) / len(votes)
    return avg, [round(v["score"], 1) for v in votes]


crossed = 0
for r in real_low:
    o_avg, o_v = grade(r["id"], r["instruction"], r["input"], r["output"])
    ref = refine_sample(r["instruction"], r["input"] or "", r["output"] or "")
    ri = ref["refined_instruction"]
    rewritten = ri is not None
    graded_instr = ri if rewritten else r["instruction"]
    n_avg, n_v = grade(r["id"], graded_instr, r["input"], r["output"])
    print("=" * 66)
    print(f"id={r['id']} blk={r['adapter_block']} DB原score={r['score']}")
    print(f"  原 instr   : {r['instruction'][:70]!r}")
    print(f"  改寫?      : {rewritten}  refined={ (ri or '')[:70]!r}")
    print(f"  原 re-grade : avg={o_avg}  votes={o_v}")
    print(f"  refined grade: avg={n_avg}  votes={n_v}")
    if n_avg is not None and n_avg >= _APPROVED_THRESHOLD:
        crossed += 1
        print("  ✓ 跨過門檻 8.0")
    elif o_avg is not None and n_avg is not None:
        print(f"  Δ={n_avg - o_avg:+.2f}（未過門檻）")

print("\n" + "=" * 66)
print(f"結論：{crossed}/{len(real_low)} 個 refined 樣本跨過 approval 門檻 8.0")
conn.close()
