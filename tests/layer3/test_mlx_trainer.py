import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from layer_3_pipeline.mlx_trainer import train_lora


def test_train_lora_returns_adapter_path(tmp_path):
    dataset = tmp_path / "data.jsonl"
    dataset.write_text('{"instruction":"hi","input":"","output":"hello"}\n')

    with patch("layer_3_pipeline.mlx_trainer.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        result = train_lora(
            dataset_path=dataset,
            adapter_block=1,
            output_dir=tmp_path / "adapters",
        )

    assert "block1" in str(result)


def test_train_lora_raises_on_failure(tmp_path):
    dataset = tmp_path / "data.jsonl"
    dataset.write_text("")

    with patch("layer_3_pipeline.mlx_trainer.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=1, stderr="OOM")
        with pytest.raises(RuntimeError, match="MLX 訓練失敗"):
            train_lora(
                dataset_path=dataset,
                adapter_block=1,
                output_dir=tmp_path / "adapters",
            )
