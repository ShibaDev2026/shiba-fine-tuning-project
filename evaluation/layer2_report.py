"""
layer2_report.py — B.4 Layer 2 Judge 可靠性報告彙整
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from layer_1_memory.lib.db import get_connection


def generate_report() -> str:
    """讀 evaluation_results + judge_agreement_logs 產報告"""
    with get_connection() as conn:
        # B.2 Kappa
        kappa_rows = conn.execute(
            """SELECT metric_value, metadata FROM evaluation_results
               WHERE phase='layer2' AND metric_name='fleiss_kappa'
               ORDER BY created_at DESC LIMIT 1"""
        ).fetchall()

        kappa = None
        kappa_meta = {}
        if kappa_rows:
            kappa = kappa_rows[0]["metric_value"]
            try:
                kappa_meta = json.loads(kappa_rows[0]["metadata"] or "{}")
            except:
                pass

        # B.3 Faithfulness
        faith_rows = conn.execute(
            """SELECT metric_value FROM evaluation_results
               WHERE phase='layer2' AND metric_name='faithfulness'"""
        ).fetchall()
        faith_scores = [r["metric_value"] for r in faith_rows]
        faith_avg = sum(faith_scores) / len(faith_scores) if faith_scores else None

        # Judge agreement logs overview
        log_cnt = conn.execute("SELECT COUNT(*) FROM judge_agreement_logs").fetchone()[0]
        sample_cnt = conn.execute(
            "SELECT COUNT(*) FROM training_samples"
        ).fetchone()[0]

    # 產報告
    lines = [
        "# Layer 2 Judge 可靠性報告",
        f"\n生成時間：{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}",
        "",
        "## B.2 Fleiss' Kappa（Judge 一致性）",
        "",
    ]

    if kappa is not None:
        lines.append(f"**κ = {kappa}**")
        lines.append("")
        if kappa >= 0.8:
            lines.append("✅ **幾乎完美一致（≥0.8）**")
        elif kappa >= 0.6:
            lines.append("✅ **實質一致（0.6-0.8）** — 三方投票共識強度足夠")
        elif kappa >= 0.4:
            lines.append("⚠️ **中等一致（0.4-0.6）** — 存在分歧，建議審查 judge 校準")
        else:
            lines.append("❌ **一致性偏低（<0.4）** — Judge 間存在系統性分歧，應檢討評分標準")

        if kappa_meta:
            lines.append("")
            lines.append("詳情：")
            lines.append(f"- 樣本數：{kappa_meta.get('n_samples', '?')}")
            lines.append(f"- 評分筆數：{kappa_meta.get('total_ratings', '?')}")
            lines.append(f"- Approved 比率：{kappa_meta.get('approved_rate', '?')}")
    else:
        lines.append("**尚無足夠資料**（需 ≥2 votes/sample）")
        lines.append("")
        lines.append(f"目前 judge_agreement_logs：{log_cnt} 筆（每筆 <2 票，無法計算）")
        lines.append("")
        lines.append("**下一步**：")
        lines.append("1. 等待 Gemini 配額重置（UTC 00:00）")
        lines.append("2. 重新評分現有樣本以累積多方投票")
        lines.append("3. 重跑 `python -m evaluation.layer2_eval --action kappa`")

    # B.3 Faithfulness
    lines.extend([
        "",
        "## B.3 RAGAS Faithfulness（輸出忠實度）",
        "",
    ])

    if faith_avg is not None:
        lines.append(f"**平均 Faithfulness = {faith_avg:.4f}**")
        lines.append("")
        lines.append(f"評估樣本數：{len(faith_scores)}")
        lines.append("")
        if faith_avg >= 0.8:
            lines.append("✅ 輸出整體忠實度高")
        elif faith_avg >= 0.6:
            lines.append("⚠️ 輸出大多忠實，但存在偏題問題")
        else:
            lines.append("❌ 輸出忠實度需改進")
    else:
        lines.append("**尚無評估資料**（需執行 B.3）")

    # 決策表
    lines.extend([
        "",
        "## 決策與建議",
        "",
        "| 檢查項 | 狀態 | 建議 |",
        "|--------|------|------|",
    ])

    kappa_status = (
        "⚠️ 待補充" if kappa is None else
        ("✅ Pass" if kappa and kappa >= 0.6 else "❌ Failed")
    )
    lines.append(f"| Kappa ≥ 0.6 | {kappa_status} | {'若 <0.4，檢討 _SCORE_PROMPT 校準' if kappa and kappa < 0.4 else ''} |")

    faith_status = (
        "⚠️ 待補充" if faith_avg is None else
        ("✅ Pass" if faith_avg and faith_avg >= 0.6 else "⚠️ Review")
    )
    lines.append(f"| Faithfulness ≥ 0.6 | {faith_status} | {'指令追蹤精準度需提升' if faith_avg and faith_avg < 0.6 else ''} |")

    lines.extend([
        "",
        "## 驗證指令",
        "",
        "```bash",
        "# 完整 100 筆樣本評估",
        "python -m evaluation.layer2_eval --action kappa",
        "",
        "# Kappa 分布",
        'sqlite3 data/shiba-brain.db "SELECT ROUND(fleiss_kappa,1) k, COUNT(*) FROM judge_agreement_logs GROUP BY k ORDER BY k"',
        "",
        "# Judge vs RAGAS 衝突樣本（高一致性但低忠實度）",
        'sqlite3 data/shiba-brain.db "SELECT sample_id, fleiss_kappa, ragas_faithfulness FROM judge_agreement_logs WHERE ragas_faithfulness < 0.5 AND fleiss_kappa > 0.7 LIMIT 10"',
        "```",
        "",
    ])

    return "\n".join(lines)


if __name__ == "__main__":
    report = generate_report()
    output_file = Path(__file__).parent / "reports" / "layer2_judge_reliability.md"
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(report, encoding="utf-8")
    print(f"✓ Report: {output_file}")
    print(report)
