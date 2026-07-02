"""session_stop_hook._write_exchange_embeddings 寫入層去噪測試。

驗證 per-message 路徑會過濾過短會話控制詞/決策碎片（≤15 字），
避免 junk instruction 入庫 → 召回 cosine=1.0 自我命中、污染日誌。
"""

from types import SimpleNamespace
from unittest.mock import patch

from layer_1_memory.hooks.session_stop_hook import _write_exchange_embeddings


def _msg(uuid: str, role: str, content: str) -> SimpleNamespace:
    return SimpleNamespace(uuid=uuid, role=role, content=content)


def test_short_instruction_not_ingested_long_kept():
    """≤15 字的會話控制詞（merge）不入庫；>15 字的真實指令入庫。"""
    messages = [
        _msg("u1", "user", "merge"),                       # 5 字 junk → 應跳過
        _msg("a1", "assistant", ""),                       # 後接執行指令
        _msg("u2", "user", "請幫我重構整個資料流節點並更新對應索引路徑"),  # >15 字 → 應寫入
        _msg("a2", "assistant", ""),
    ]
    active_branch = SimpleNamespace(messages=messages)
    parsed = SimpleNamespace(tool_executions=[
        {"tool_name": "Bash", "input_cmd": '{"command": "git merge"}', "message_uuid": "a1"},
        {"tool_name": "Bash", "input_cmd": '{"command": "grep -rn flow"}', "message_uuid": "a2"},
    ])

    written: list[str] = []

    def fake_upsert(*, session_uuid, instruction, commands, embedding, **kw):
        written.append(instruction)

    with patch("layer_1_memory.lib.embedder.get_embedding", return_value=[0.1, 0.2, 0.3]), \
         patch("layer_1_memory.lib.db.upsert_exchange_embedding", side_effect=fake_upsert):
        _write_exchange_embeddings("sess-test", parsed, active_branch)

    # merge（≤15）絕不入庫；長指令入庫
    assert "merge" not in written
    assert any("重構整個資料流" in w for w in written)


def test_pure_qa_ingested_with_answer():
    """純問答（無工具）現在會入庫，commands 為空、answer 帶回答。"""
    messages = [
        _msg("u1", "user", "D4 灌水是什麼意思？請解釋一下原理"),   # >15 字、純問答
        _msg("a1", "assistant", "D4 指的是 branch membership 錯亂導致同段對話被重複切片。"),
    ]
    active_branch = SimpleNamespace(messages=messages)
    parsed = SimpleNamespace(tool_executions=[])  # 無任何工具

    written: list[dict] = []

    def fake_upsert(*, session_uuid, instruction, commands, embedding, answer=None, **kw):
        written.append({"instruction": instruction, "commands": commands, "answer": answer})

    with patch("layer_1_memory.lib.embedder.get_embedding", return_value=[0.1, 0.2, 0.3]), \
         patch("layer_1_memory.lib.db.upsert_exchange_embedding", side_effect=fake_upsert):
        _write_exchange_embeddings("sess-test", parsed, active_branch)

    assert len(written) == 1
    assert "D4" in written[0]["instruction"]
    assert written[0]["commands"] == ""               # 純問答指令為空
    assert "branch membership" in (written[0]["answer"] or "")
