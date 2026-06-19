"""test_ragas_uuid_metrics.py — Bug 2 regression：uuid_recall/precision 不因重複 UUID over-count。

_compute_uuid_metrics 是純函式，但 ragas_runner 頂層 import rag/teacher_service（重依賴）；
以 importlib file-path 載入該模組並只取純函式，避免測試被無關依賴鏈卡住。
"""
import importlib.util
import sys
from pathlib import Path

_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def _load_compute_uuid_metrics():
    path = _ROOT / "modules" / "ragas" / "ragas_runner.py"
    spec = importlib.util.spec_from_file_location("_ragas_runner_under_test", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod._compute_uuid_metrics


def test_uuid_recall_no_overcount_on_duplicate_retrieved():
    """retrieved 含重複 UUID：舊 code hits=list→recall=4/2=2.0；修後集合交集→1.0。"""
    compute = _load_compute_uuid_metrics()
    m = compute(["A", "A", "A", "B"], ["A", "B"])  # A 重複 3 次、gt={A,B}
    assert m["uuid_recall"] == 1.0          # 舊 code 會給 2.0（over-count）
    assert m["uuid_recall"] <= 1.0
    assert m["uuid_precision"] <= 1.0       # 去重 ret_set={A,B} → 2/2=1.0
    assert m["uuid_precision"] == 1.0


def test_uuid_metrics_normal_case_unchanged():
    """無重複的正常案例：修法不改變既有正確結果（防 regression）。"""
    compute = _load_compute_uuid_metrics()
    m = compute(["A", "C"], ["A", "B"])     # 召回 {A,C}、gt={A,B}，命中 A
    assert m["uuid_recall"] == 0.5          # 1 命中 / 2 gt
    assert m["uuid_precision"] == 0.5       # 1 命中 / 2 retrieved
    assert m["hit@1"] == 1.0                # ret[0]=A 在 gt
    assert m["mrr"] == 1.0                  # 第 1 名命中


def test_uuid_metrics_empty_ground_truth():
    """gt 為空 → 全 None（既有契約不變）。"""
    compute = _load_compute_uuid_metrics()
    m = compute(["A"], [])
    assert m["uuid_recall"] is None
