"""
PII 後處理 — 對 outputs_{A,B,C}.csv 的文字欄位（rag_context / raw_response /
extracted_commands / instruction / gold_commands）套用 sample.redact，就地覆寫。

理由：rag_context 直接取自 DB 原始資料、模型輸出可能回放 PII；experiments/ 檔案
雖本地未提交，仍依 CLAUDE.md 硬約束去機敏。可重複執行（idempotent）。
"""
from __future__ import annotations

import csv
from pathlib import Path

from sample import redact  # 複用同一套遮罩規則

HERE = Path(__file__).parent
TEXT_COLS = ("instruction", "gold_commands", "rag_context", "raw_response", "extracted_commands")


def main() -> None:
    for cfg in ("A", "B", "C"):
        path = HERE / f"outputs_{cfg}.csv"
        if not path.exists():
            continue
        with path.open(encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            fields = reader.fieldnames
        if not fields:
            continue
        for r in rows:
            for col in TEXT_COLS:
                if col in r and r[col]:
                    r[col] = redact(r[col])
        with path.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            w.writerows(rows)
        print(f"✓ 遮罩 {path.name}（{len(rows)} 列）")


if __name__ == "__main__":
    main()
