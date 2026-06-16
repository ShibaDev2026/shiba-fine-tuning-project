"""OpenAICompatClient thinking 控制測試"""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from clients.openai_compat.client import OpenAICompatClient, _thinking_extra_body


def test_thinking_extra_body_qwen_sets_reasoning_effort_none():
    # 實測 LM Studio：qwen3.5 唯一有效的關 thinking 機制是 reasoning_effort=none
    assert _thinking_extra_body("local-qwen", True) == {"reasoning_effort": "none"}


def test_thinking_extra_body_glm_sets_reasoning_effort_none():
    assert _thinking_extra_body("local-glm", True) == {"reasoning_effort": "none"}


def test_thinking_extra_body_gemma_empty():
    # gemma 加 reasoning_effort 反而碎念，靠 reasoning_content 分流 + token headroom
    assert _thinking_extra_body("local-gemma", True) == {}


def test_thinking_extra_body_disabled_flag_off():
    assert _thinking_extra_body("local-qwen", False) == {}


def _fake_completion(content: str):
    msg = MagicMock(); msg.content = content
    choice = MagicMock(); choice.message = msg
    usage = MagicMock(); usage.prompt_tokens = 5; usage.completion_tokens = 7
    resp = MagicMock(); resp.choices = [choice]; resp.usage = usage
    return resp


def test_generate_passes_reasoning_effort_for_qwen():
    client = OpenAICompatClient(
        api_key="none", api_base="http://localhost:1234/v1", vendor="local-qwen",
    )
    fake_openai = MagicMock()
    fake_openai.chat.completions.create.return_value = _fake_completion('{"score":9,"reason":"ok"}')
    with patch("openai.OpenAI", return_value=fake_openai), \
         patch("clients.openai_compat.client.log_api_call"):
        _, _, _, status = client.generate(
            model_id="qwen3.5-27b", prompt="EVAL", disable_thinking=True,
        )
    assert status == "success"
    sent = fake_openai.chat.completions.create.call_args.kwargs
    # prompt 不再被注入 /no_think，改由 extra_body 帶 reasoning_effort
    assert sent["messages"][0]["content"] == "EVAL"
    assert sent["extra_body"] == {"reasoning_effort": "none"}
