"""Step 1（gate）：per-exchange 抽取的 yield 驗證 at scale。

擴大 corpus_selfcontained 的 n=8 → 50，量化「乾淨自包含 instruction + 同一 exchange 的真實
output」的 judge 通過率，並按 event_type→block 分布，估每 block 可成 approved 數。

gate 準則：716 × pass_rate 估算，且 block1/block2 各 >= 30 才值得建 per-exchange 路徑。
非破壞：只 _collect_votes。
"""
import json
import re
import sqlite3
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from layer_2_chamber.backend.services.multi_judge import _collect_votes, _APPROVED_THRESHOLD
from layer_2_chamber.backend.services.teacher_service import get_active_teachers, is_quota_available

BLOCK1 = {"git_ops", "terminal_ops", "code_gen"}
BLOCK2 = {"debugging", "architecture", "knowledge_qa", "fine_tuning_ops"}

def to_block(event_types_json):
    try:
        ets = json.loads(event_types_json) if event_types_json else []
    except (json.JSONDecodeError, TypeError):
        ets = []
    has1 = any(e in BLOCK1 for e in ets)
    has2 = any(e in BLOCK2 for e in ets)
    if has1 and not has2: return 1
    if has2 and not has1: return 2
    if has1 and has2: return 0  # 混合（需 per-exchange 細分，先標 0）
    return None

conn = sqlite3.connect("data/shiba-brain.db")
conn.row_factory = sqlite3.Row
available = [t for t in get_active_teachers(conn) if is_quota_available(conn, t)]
print(f"judges: {[t['name'] for t in available]} 門檻={_APPROVED_THRESHOLD}\n")

rows = conn.execute("""
    SELECT e.id, mu.content AS instr, mf.content AS output, s.event_types
    FROM exchanges e
    JOIN branches b  ON b.id=e.branch_id
    JOIN messages mu ON mu.id=e.user_message_id
    JOIN messages mf ON mf.id=e.final_assistant_message_id
    JOIN sessions s  ON s.id=e.session_id
    WHERE e.has_error=0 AND e.has_final_text=1 AND e.status='completed' AND b.decay_score>=0.3
      AND mu.content IS NOT NULL AND mu.content!='' AND mf.content IS NOT NULL AND mf.content!=''
""").fetchall()

noise = re.compile(r'<command-|<local-command|<bash-|\[Request interrupted|<system-reminder>|Caveat:|Implement the following plan|session_id|<task-notification|You are summarizing|Apply maximum')
frag = ('繼續','好','ok','OK','對','不','要','是','可以','1','2','3','A','B','C','step','echo','go','Option')
def clean_sc(t):
    t=(t or '').strip()
    if not (12<=len(t)<=200): return False
    if noise.search(t): return False
    if t.startswith(frag): return False
    return ('?' in t or '？' in t or '如何' in t or '怎' in t or '請' in t or '寫' in t or '實作' in t or '為什麼' in t or '什麼' in t)

cand = [r for r in rows if clean_sc(r['instr'])]
block_dist = Counter(to_block(r['event_types']) for r in cand)
print(f"乾淨自包含候選母體 = {len(cand)}；block 分布 = {dict(block_dist)}（1=block1, 2=block2, 0=混合, None=無）\n")

import random
random.seed(7)
sample = random.sample(cand, min(50, len(cand)))
passed = []
pass_by_block = Counter()
tot_by_block = Counter()
for i, r in enumerate(sample, 1):
    blk = to_block(r['event_types'])
    tot_by_block[blk] += 1
    votes = _collect_votes(conn, r['id'], r['instr'], "", r['output'], available)
    avg = sum(v['score'] for v in votes)/len(votes) if votes else 0
    ok = avg >= _APPROVED_THRESHOLD
    if ok:
        passed.append((r['id'], round(avg,1), blk))
        pass_by_block[blk] += 1
    print(f"[{i}/{len(sample)}] ex={r['id']} blk={blk} avg={round(avg,1)} {'OK' if ok else ''}")

n = len(sample)
rate = len(passed)/n if n else 0
print(f"\n=== 通過率：{len(passed)}/{n} = {100*rate:.1f}% ===")
print(f"按 block 通過：{dict(pass_by_block)} / 樣本 block 分布：{dict(tot_by_block)}")
print(f"\n估算（母體 {len(cand)} × 通過率）：總可成 approved ≈ {int(len(cand)*rate)}")
for b in (1,2):
    bt = block_dist.get(b,0); br = (pass_by_block.get(b,0)/tot_by_block.get(b,1)) if tot_by_block.get(b) else 0
    print(f"  block{b}: 母體 {bt} × 該 block 通過率 {100*br:.0f}% ≈ {int(bt*br)} approved（目標 30）")
print("通過樣本:", passed)
conn.close()
