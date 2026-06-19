"""test_judge_confusion_matrix.py — D3 診斷的混淆矩陣算術（結論所繫，單測一個）。

驗：Shiba 標記優先於 Claude verdict、TP/FP/TN/FN 分類、TPR/TNR/precision、
   Claude 自身錨定（vs Shiba good/bad agreement）、missing GT。
import 沿用 tests/layer2 慣例（sys.path 插專案根）。
"""
import sys
from pathlib import Path

_ROOT = Path(__file__).parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts.judge_confusion_matrix import compute_confusion


def test_compute_confusion_matrix_and_anchor():
    # 7 筆涵蓋：TP/FP/TN/FN、Shiba 優先、anchor good 不合/bad 合、missing
    oracle = [
        {"sid": 1, "panel_status": "approved", "shiba_gt": "good"},  # TP（shiba good）
        {"sid": 2, "panel_status": "approved", "shiba_gt": "bad"},   # FP（shiba 拒卻放行）
        {"sid": 3, "panel_status": "rejected", "shiba_gt": None},    # TN（claude bad）
        {"sid": 4, "panel_status": "rejected", "shiba_gt": None},    # FN（claude good）
        {"sid": 5, "panel_status": "approved", "shiba_gt": None},    # missing（無 claude）
        {"sid": 6, "panel_status": "approved", "shiba_gt": "good"},  # TP；anchor good 不合
        {"sid": 7, "panel_status": "rejected", "shiba_gt": "bad"},   # TN；anchor bad 合
    ]
    verdicts = {"3": "bad", "4": "good", "6": "bad", "7": "bad"}

    r = compute_confusion(verdicts, oracle)

    assert r["matrix"] == {"TP": 2, "FP": 1, "TN": 2, "FN": 1}
    assert r["metrics"]["TPR_recall"] == round(2 / 3, 4)
    assert r["metrics"]["TNR"] == round(2 / 3, 4)
    assert r["metrics"]["precision"] == round(2 / 3, 4)
    assert r["metrics"]["n_scored"] == 6                 # missing 不計
    assert r["fp_review_candidates"] == [2]              # panel approved 但 GT bad
    assert r["fn_overkill"] == [4]                       # panel rejected 但 GT good
    assert r["missing_gt"] == [5]
    # Claude 自身錨定：sid6 shiba good/claude bad → 不合；sid7 shiba bad/claude bad → 合
    assert r["claude_self_anchor"]["vs_shiba_good_agree"] == "0/1"
    assert r["claude_self_anchor"]["vs_shiba_bad_agree"] == "1/1"
    assert r["claude_self_anchor"]["overall_agree"] == 0.5


def test_shiba_label_overrides_claude():
    # Shiba 標記必須蓋過 Claude（人類 > Claude）：shiba good 但 claude bad → 仍 good 側
    oracle = [{"sid": 10, "panel_status": "approved", "shiba_gt": "good"}]
    r = compute_confusion({"10": "bad"}, oracle)
    assert r["matrix"] == {"TP": 1, "FP": 0, "TN": 0, "FN": 0}  # GT=good(shiba) 非 bad(claude)
