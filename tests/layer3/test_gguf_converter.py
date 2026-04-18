import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from layer_3_pipeline.gguf_converter import convert_to_gguf


def test_convert_returns_gguf_path(tmp_path):
    adapter_dir = tmp_path / "adapter"
    adapter_dir.mkdir()
    out_dir = tmp_path / "gguf"

    with patch("layer_3_pipeline.gguf_converter._run") as mock_run:
        result = convert_to_gguf(adapter_dir=adapter_dir, output_dir=out_dir, adapter_block=1)

    assert "block1" in str(result)
    assert result.suffix == ".gguf"


def test_convert_raises_on_failure(tmp_path):
    with patch("layer_3_pipeline.gguf_converter._run") as mock_run:
        mock_run.side_effect = RuntimeError("GGUF 轉換失敗（fuse，returncode=1）：error")
        with pytest.raises(RuntimeError, match="GGUF 轉換失敗"):
            convert_to_gguf(adapter_dir=tmp_path, output_dir=tmp_path, adapter_block=1)
