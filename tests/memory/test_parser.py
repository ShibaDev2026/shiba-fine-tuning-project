# tests/memory/test_parser.py
"""parser.py 單元測試"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "layer_1_memory"))

from lib.parser import ParsedSession, parse_jsonl


def _write_jsonl(path: Path, entries: list) -> None:
    """將 entry list 寫入 JSONL 檔案"""
    with open(path, "w", encoding="utf-8") as f:
        for entry in entries:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def test_parse_basic_session(tmp_path):
    """應正確解析 user / assistant 訊息，回傳 ParsedSession"""
    jsonl = tmp_path / "aaaaaaaa-0000-0000-0000-000000000001.jsonl"
    _write_jsonl(jsonl, [
        {
            "type": "user",
            "uuid": "u1",
            "parentUuid": None,
            "timestamp": "2026-04-15T10:00:00Z",
            "message": {"role": "user", "content": "如何使用 LoRA fine-tuning？"},
            "cwd": "/project",
            "sessionId": "aaaaaaaa-0000-0000-0000-000000000001",
        },
        {
            "type": "assistant",
            "uuid": "a1",
            "parentUuid": "u1",
            "timestamp": "2026-04-15T10:00:05Z",
            "message": {
                "role": "assistant",
                "content": [{"type": "text", "text": "LoRA 是一種低秩矩陣方法..."}],
            },
            "sessionId": "aaaaaaaa-0000-0000-0000-000000000001",
        },
    ])
    result = parse_jsonl(jsonl)

    assert result is not None
    assert isinstance(result, ParsedSession)
    assert result.exchange_count >= 1


def test_parse_empty_file_returns_none(tmp_path):
    """空檔案應回傳 None"""
    jsonl = tmp_path / "aaaaaaaa-0000-0000-0000-000000000002.jsonl"
    jsonl.write_text("")
    assert parse_jsonl(jsonl) is None


def test_parse_nonexistent_file_returns_none(tmp_path):
    """不存在的檔案應回傳 None"""
    jsonl = tmp_path / "nonexistent.jsonl"
    assert parse_jsonl(jsonl) is None


def test_parse_detects_tool_use(tmp_path):
    """含 tool_use 的 assistant 訊息應標記 has_tool_use=True"""
    jsonl = tmp_path / "aaaaaaaa-0000-0000-0000-000000000003.jsonl"
    _write_jsonl(jsonl, [
        {
            "type": "user",
            "uuid": "u1",
            "parentUuid": None,
            "timestamp": "2026-04-15T10:00:00Z",
            "message": {"role": "user", "content": "執行指令"},
            "cwd": "/project",
            "sessionId": "aaaaaaaa-0000-0000-0000-000000000003",
        },
        {
            "type": "assistant",
            "uuid": "a1",
            "parentUuid": "u1",
            "timestamp": "2026-04-15T10:00:05Z",
            "message": {
                "role": "assistant",
                "content": [
                    {"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "ls"}},
                ],
            },
            "sessionId": "aaaaaaaa-0000-0000-0000-000000000003",
        },
    ])
    result = parse_jsonl(jsonl)

    assert result is not None
    tool_msgs = [m for m in result.all_messages if m.has_tool_use]
    assert len(tool_msgs) >= 1
    assert "Bash" in tool_msgs[0].tool_names


def test_parse_detects_tool_result_in_raw_content(tmp_path):
    """raw_content 應可完整保留 json 結構，包含被忽略的 tool_result"""
    jsonl = tmp_path / "aaaaaaaa-0000-0000-0000-000000000004.jsonl"
    _write_jsonl(jsonl, [
        {
            "type": "user",
            "uuid": "u2",
            "parentUuid": None,
            "timestamp": "2026-04-15T10:00:00Z",
            "message": {
                "role": "user",
                "content": [
                    {"type": "tool_result", "tool_use_id": "t1", "content": "error line 1"}
                ]
            },
            "cwd": "/project",
            "sessionId": "aaaaaaaa-0000-0000-0000-000000000004",
        }
    ])
    result = parse_jsonl(jsonl)

    assert result is not None
    msg = result.all_messages[0]
    assert msg.content is None  # content 依舊忽略 tool_result
    assert msg.raw_content is not None
    assert "error line 1" in msg.raw_content


def test_parse_extracts_tokens_and_sizes(tmp_path):
    """驗證 parser 能正確抽取出 usage token 以計算字元數與位元組"""
    jsonl = tmp_path / "aaaaaaaa-0000-0000-0000-000000000005.jsonl"
    _write_jsonl(jsonl, [
        {
            "type": "assistant",
            "uuid": "a2",
            "parentUuid": None,
            "timestamp": "2026-04-15T10:00:00Z",
            "message": {
                "role": "assistant",
                "content": [{"type": "text", "text": "測試字串"}],
                "usage": {
                    "input_tokens": 10,
                    "output_tokens": 20,
                    "cache_creation_input_tokens": 100,
                    "cache_read_input_tokens": 50
                }
            },
            "sessionId": "aaaaaaaa-0000-0000-0000-000000000005",
        }
    ])
    result = parse_jsonl(jsonl)

    assert result is not None
    msg = result.all_messages[0]
    
    # Validation
    assert msg.input_tokens == 10
    assert msg.output_tokens == 20
    assert msg.cache_creation_input_tokens == 100
    assert msg.cache_read_input_tokens == 50
    assert msg.char_count > 0
    assert msg.byte_count >= msg.char_count
    assert msg.encoding == "utf-8"
