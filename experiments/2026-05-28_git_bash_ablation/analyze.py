"""
Step 5 — 分析：讀 labels.csv（Shiba 標好）+ outputs → 採納率 / Δ 分解 / failure_mode → RESULT.md

決策樹（依 Config C 最終採納率）：
  ≥80%  → 砍 Layer 3 fine-tune，純 RAG + 大模型 + 方法論
  70-80% → 看 Δ 來源決定輕量解（B=結構化 / C=grounding），仍不需 fine-tune
  <70%  → base 能力差距 fine-tune 救不了，砍 Layer 0/2/3，留 Layer 1 + RAGAS
"""
from __future__ import annotations

import csv
from collections import Counter
from pathlib import Path

HERE = Path(__file__).parent
CONFIGS = ["A", "B", "C"]
LABELS_CSV = HERE / "labels.csv"
RESULT_MD = HERE / "RESULT.md"


def load_labels() -> list[dict]:
    if not LABELS_CSV.exists():
        raise SystemExit(f"找不到 {LABELS_CSV}——請先用 make_labels.py 產模板並由 Shiba 標註後另存為 labels.csv")
    with LABELS_CSV.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def rate(rows: list[dict], config: str) -> tuple[int, int, float]:
    sub = [r for r in rows if r["config"] == config and r["accepted"].strip() != ""]
    acc = sum(1 for r in sub if r["accepted"].strip() == "1")
    n = len(sub)
    return acc, n, (acc / n if n else 0.0)


def decide(c_rate: float, d_ab: float, d_bc: float) -> str:
    if c_rate >= 0.80:
        return "**砍 Layer 3 fine-tune**：純 RAG + 大模型 inference + 方法論已達標。保留 Layer 1 + RAGAS。"
    if c_rate >= 0.70:
        lever = "結構化（B）" if d_ab >= d_bc else "grounding（C）"
        return (f"**邊界（70-80%）**：主要貢獻來自 {lever}，採輕量解即可，**不需 fine-tune**。"
                f"保留該方法論層，砍 Layer 3 訓練。")
    return "**砍 Layer 0/2/3**：base 能力差距 fine-tune 救不了，保留 Layer 1 + RAGAS。"


def main() -> None:
    rows = load_labels()
    rates = {c: rate(rows, c) for c in CONFIGS}
    r_a, r_b, r_c = rates["A"][2], rates["B"][2], rates["C"][2]
    d_ab, d_bc = r_b - r_a, r_c - r_b

    lines = [
        "# Local Qwen 能力上限驗證 — RESULT",
        "",
        "> 實驗：git+bash 30 樣本 × 3 config ablation；標註判準「我會不會原樣執行」。",
        "> **常數**：think:false / temp 0.7 / num_ctx 8192 / RAG 三層共用。temp 0.7 單樣本有變異（limitation）。",
        "",
        "## 採納率",
        "",
        "| Config | 疊加 | 採納/有效 | 採納率 |",
        "|---|---|---|---|",
        f"| A 基線 | production 複刻 | {rates['A'][0]}/{rates['A'][1]} | {r_a:.0%} |",
        f"| B +reframe | 指令生成器+JSON | {rates['B'][0]}/{rates['B'][1]} | {r_b:.0%} |",
        f"| C +grounding | +當下 git 環境 | {rates['C'][0]}/{rates['C'][1]} | {r_c:.0%} |",
        "",
        "## Δ 分解（哪個方法論值得保留）",
        "",
        f"- A→B（角色/格式 reframe）：**{d_ab:+.0%}**",
        f"- B→C（grounding）：**{d_bc:+.0%}**",
        f"- 總提升 A→C：**{r_c - r_a:+.0%}**",
        "",
        "## failure_mode 分布",
        "",
        "| failure_mode | A | B | C |",
        "|---|---|---|---|",
    ]
    modes_by_cfg = {c: Counter(r["failure_mode"].strip() for r in rows
                               if r["config"] == c and r["failure_mode"].strip())
                    for c in CONFIGS}
    all_modes = sorted({m for cnt in modes_by_cfg.values() for m in cnt})
    for m in all_modes:
        lines.append(f"| {m} | {modes_by_cfg['A'][m]} | {modes_by_cfg['B'][m]} | {modes_by_cfg['C'][m]} |")

    lines += [
        "",
        "## 決策（依 Config C 採納率）",
        "",
        decide(r_c, d_ab, d_bc),
        "",
        "## 後續",
        "- 更新 memory [[capability-upper-bound-validation]] 為實測結論",
        "- 刪除 plan 檔 `~/.claude/plans/sorted-watching-origami.md`（CLAUDE.md：驗證完即刪）",
    ]
    RESULT_MD.write_text("\n".join(lines), encoding="utf-8")
    print(f"✓ 寫入 {RESULT_MD}")
    print(f"  A={r_a:.0%} B={r_b:.0%} C={r_c:.0%} | Δab={d_ab:+.0%} Δbc={d_bc:+.0%}")


if __name__ == "__main__":
    main()
