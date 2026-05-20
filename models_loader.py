"""Model yaml 載入器 — 全專案 model 配置的單一入口。

設計與 shiba_config.py 一致：
- frozen dataclass，禁止 runtime 修改
- module-level singleton MODELS
- import 即載入；缺欄位 fail-fast

使用範例：

    from models_loader import MODELS

    # 列出所有 yaml
    for m in MODELS.list_all():
        print(m.stem, m.display_name)

    # 取某 role 的所有可選 model（給前端 dropdown）
    classifiers = MODELS.by_role("classifier")

    # 由 DB router_config 拿到 stem 後反查
    cfg = MODELS.get_by_stem("classifier-gemma3-4b")
    ollama_tag = cfg.ollama_tag                  # "gemma3:4b"
    think      = cfg.inference.think             # False
    sys_prompt = cfg.prompt.system               # "你是嚴格的事件分類器…"

設計原則：
- 一份 yaml = 一個 model × 一個 role；同 model 多 role 寫多份
- 檔名 stem 即識別字串（DB 存 stem）：例 "classifier-gemma3-4b"
- 推論型 yaml（classifier/compressor/responder/embedder）必填 ollama_tag、inference、prompt
- 訓練型 yaml（training_base）必填 hf_repo、training；不應有 inference 區塊
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import yaml

# ----------------------------------------------------------------
# 常量
# ----------------------------------------------------------------

# role enum：與 yaml 內 role 欄位 + DB router_config key 對齊
_VALID_ROLES: frozenset[str] = frozenset(
    ["classifier", "compressor", "responder", "embedder", "training_base"]
)

# 推論型 role 必填 ollama_tag；訓練型 role 必填 hf_repo
_INFERENCE_ROLES: frozenset[str] = frozenset(
    ["classifier", "compressor", "responder", "embedder"]
)
_TRAINING_ROLES: frozenset[str] = frozenset(["training_base"])

_Role = Literal["classifier", "compressor", "responder", "embedder", "training_base"]


# ----------------------------------------------------------------
# 型別定義（全為 frozen dataclass，呼叫端只讀）
# ----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class InferenceConfig:
    """Ollama /api/generate 與 /api/chat 帶入的推論參數。"""

    think: bool
    num_ctx: int
    temperature: float
    top_p: float
    top_k: int
    repeat_penalty: float
    num_predict: int
    stop: tuple[str, ...]
    keep_alive: str
    timeout_seconds: int


@dataclass(frozen=True, slots=True)
class PromptConfig:
    """系統提示與使用者 template；user_template=None 表示由呼叫端組裝。"""

    system: str | None
    user_template: str | None


@dataclass(frozen=True, slots=True)
class TrainingConfig:
    """Layer 3 LoRA 訓練參數，取代 mlx_trainer.py 內的 _LORA_CONFIG。"""

    blocks: tuple[int, ...]
    num_layers: int
    learning_rate: float
    batch_size: int
    iters: int
    lora_rank_cold: int
    lora_rank_warm: int
    chat_template: str


@dataclass(frozen=True, slots=True)
class MetaConfig:
    """模型元資料（顯示 + 硬體適配 + 多模態 flag）。

    parameters_b / format 僅 training_base 使用；推論型留 None。
    """

    family: str
    quantization: str | None
    size_gb: float | None
    min_ram_gb: int | None
    supports_thinking: bool
    supports_vision: bool
    supports_audio: bool
    parameters_b: float | None
    format: str | None


@dataclass(frozen=True, slots=True)
class MaintenanceConfig:
    """yaml 維護資訊。"""

    yaml_version: int
    added_at: str
    notes: str


@dataclass(frozen=True, slots=True)
class ModelConfig:
    """單一 yaml 的完整內容。

    依 role 不同，inference / prompt 與 training 互斥：
    - 推論型（classifier/compressor/responder/embedder）：inference + prompt 必有，training 為 None
    - 訓練型（training_base）：training 必有，inference + prompt 為 None
    """

    stem: str                              # 檔名去 .yaml；DB router_config 存此值
    role: _Role
    display_name: str
    description: str
    ollama_tag: str | None                 # 推論型必填
    hf_repo: str | None                    # 訓練型必填
    inference: InferenceConfig | None
    prompt: PromptConfig | None
    training: TrainingConfig | None
    meta: MetaConfig
    maintenance: MaintenanceConfig

    @property
    def is_inference(self) -> bool:
        return self.role in _INFERENCE_ROLES

    @property
    def is_training(self) -> bool:
        return self.role in _TRAINING_ROLES


# ----------------------------------------------------------------
# 載入 + 驗證邏輯
# ----------------------------------------------------------------


def _models_dir() -> Path:
    """yaml 目錄 = config/models/；本檔位於專案根，往下找 config/models/。"""
    return Path(__file__).resolve().parent / "config" / "models"


def _require(mapping: dict[str, Any], key: str, ctx: str) -> Any:
    """缺 key 時丟帶 yaml 路徑的 KeyError，方便除錯。"""
    if key not in mapping:
        raise KeyError(f"{ctx} 缺少必要欄位：{key}")
    return mapping[key]


def _build_inference(raw: dict[str, Any], ctx: str) -> InferenceConfig:
    """解析 inference 區塊 → InferenceConfig。"""
    return InferenceConfig(
        think=bool(_require(raw, "think", f"{ctx}.inference")),
        num_ctx=int(_require(raw, "num_ctx", f"{ctx}.inference")),
        temperature=float(_require(raw, "temperature", f"{ctx}.inference")),
        top_p=float(_require(raw, "top_p", f"{ctx}.inference")),
        top_k=int(_require(raw, "top_k", f"{ctx}.inference")),
        repeat_penalty=float(_require(raw, "repeat_penalty", f"{ctx}.inference")),
        num_predict=int(_require(raw, "num_predict", f"{ctx}.inference")),
        stop=tuple(raw.get("stop") or []),
        keep_alive=str(_require(raw, "keep_alive", f"{ctx}.inference")),
        timeout_seconds=int(_require(raw, "timeout_seconds", f"{ctx}.inference")),
    )


def _build_prompt(raw: dict[str, Any]) -> PromptConfig:
    """解析 prompt 區塊 → PromptConfig；缺欄位給 None（合法）。"""
    return PromptConfig(
        system=raw.get("system"),
        user_template=raw.get("user_template"),
    )


def _build_training(raw: dict[str, Any], ctx: str) -> TrainingConfig:
    """解析 training 區塊 → TrainingConfig。"""
    blocks_raw = _require(raw, "blocks", f"{ctx}.training")
    if not isinstance(blocks_raw, list) or not all(isinstance(b, int) for b in blocks_raw):
        raise ValueError(f"{ctx}.training.blocks 必須是 int list，實際：{blocks_raw!r}")
    return TrainingConfig(
        blocks=tuple(blocks_raw),
        num_layers=int(_require(raw, "num_layers", f"{ctx}.training")),
        learning_rate=float(_require(raw, "learning_rate", f"{ctx}.training")),
        batch_size=int(_require(raw, "batch_size", f"{ctx}.training")),
        iters=int(_require(raw, "iters", f"{ctx}.training")),
        lora_rank_cold=int(_require(raw, "lora_rank_cold", f"{ctx}.training")),
        lora_rank_warm=int(_require(raw, "lora_rank_warm", f"{ctx}.training")),
        chat_template=str(_require(raw, "chat_template", f"{ctx}.training")),
    )


def _build_meta(raw: dict[str, Any], ctx: str) -> MetaConfig:
    """解析 meta 區塊 → MetaConfig。"""
    return MetaConfig(
        family=str(_require(raw, "family", f"{ctx}.meta")),
        quantization=raw.get("quantization"),
        size_gb=float(raw["size_gb"]) if "size_gb" in raw else None,
        min_ram_gb=int(raw["min_ram_gb"]) if "min_ram_gb" in raw else None,
        supports_thinking=bool(raw.get("supports_thinking", False)),
        supports_vision=bool(raw.get("supports_vision", False)),
        supports_audio=bool(raw.get("supports_audio", False)),
        parameters_b=float(raw["parameters_b"]) if "parameters_b" in raw else None,
        format=raw.get("format"),
    )


def _build_maintenance(raw: dict[str, Any], ctx: str) -> MaintenanceConfig:
    """解析 maintenance 區塊 → MaintenanceConfig。"""
    return MaintenanceConfig(
        yaml_version=int(_require(raw, "yaml_version", f"{ctx}.maintenance")),
        added_at=str(_require(raw, "added_at", f"{ctx}.maintenance")),
        notes=str(raw.get("notes") or ""),
    )


def _validate_role(role: str, ctx: str) -> _Role:
    """驗 role 是合法 enum；不合法時 fail-fast。"""
    if role not in _VALID_ROLES:
        raise ValueError(
            f"{ctx} role={role!r} 不合法，可選：{sorted(_VALID_ROLES)}"
        )
    return role  # type: ignore[return-value]


def _validate_role_specific_fields(
    role: _Role,
    ollama_tag: str | None,
    hf_repo: str | None,
    inference: InferenceConfig | None,
    training: TrainingConfig | None,
    ctx: str,
) -> None:
    """依 role 確認必填欄位齊全 + 互斥欄位無衝突。"""
    if role in _INFERENCE_ROLES:
        if not ollama_tag:
            raise ValueError(f"{ctx} role={role} 必填 ollama_tag")
        if inference is None:
            raise ValueError(f"{ctx} role={role} 必填 inference 區塊")
        if training is not None:
            raise ValueError(f"{ctx} role={role} 不應有 training 區塊（訓練型專用）")
    elif role in _TRAINING_ROLES:
        if not hf_repo:
            raise ValueError(f"{ctx} role={role} 必填 hf_repo")
        if training is None:
            raise ValueError(f"{ctx} role={role} 必填 training 區塊")
        if inference is not None:
            raise ValueError(f"{ctx} role={role} 不應有 inference 區塊（推論型專用）")


def _load_one(yaml_path: Path) -> ModelConfig:
    """載入單一 yaml 檔，回傳 ModelConfig；任何欄位錯誤 fail-fast。"""
    ctx = f"config/models/{yaml_path.name}"
    with yaml_path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    role = _validate_role(str(_require(raw, "role", ctx)), ctx)
    stem = yaml_path.stem

    # 檔名前綴必須與 role 一致（例：classifier-*.yaml 內 role 必為 classifier）
    if not stem.startswith(f"{role}-") and stem != role:
        raise ValueError(
            f"{ctx} 檔名 stem={stem!r} 與 role={role!r} 不一致；"
            f"檔名應以 '{role}-' 起頭"
        )

    inference = _build_inference(raw["inference"], ctx) if "inference" in raw else None
    prompt = _build_prompt(raw.get("prompt") or {}) if "prompt" in raw else None
    training = _build_training(raw["training"], ctx) if "training" in raw else None

    ollama_tag = raw.get("ollama_tag")
    hf_repo = raw.get("hf_repo")

    _validate_role_specific_fields(role, ollama_tag, hf_repo, inference, training, ctx)

    return ModelConfig(
        stem=stem,
        role=role,
        display_name=str(_require(raw, "display_name", ctx)),
        description=str(raw.get("description") or ""),
        ollama_tag=ollama_tag,
        hf_repo=hf_repo,
        inference=inference,
        prompt=prompt,
        training=training,
        meta=_build_meta(_require(raw, "meta", ctx), ctx),
        maintenance=_build_maintenance(_require(raw, "maintenance", ctx), ctx),
    )


# ----------------------------------------------------------------
# Singleton 容器
# ----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _ModelRegistry:
    """所有 yaml 載入後的索引；by_stem 為主索引，by_role 由 stem 反查維持單一真實值。"""

    _by_stem: dict[str, ModelConfig]

    def list_all(self) -> list[ModelConfig]:
        """回傳所有 yaml，按 stem 字典序排序（穩定輸出，方便測試）。"""
        return sorted(self._by_stem.values(), key=lambda m: m.stem)

    def by_role(self, role: str) -> list[ModelConfig]:
        """列出指定 role 的所有 yaml；給前端 dropdown 用。"""
        if role not in _VALID_ROLES:
            raise ValueError(f"role={role!r} 不合法，可選：{sorted(_VALID_ROLES)}")
        return [m for m in self.list_all() if m.role == role]

    def get_by_stem(self, stem: str) -> ModelConfig:
        """由 DB router_config 存的 stem 反查；查不到時 fail-fast。"""
        if stem not in self._by_stem:
            raise KeyError(
                f"找不到 model yaml stem={stem!r}；現有：{sorted(self._by_stem)}"
            )
        return self._by_stem[stem]

    def stems_by_role(self, role: str) -> list[str]:
        """純 stem 清單，給 API 層輕量回應用。"""
        return [m.stem for m in self.by_role(role)]


def _load_all() -> _ModelRegistry:
    """掃 config/models/*.yaml 全部載入；同 stem 重複時 fail-fast。"""
    models_dir = _models_dir()
    if not models_dir.is_dir():
        raise FileNotFoundError(f"找不到 model yaml 目錄：{models_dir}")

    by_stem: dict[str, ModelConfig] = {}
    for yaml_path in sorted(models_dir.glob("*.yaml")):
        cfg = _load_one(yaml_path)
        if cfg.stem in by_stem:
            raise ValueError(f"yaml stem={cfg.stem!r} 重複定義（{yaml_path}）")
        by_stem[cfg.stem] = cfg

    if not by_stem:
        raise ValueError(f"{models_dir} 內找不到任何 .yaml；至少需 1 份")

    return _ModelRegistry(_by_stem=by_stem)


# ----------------------------------------------------------------
# Module-level singleton
# ----------------------------------------------------------------

MODELS: _ModelRegistry = _load_all()

__all__ = [
    "MODELS",
    "ModelConfig",
    "InferenceConfig",
    "PromptConfig",
    "TrainingConfig",
    "MetaConfig",
    "MaintenanceConfig",
]
