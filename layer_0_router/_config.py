"""Layer 0 三顆推論模型的執行階段設定載入器（router_config + model_registry snapshot）。

設計：
- router_config 表存「當前選擇」（key=role_model_yaml → value=stem，以及 ollama_status kill switch）
- model_registry 表存版本歷史 + JSON snapshot；同 stem 僅一筆 is_current=1
- 雙表 join：role → stem → snapshot dict
- 50ms in-process cache，hot path 多次呼叫不重打 DB；切換 model 走 invalidate_cache 即時失效
- DB miss 一律 raise RuntimeError；上層（router.py）try/except 接住自然轉 Claude，避免 silent 用過時值
"""

import json
import sqlite3
import time
from typing import Literal

from shiba_config import CONFIG

DB_PATH = CONFIG.paths.db

Role = Literal["classifier", "compressor", "responder"]

_CACHE_TTL_SEC = 0.05  # 50ms：足夠涵蓋同 request 內多次呼叫
_snapshot_cache: dict[str, tuple[float, dict]] = {}


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def load_active_snapshot(role: Role) -> dict:
    """取 role 對應的 active model snapshot（dict）。

    1. router_config[f'{role}_model_yaml'] → stem
    2. model_registry WHERE model_name=stem AND is_current=1 → snapshot JSON
    3. json.loads → dict
    """
    now = time.monotonic()
    cached = _snapshot_cache.get(role)
    if cached is not None and now - cached[0] < _CACHE_TTL_SEC:
        return cached[1]

    cfg_key = f"{role}_model_yaml"
    with _connect() as conn:
        row = conn.execute(
            "SELECT value FROM router_config WHERE key = ?", (cfg_key,)
        ).fetchone()
        if row is None:
            raise RuntimeError(
                f"router_config 缺 key={cfg_key}（lifespan sync 漏？）"
            )
        stem = row["value"]

        snap_row = conn.execute(
            "SELECT snapshot FROM model_registry "
            "WHERE model_name = ? AND is_current = 1",
            (stem,),
        ).fetchone()
        if snap_row is None:
            raise RuntimeError(
                f"model_registry 找不到 model_name={stem} is_current=1"
            )
        snap = json.loads(snap_row["snapshot"])

    _snapshot_cache[role] = (now, snap)
    return snap


def is_local_enabled() -> bool:
    """Layer 0 全域 kill switch：ollama_status='online' 才走 local。

    不 cache，避免 toggle 後遲滯（操作頻率低，每次 request 多 1 次 SELECT 可接受）。
    缺 key → False（保守 default 走 Claude）。
    """
    with _connect() as conn:
        row = conn.execute(
            "SELECT value FROM router_config WHERE key = 'ollama_status'"
        ).fetchone()
    return row is not None and row["value"] == "online"


def invalidate_cache() -> None:
    """清 snapshot cache；給 PUT /router/config 切換 model 時呼叫，或測試使用。"""
    _snapshot_cache.clear()


def get_training_base_hf_repo(adapter_block: int) -> str:
    """取 Layer 3 訓練 base 的 hf_repo（從 router_config + model_registry snapshot 解出）。

    流程：router_config[training_base_block{N}_yaml] → stem
        → model_registry.snapshot.hf_repo。
    block 1/2 各自獨立 key；訓練 key 命名為 `training_base_block{N}_yaml`，
    與推論型 `{role}_model_yaml` 不同 pattern，故走獨立查詢不重用 load_active_snapshot。
    DB miss 一律 raise RuntimeError；訓練流程是離線批次任務，hard fail 比 silent default 安全。
    """
    if adapter_block not in (1, 2):
        raise ValueError(f"adapter_block 須為 1 或 2，收到：{adapter_block!r}")

    cfg_key = f"training_base_block{adapter_block}_yaml"
    with _connect() as conn:
        row = conn.execute(
            "SELECT value FROM router_config WHERE key=?", (cfg_key,)
        ).fetchone()
        if row is None:
            raise RuntimeError(f"router_config 缺 key={cfg_key}（lifespan sync 漏？）")
        stem = row["value"]
        snap_row = conn.execute(
            "SELECT snapshot FROM model_registry WHERE model_name=? AND is_current=1",
            (stem,),
        ).fetchone()
        if snap_row is None:
            raise RuntimeError(f"model_registry 找不到 model_name={stem} is_current=1")
        snap = json.loads(snap_row["snapshot"])

    hf_repo = snap.get("hf_repo")
    if not hf_repo:
        raise RuntimeError(
            f"training_base block{adapter_block} snapshot 缺 hf_repo（yaml 是否誤用推論型 schema？）"
        )
    return hf_repo


def split_inference(inference: dict | None) -> tuple[dict, str | None, bool | None]:
    """把 yaml inference dict 拆成 (ollama_options, keep_alive, think)。

    - `keep_alive` 抽到 Ollama request body 頂層（Ollama API 規定不能放 options 內）
    - `think` 同樣抽到 body 頂層（Ollama 0.9+ 規格：think 是頂層欄位，
      放 options 內會被忽略導致 thinking-only 模型空回應）；None 代表 yaml 沒設
    - `timeout_seconds` 直接丟棄（Layer 0 client timeout 固定 30s，不吃 yaml；
      模型切換的 swap 等待由前端倒數提示處理）
    - 其餘 keys（num_ctx/temperature/top_p/top_k/repeat_penalty/num_predict/stop）
      組成 Ollama options dict
    """
    src = dict(inference or {})
    keep_alive = src.pop("keep_alive", None)
    think = src.pop("think", None)
    src.pop("timeout_seconds", None)
    return src, keep_alive, think
