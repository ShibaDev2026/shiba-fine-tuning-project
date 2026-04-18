# layer_3_pipeline/mlx_trainer.py
"""MLX LoRA 訓練器：呼叫 mlx_lm.lora CLI 執行訓練"""

import subprocess
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_LORA_CONFIG = {
    "num_layers": 16,
    "learning_rate": 1e-4,
    "iters": 600,
    "batch_size": 4,
}

BASE_MODELS = {
    1: "mlx-community/Qwen2.5-7B-Instruct-4bit",
    2: "mlx-community/Qwen2.5-7B-Instruct-4bit",
}


def train_lora(
    dataset_path: Path,
    adapter_block: int,
    output_dir: Path,
) -> Path:
    """
    執行 MLX LoRA fine-tune。
    回傳 adapter 目錄 Path；失敗時 raise RuntimeError。
    """
    adapter_dir = output_dir / f"block{adapter_block}"
    adapter_dir.mkdir(parents=True, exist_ok=True)

    model = BASE_MODELS[adapter_block]
    cmd = [
        "python", "-m", "mlx_lm.lora",
        "--model", model,
        "--train",
        "--data", str(dataset_path.parent),  # mlx_lm 讀目錄下的 train.jsonl
        "--adapter-path", str(adapter_dir),
        "--num-layers", str(_LORA_CONFIG["num_layers"]),
        "--learning-rate", str(_LORA_CONFIG["learning_rate"]),
        "--iters", str(_LORA_CONFIG["iters"]),
        "--batch-size", str(_LORA_CONFIG["batch_size"]),
    ]

    logger.info("開始 MLX 訓練 block%d：%s", adapter_block, " ".join(cmd))
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        raise RuntimeError(f"MLX 訓練失敗（returncode={result.returncode}）：{result.stderr[:500]}")

    logger.info("MLX 訓練完成，adapter → %s", adapter_dir)
    return adapter_dir
