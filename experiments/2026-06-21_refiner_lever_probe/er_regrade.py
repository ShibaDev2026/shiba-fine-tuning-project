"""error_repair probe 公平性重評：53/55 既有 error_repair 是 pre-cutover 舊付費裁判評的，
不能與 gold（本地 panel 8.5-9）直接比。在現行本地 panel 重評 6 個 error_repair 對。

問題：error_repair（by-construction 自包含 instruction + 真實修復 output）在本地 panel 過不過 8.0？
- 過 → error_repair 是 block1 yield 來源（但母體上限僅 ~63 session）。
- 不過 → 確認 output 不是答案形狀是跨路徑的共同牆。
非破壞：只 _collect_votes。
"""
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from layer_2_chamber.backend.services.multi_judge import _collect_votes, _APPROVED_THRESHOLD
from layer_2_chamber.backend.services.teacher_service import get_active_teachers, is_quota_available

conn = sqlite3.connect("data/shiba-brain.db")
conn.row_factory = sqlite3.Row
available = [t for t in get_active_teachers(conn) if is_quota_available(conn, t)]
print(f"judges: {[t['name'] for t in available]} 門檻={_APPROVED_THRESHOLD}\n")

rows = conn.execute(
    "SELECT id, instruction, output, score, adapter_block FROM training_samples "
    "WHERE source='error_repair' AND output IS NOT NULL AND output!='' "
    "ORDER BY score DESC LIMIT 6"
).fetchall()

ge8 = 0
for r in rows:
    votes = _collect_votes(conn, r['id'], r['instruction'], "", r['output'], available)
    avg = sum(v['score'] for v in votes)/len(votes) if votes else 0
    ok = avg >= _APPROVED_THRESHOLD
    ge8 += ok
    print(f"id={r['id']} blk={r['adapter_block']} 舊score={round(r['score'],1) if r['score'] else None} → 本地panel avg={round(avg,1)} {'OK>=8' if ok else ''}")
    print(f"  instr : {r['instruction'][:70]!r}")
    print(f"  output: {(r['output'] or '')[:75]!r}")

print(f"\n結論：{ge8}/{len(rows)} 個 error_repair 在本地 panel 過 8.0")
conn.close()
