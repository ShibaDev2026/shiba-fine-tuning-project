"""OpenAICompatClient thinking 控制測試"""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from clients.openai_compat.client import OpenAICompatClient, _apply_thinking_control


def test_apply_thinking_control_qwen_appends_no_think():
    out = _apply_thinking_control("PROMPT", "local-qwen", True)
    assert out.endswith("/no_think")
    assert "PROMPT" in out


def test_apply_thinking_control_gemma_untouched():
    assert _apply_thinking_control("PROMPT", "local-gemma", True) == "PROMPT"


def test_apply_thinking_control_disabled_flag_off():
    assert _apply_thinking_control("PROMPT", "local-qwen", False) == "PROMPT"


def _fake_completion(content: str):
    msg = MagicMock(); msg.content = content
    choice = MagicMock(); choice.message = msg
    usage = MagicMock(); usage.prompt_tokens = 5; usage.completion_tokens = 7
    resp = MagicMock(); resp.choices = [choice]; resp.usage = usage
    return resp


def test_generate_injects_no_think_for_qwen():
    client = OpenAICompatClient(
        api_key="none", api_base="http://localhost:1234/v1", vendor="local-qwen",
    )
    fake_openai = MagicMock()
    fake_openai.chat.completions.create.return_value = _fake_completion('{"score":9,"reason":"ok"}')
    with patch("openai.OpenAI", return_value=fake_openai), \
         patch("clients.openai_compat.client.log_api_call"):
        text, _, _, status = client.generate(
            model_id="qwen3.5-27b", prompt="EVAL", disable_thinking=True,
        )
    assert status == "success"
    sent_messages = fake_openai.chat.completions.create.call_args.kwargs["messages"]
    assert "/no_think" in sent_messages[0]["content"]
