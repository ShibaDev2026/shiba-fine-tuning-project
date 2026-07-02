#!/usr/bin/env python3
"""盲評準備：results.jsonl → blind.md（無臂標籤，seed=42 洗牌）+ mapping.json（解盲用，評分前不得讀）"""
import json
import random
from pathlib import Path

HERE = Path(__file__).resolve().parent
rows = [json.loads(line) for line in (HERE / "results.jsonl").read_text(encoding="utf-8").splitlines()]
eval_set = json.loads((HERE / "eval_set.json").read_text(encoding="utf-8"))
def final_answer(text: str) -> str:
    """qwen3 thinking 混入 content 時，取最後一個 </think> 之後的最終答案；無標記則取全文"""
    if "</think>" in text:
        tail = text.rsplit("</think>", 1)[1].strip()
        return tail if tail else text  # 截斷在 thinking 內 → 保留全文供評（照實扣分）
    return text


by_q = {}
for r in rows:
    by_q.setdefault(r["qid"], {})[r["arm"]] = final_answer(r["response"])

rng = random.Random(43)  # run2 換 seed：run1 已解盲過，避免 mapping 資訊殘留
mapping = {}
lines = ["# 盲評卷（X/Y 為隨機臂，評分前不得讀 mapping.json）\n"]
for q in eval_set["questions"]:
    qid = q["id"]
    arms = ["A", "B"]
    rng.shuffle(arms)
    mapping[qid] = {"X": arms[0], "Y": arms[1]}
    lines.append(f"\n## {qid}\n**問題**：{q['question']}\n**Key facts**：{'；'.join(q['key_facts'])}\n")
    for label, arm in (("X", arms[0]), ("Y", arms[1])):
        lines.append(f"\n### 回答 {label}\n{by_q[qid][arm]}\n")

(HERE / "blind.md").write_text("\n".join(lines), encoding="utf-8")
(HERE / "mapping.json").write_text(json.dumps(mapping, ensure_ascii=False, indent=1), encoding="utf-8")
print(f"blind.md 就緒（{len(mapping)} 題）；mapping.json 已存（評分後才讀）")
