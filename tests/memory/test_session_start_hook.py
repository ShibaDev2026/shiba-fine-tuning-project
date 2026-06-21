# tests/memory/test_session_start_hook.py
"""session_start_hook.build_rag_query 單元測試（fallback bug 修正）"""

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "layer_1_memory"))
sys.path.insert(0, str(_PROJECT_ROOT / "layer_1_memory" / "hooks"))
sys.path.insert(0, str(_PROJECT_ROOT))

from session_start_hook import build_rag_query


def test_build_rag_query_keeps_short_prompt():
    """有 prompt 欄位時，短 prompt（如「不用」）一律用真實 prompt，不偷換成專案名"""
    query = build_rag_query({"prompt": "不用", "cwd": "/path/shiba-fine-tuning-project"})
    assert query == "不用"


def test_build_rag_query_falls_back_to_project_name_without_prompt():
    """無 prompt 欄位的 hook（PreToolUse 等）才 fallback 用 project path 目錄名"""
    query = build_rag_query({"cwd": "/path/shiba-fine-tuning-project"})
    assert query == "shiba-fine-tuning-project"
