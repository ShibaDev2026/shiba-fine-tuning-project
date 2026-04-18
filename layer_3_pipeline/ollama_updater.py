# layer_3_pipeline/ollama_updater.py
"""將 GGUF 推送至本地 Ollama（ollama create）"""

import subprocess
import logging
import tempfile
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


def push_to_ollama(gguf_path: Path, adapter_block: int) -> str:
    """
    用 Modelfile 建立 ollama model，回傳 model tag（如 shiba-block1:20260419）。
    失敗時 raise RuntimeError。
    """
    date_tag = datetime.now().strftime("%Y%m%d")
    model_tag = f"shiba-block{adapter_block}:{date_tag}"

    modelfile_content = f"FROM {gguf_path}\nPARAMETER temperature 0.7\n"

    with tempfile.NamedTemporaryFile(mode="w", suffix="Modelfile", delete=False) as f:
        f.write(modelfile_content)
        modelfile_path = f.name

    cmd = ["ollama", "create", model_tag, "-f", modelfile_path]
    logger.info("ollama create：%s", model_tag)
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        raise RuntimeError(f"ollama create 失敗（returncode={result.returncode}）：{result.stderr[:300]}")

    logger.info("Ollama 模型更新完成：%s", model_tag)
    return model_tag
