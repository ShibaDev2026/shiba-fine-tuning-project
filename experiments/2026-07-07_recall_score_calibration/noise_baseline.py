"""noise_baseline.py — 召回分數雜訊基線實驗（~$0、不依賴 Ollama）

假設待證：rag.py 的 0.35 floor 遠低於 bge-m3 語料底噪 → top-3 恆滿、無鑑別力。
方法：從 exchange_embeddings 隨機抽「跨 session 不相關配對」算 cosine → 雜訊分布；
      對照 recall_logs 全部歷史命中分數分布 → 推導校準門檻（noise p90/p95/p99）。
"""
import json
import random
import re
import sqlite3
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
DB = ROOT / "data" / "shiba-brain.db"
LOGS = ROOT / "recall_logs"

random.seed(42)

# ── 1. 抽樣不相關配對（跨 session）算雜訊 cosine 分布 ──
conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row
rows = conn.execute(
    "SELECT session_uuid, embedding FROM exchange_embeddings ORDER BY RANDOM() LIMIT 400"
).fetchall()
conn.close()

vecs = []
for r in rows:
    try:
        v = np.array(json.loads(r["embedding"]), dtype=np.float32)
        vecs.append((r["session_uuid"], v / np.linalg.norm(v)))
    except Exception:
        continue

noise_scores = []
n = len(vecs)
for _ in range(2000):
    a, b = random.sample(range(n), 2)
    if vecs[a][0] == vecs[b][0]:   # 同 session 可能真相關，跳過
        continue
    noise_scores.append(float(np.dot(vecs[a][1], vecs[b][1])))

noise = np.array(noise_scores)

# ── 2. 歷史命中分數（recall_logs 全量）──
hit_scores = []
for f in sorted(LOGS.glob("*.txt")):
    hit_scores += [float(m) for m in re.findall(r"score=([0-9.]+)", f.read_text())]
hits = np.array(hit_scores)

# ── 3. 輸出對照 ──
def pct(a, q):
    return float(np.percentile(a, q))

print(f"雜訊配對 n={len(noise)}: min={noise.min():.3f} p50={pct(noise,50):.3f} "
      f"p90={pct(noise,90):.3f} p95={pct(noise,95):.3f} p99={pct(noise,99):.3f} max={noise.max():.3f}")
print(f"歷史命中 n={len(hits)}: min={hits.min():.3f} p50={pct(hits,50):.3f} "
      f"p90={pct(hits,90):.3f} max={hits.max():.3f}")

for th in (0.35, pct(noise, 90), pct(noise, 95), pct(noise, 99), 0.70, 0.75):
    kept = (hits > th).mean() * 100
    fp = (noise > th).mean() * 100
    print(f"門檻 {th:.3f}: 保留歷史命中 {kept:5.1f}% | 雜訊誤放行 {fp:5.1f}%")
