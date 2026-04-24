"""shiba-fine-tuning-project 全專案設定載入器。

全專案唯一 source of truth：config/shiba.yaml
呼叫方統一入口：

    from shiba_config import CONFIG

    sqlite3.connect(CONFIG.paths.db)
    requests.get(CONFIG.services.ollama_base_url + "/api/tags")

設計原則：
- frozen dataclass，禁止 runtime 修改
- import 即載入，module-level singleton
- 所有 paths 自動轉絕對路徑，呼叫方直接使用
- 路徑/URL 缺失一律 fail fast（不提供預設值隱藏錯誤）
- Ollama / Layer 3 URL 依 SHIBA_RUNTIME 擇一暴露，呼叫方無需判斷 runtime

Runtime 判定：
- 讀 env `SHIBA_RUNTIME`；值為 'docker' 時 is_docker=True
- 未設或 'host' 時為 host 環境
- 其他值 → ValueError
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import yaml

# ----------------------------------------------------------------
# 型別定義（全為 frozen dataclass）
# ----------------------------------------------------------------

_RuntimeEnv = Literal["host", "docker"]


@dataclass(frozen=True, slots=True)
class Paths:
    """所有路徑欄位皆為絕對路徑（Path 物件）。"""

    project_root: Path
    db: Path
    logs_dir: Path
    queue_dir: Path
    backups_dir: Path
    external_dataset: Path


@dataclass(frozen=True, slots=True)
class Services:
    """服務 port 與 URL；URL 已依 runtime 擇一。"""

    backend_port: int
    frontend_port: int
    layer3_port: int
    ollama_base_url: str
    layer3_base_url: str


@dataclass(frozen=True, slots=True)
class Runtime:
    """執行環境標記。"""

    environment: _RuntimeEnv

    @property
    def is_docker(self) -> bool:
        return self.environment == "docker"


@dataclass(frozen=True, slots=True)
class _Config:
    paths: Paths
    services: Services
    runtime: Runtime


# ----------------------------------------------------------------
# 載入邏輯
# ----------------------------------------------------------------


def _project_root() -> Path:
    """專案根 = 本檔案所在目錄；host 與 docker 都靠 __file__ 自動對齊。"""
    return Path(__file__).resolve().parent


def _require(mapping: dict[str, Any], key: str, yaml_path: str) -> Any:
    """缺 key 時丟帶 yaml 路徑的 KeyError，方便除錯。"""
    if key not in mapping:
        raise KeyError(f"config/shiba.yaml 缺少必要欄位：{yaml_path}")
    return mapping[key]


def _resolve_runtime(raw: dict[str, Any]) -> _RuntimeEnv:
    """讀 SHIBA_RUNTIME env，決定 'host' / 'docker'。"""
    env_var_name = _require(raw, "environment_var", "runtime.environment_var")
    value = os.environ.get(env_var_name, "host").strip().lower()
    if value not in ("host", "docker"):
        raise ValueError(
            f"環境變數 {env_var_name}={value!r} 不合法，只接受 'host' / 'docker'"
        )
    return value  # type: ignore[return-value]


def _build_paths(raw: dict[str, Any], project_root: Path) -> Paths:
    """paths 全部以專案根為基準轉絕對路徑。"""
    return Paths(
        project_root=project_root,
        db=project_root / _require(raw, "db", "paths.db"),
        logs_dir=project_root / _require(raw, "logs_dir", "paths.logs_dir"),
        queue_dir=project_root / _require(raw, "queue_dir", "paths.queue_dir"),
        backups_dir=project_root / _require(raw, "backups_dir", "paths.backups_dir"),
        external_dataset=project_root / _require(raw, "external_dataset", "paths.external_dataset"),
    )


def _build_services(raw: dict[str, Any], is_docker: bool) -> Services:
    """Services：port 直接取；ollama/layer3 URL 依 runtime 擇一暴露。"""
    ollama_key = "ollama_base_url_docker" if is_docker else "ollama_base_url_host"
    layer3_key = "layer3_base_url_docker" if is_docker else "layer3_base_url_host"
    return Services(
        backend_port=int(_require(raw, "backend_port", "services.backend_port")),
        frontend_port=int(_require(raw, "frontend_port", "services.frontend_port")),
        layer3_port=int(_require(raw, "layer3_port", "services.layer3_port")),
        ollama_base_url=_require(raw, ollama_key, f"services.{ollama_key}"),
        layer3_base_url=_require(raw, layer3_key, f"services.{layer3_key}"),
    )


def _load_config() -> _Config:
    project_root = _project_root()
    yaml_path = project_root / "config" / "shiba.yaml"
    if not yaml_path.is_file():
        raise FileNotFoundError(f"找不到設定檔：{yaml_path}")

    with yaml_path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    runtime_raw = _require(raw, "runtime", "runtime")
    environment = _resolve_runtime(runtime_raw)

    paths_raw = _require(raw, "paths", "paths")
    services_raw = _require(raw, "services", "services")

    return _Config(
        paths=_build_paths(paths_raw, project_root),
        services=_build_services(services_raw, is_docker=(environment == "docker")),
        runtime=Runtime(environment=environment),
    )


# ----------------------------------------------------------------
# Module-level singleton
# ----------------------------------------------------------------

CONFIG: _Config = _load_config()

__all__ = ["CONFIG", "Paths", "Services", "Runtime"]
