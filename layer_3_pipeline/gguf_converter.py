# layer_3_pipeline/gguf_converter.py
"""MLX adapter → GGUF 轉換（mlx_lm.fuse + llama.cpp convert）"""

import subprocess
import logging
from pathlib import Path

from layer_0_router._config import get_training_base_hf_repo

logger = logging.getLogger(__name__)

# base model 改從 router_config + model_registry snapshot 取得（yaml 化後唯一真相來源）。
_LLAMA_CPP_CONVERT = Path.home() / "llama.cpp" / "convert_hf_to_gguf.py"


def convert_to_gguf(adapter_dir: Path, output_dir: Path, adapter_block: int) -> Path:
    """
    1. mlx_lm.fuse：將 base model + LoRA adapter 合併為完整 HF model
    2. convert_hf_to_gguf.py：轉換為 Q8_0 GGUF
    回傳 .gguf 檔案 Path；失敗時 raise RuntimeError。
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    fused_dir = output_dir / f"block{adapter_block}_fused"
    gguf_path = output_dir / f"shiba-block{adapter_block}.gguf"

    fuse_cmd = [
        "python", "-m", "mlx_lm.fuse",
        "--model", get_training_base_hf_repo(adapter_block),
        "--adapter-path", str(adapter_dir),
        "--save-path", str(fused_dir),
        "--de-quantize",
    ]
    _run(fuse_cmd, "fuse")

    convert_cmd = [
        "python", str(_LLAMA_CPP_CONVERT),
        str(fused_dir),
        "--outfile", str(gguf_path),
        "--outtype", "q8_0",
    ]
    _run(convert_cmd, "convert")

    logger.info("GGUF 轉換完成：%s", gguf_path)
    return gguf_path


def _run(cmd: list[str], stage: str) -> None:
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"GGUF 轉換失敗（{stage}，returncode={result.returncode}）：{result.stderr[:500]}")
