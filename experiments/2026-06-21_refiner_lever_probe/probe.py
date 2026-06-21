"""no-regret 實驗：refiner 能否把失敗模式②（不自足 instruction）改寫成自包含、
從而抬高 judge 分數過門檻？驗 refiner 這個既有槓桿對 fine-tuning yield 是否有效。

只讀 DB（取真實樣本），對 refiner 唯一副作用是呼叫本地 Ollama（不寫回 DB）。
"""
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from layer_2_chamber.backend.services.refiner_service import refine_sample

conn = sqlite3.connect("file:data/shiba-brain.db?mode=ro", uri=True)
conn.row_factory = sqlite3.Row

# 取代表性失敗樣本：兩種模式② + 一個雜訊①（對照 refiner 不丟雜訊）
ids = [47, 25, 32, 52]
rows = conn.execute(
    f"SELECT id, instruction, input, output, score, status FROM training_samples "
    f"WHERE id IN ({','.join('?'*len(ids))})", ids
).fetchall()
conn.close()

for r in rows:
    print("=" * 70)
    print(f"id={r['id']} 原 score={r['score']} status={r['status']}")
    print(f"  原 INSTR : {(r['instruction'] or '')[:160]!r}")
    print(f"  input 空? : {not (r['input'] or '').strip()}")
    out = refine_sample(r["instruction"], r["input"] or "", r["output"] or "")
    print(f"  qwen_available : {out['qwen_available']}")
    print(f"  refined_instruction : {out['refined_instruction']!r}")
    print(f"  expected_answer : {(out['expected_answer'] or '')[:120]!r}")
