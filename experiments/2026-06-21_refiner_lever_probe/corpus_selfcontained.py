"""修正版（advisor 指出母體錯誤）：從 9721 eligible EXCHANGES 直接抽真實乾淨自包含對，
不從 61 個已抽出樣本抽。決定 D4 配對設計形狀：

- 真實乾淨 instruction + 真實 final output 多數過 8.0 → 語料可 harvest、瓶頸是 extraction 覆蓋率（tractable）。
- 仍低分 → narrower 結論：真實 output 不是答案形狀（output 選取問題，非前提受限）。

非破壞：只 _collect_votes。instruction=user_open content、output=final_assistant content。
"""
import re
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

# 從 eligible exchanges 取 user_open 文字 + 真實 final assistant 文字
rows = conn.execute("""
    SELECT e.id, mu.content AS instr, mf.content AS output
    FROM exchanges e
    JOIN branches b  ON b.id=e.branch_id
    JOIN messages mu ON mu.id=e.user_message_id
    JOIN messages mf ON mf.id=e.final_assistant_message_id
    WHERE e.has_error=0 AND e.has_final_text=1 AND e.status='completed' AND b.decay_score>=0.3
      AND mu.content IS NOT NULL AND mu.content!=''
      AND mf.content IS NOT NULL AND mf.content!=''
""").fetchall()
print(f"eligible exchanges（有 user content + final 文字）: {len(rows)}")

noise = re.compile(r'<command-|<local-command|<bash-|\[Request interrupted|<system-reminder>|Caveat:|Implement the following plan|session_id|<task-notification|You are summarizing|Apply maximum')
frag = ('繼續', '好', 'ok', 'OK', '對', '不', '要', '是', '可以', '1', '2', '3', 'A', 'B', 'C', 'step', 'echo', 'go', 'Option')

def clean_selfcontained(t):
    t = (t or '').strip()
    if not (12 <= len(t) <= 200): return False
    if noise.search(t): return False
    if t.startswith(frag): return False
    return ('?' in t or '？' in t or '如何' in t or '怎' in t or '請' in t or
            '寫' in t or '實作' in t or '為什麼' in t or '什麼' in t)

cand = [r for r in rows if clean_selfcontained(r['instr'])]
print(f"其中『乾淨自包含』instruction: {len(cand)}（這才是語料可 harvest 上限的指標）\n")

import random
random.seed(42)
sample = random.sample(cand, min(8, len(cand)))
ge8 = 0
for r in sample:
    votes = _collect_votes(conn, r['id'], r['instr'], "", r['output'], available)
    avg = sum(v['score'] for v in votes)/len(votes) if votes else None
    crossed = avg is not None and avg >= _APPROVED_THRESHOLD
    ge8 += crossed
    print(f"ex={r['id']} → panel avg={avg} {'✓>=8' if crossed else ''}")
    print(f"  instr : {r['instr'].strip()[:65]!r}")
    print(f"  output: {r['output'].strip()[:75]!r}")

print(f"\n結論：{ge8}/{len(sample)} 個『真實語料乾淨自包含對』過 8.0（候選母體={len(cand)}，目標 30/block×2=60）")
conn.close()
