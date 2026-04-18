import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from layer_3_pipeline.ollama_updater import push_to_ollama


def test_push_returns_model_tag(tmp_path):
    gguf = tmp_path / "shiba-block1.gguf"
    gguf.write_bytes(b"fake")

    with patch("layer_3_pipeline.ollama_updater.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        tag = push_to_ollama(gguf_path=gguf, adapter_block=1)

    assert tag.startswith("shiba-block1:")


def test_push_raises_on_failure(tmp_path):
    gguf = tmp_path / "shiba-block1.gguf"
    gguf.write_bytes(b"fake")

    with patch("layer_3_pipeline.ollama_updater.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=1, stderr="err")
        with pytest.raises(RuntimeError, match="ollama create 失敗"):
            push_to_ollama(gguf_path=gguf, adapter_block=1)
