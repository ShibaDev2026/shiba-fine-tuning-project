"""
Step 4 輔助 — 由 outputs_{A,B,C}.csv 產出：
  1. labels_template.csv：90 列 (sample × config)，待 Shiba 填 accepted / failure_mode
  2. review.md：三層並排的人類可讀檢視，標註時對照用

判準（寫在 review.md 頂部）：「若此刻 Qwen 直接給我這指令、我會不會原樣執行」。
failure_mode 列舉：placeholder_unfilled / role_confusion / thinking_leak /
                   format_error / wrong_command / hallucination / ok
"""
from __future__ import annotations

import csv
from pathlib import Path

HERE = Path(__file__).parent
CONFIGS = ["A", "B", "C"]
TEMPLATE_CSV = HERE / "labels_template.csv"
REVIEW_MD = HERE / "review.md"

FAILURE_MODES = (
    "ok / placeholder_unfilled / role_confusion / thinking_leak / "
    "format_error / wrong_command / hallucination"
)


def load(config: str) -> dict[str, dict]:
    path = HERE / f"outputs_{config}.csv"
    with path.open(encoding="utf-8") as f:
        return {r["sample_id"]: r for r in csv.DictReader(f)}


def main() -> None:
    data = {c: load(c) for c in CONFIGS}
    sample_ids = sorted(data["A"].keys(), key=int)

    # 1. labels_template.csv
    with TEMPLATE_CSV.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["sample_id", "config", "accepted", "failure_mode", "note"])
        for sid in sample_ids:
            for c in CONFIGS:
                w.writerow([sid, c, "", "", ""])
    print(f"✓ {TEMPLATE_CSV}（{len(sample_ids) * len(CONFIGS)} 列待標）")

    # 2. review.md
    lines = [
        "# Ablation 標註檢視（三層並排）",
        "",
        "**判準**：若此刻 Qwen 直接給我這指令、我會不會**原樣執行**（不是「完美」而是「我敢跑」）。",
        "",
        f"**failure_mode**：{FAILURE_MODES}",
        "",
        "標註填入 `labels_template.csv`（accepted=0/1, failure_mode）。",
        "",
        "---",
        "",
    ]
    for sid in sample_ids:
        a = data["A"][sid]
        lines.append(f"## #{sid}")
        lines.append(f"- **請求**：{a['instruction']}")
        lines.append(f"- **gold（當時實跑，僅參考非標準答案）**：`{a['gold_commands']}`")
        lines.append(f"- **RAG**：source={a['rag_source']}，context={'(空)' if not a['rag_context'] else a['rag_context'][:120]}")
        lines.append("")
        for c in CONFIGS:
            r = data[c][sid]
            out = r["extracted_commands"].strip() or "(空)"
            tag = "" if r["json_ok"] == "1" else "  ⚠json_fail"
            lines.append(f"**[{c}]**{tag}")
            lines.append("```")
            lines.append(out[:600])
            lines.append("```")
        lines.append("")
        lines.append("---")
        lines.append("")
    REVIEW_MD.write_text("\n".join(lines), encoding="utf-8")
    print(f"✓ {REVIEW_MD}")


if __name__ == "__main__":
    main()
