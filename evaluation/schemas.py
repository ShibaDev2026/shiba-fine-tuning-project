"""RAGAS 評估三元組資料結構"""
from dataclasses import dataclass, field


@dataclass
class RetrievalSample:
    """Layer 1 召回評估用三元組"""
    query: str
    retrieved_contexts: list[str]           # 召回的 exchange 文字片段
    retrieved_session_uuids: list[str]      # 召回的 session UUID
    ground_truth_uuids: list[str] = field(default_factory=list)   # golden set 標注


@dataclass
class EvalResult:
    """單筆評估結果（對應 evaluation_results 表）"""
    run_id: str
    phase: str          # 'layer1' | 'layer2' | 'e2e'
    metric_name: str
    metric_value: float
    evaluator_model: str
    sample_id: int | None = None
    metadata: dict | None = None
