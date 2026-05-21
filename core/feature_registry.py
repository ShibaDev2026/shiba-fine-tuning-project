"""核心 Feature Registry（PR-O-1 骨架）。

每個 feature 模組透過 register(FeatureSpec(...)) 自我登記：
- name        : 顯示名稱（log / 錯誤訊息用）
- flag        : 對應 CONFIG.features.<flag> 的欄位名
- schema_files: 相對專案根的 .sql 檔列表（apply_features 時依序 executescript）
- depends_on  : 需要同時啟用的其他 feature flag 名（fail fast 不靜默 skip）
- init_fn     : schema 套完後執行的 hook（註冊 router / 起 background job 等）

PR-O-1 階段：
- 本檔僅含資料結構與 API；後續 PR-O-3 ~ -8 會把 module 註冊呼叫補上
- main.py / server.py 尚未接線（保留現有啟動流程），由後續 PR 切換

設計原則：
- SRP：本檔只負責 registry 自身語意，不知道任何 feature 細節
- DIP：主幹只依賴本檔的 register / apply_features API，不依賴任何具體 module
- OCP：新增 feature 不需改本檔，只需在 module 內呼叫 register()
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger(__name__)


# ── 型別 ─────────────────────────────────────────────────────────
# init_fn：feature schema 套完後執行的 hook；conn 由 apply_features 注入
InitFn = Callable[[sqlite3.Connection], None]


@dataclass(frozen=True, slots=True)
class FeatureSpec:
    """單一 feature 的註冊規格。"""

    name: str
    flag: str
    schema_files: tuple[str, ...] = ()
    depends_on: tuple[str, ...] = ()
    init_fn: Optional[InitFn] = None


# ── Registry 內部狀態 ────────────────────────────────────────────
# module-level singleton；reset_registry() 僅供測試使用
_REGISTRY: dict[str, FeatureSpec] = {}


def register(spec: FeatureSpec) -> None:
    """註冊一個 feature；name 重複直接拋錯（禁止覆寫，避免靜默替換）。"""
    if spec.name in _REGISTRY:
        raise ValueError(f"feature {spec.name!r} 已註冊，禁止重複")
    _REGISTRY[spec.name] = spec


def all_features() -> tuple[FeatureSpec, ...]:
    """回傳目前已註冊的全部 feature（順序依註冊順序）。"""
    return tuple(_REGISTRY.values())


def get_feature(name: str) -> FeatureSpec:
    """依 name 取 feature；不存在直接拋錯。"""
    if name not in _REGISTRY:
        raise KeyError(f"feature {name!r} 未註冊")
    return _REGISTRY[name]


def reset_registry() -> None:
    """清空 registry — 僅供測試使用，避免污染 module-level singleton。"""
    _REGISTRY.clear()


# ── 拓撲排序與套用 ──────────────────────────────────────────────
def _topo_sort(specs: list[FeatureSpec]) -> list[FeatureSpec]:
    """以 depends_on 為邊做拓撲排序；偵測循環依賴 fail fast。

    僅排序傳入的 specs；depends_on 指向未在 specs 內的 flag 不視為錯誤
    （那是 apply_features 的依賴啟用檢核責任）。
    """
    by_flag = {s.flag: s for s in specs}
    # state: 0=visiting / 1=done；未訪問為缺 key
    state: dict[str, int] = {}
    order: list[FeatureSpec] = []

    def visit(s: FeatureSpec) -> None:
        cur = state.get(s.flag, -1)
        if cur == 1:
            return
        if cur == 0:
            raise ValueError(f"feature 循環依賴於 {s.flag!r}")
        state[s.flag] = 0
        for dep_flag in s.depends_on:
            if dep_flag in by_flag:
                visit(by_flag[dep_flag])
        state[s.flag] = 1
        order.append(s)

    for s in specs:
        visit(s)
    return order


def apply_features(
    conn: sqlite3.Connection,
    enabled_flags: dict[str, bool],
    project_root: Path,
) -> list[str]:
    """依 enabled_flags 套用所有啟用的 feature；回傳實際啟用 name 清單。

    強約束：
    - feature A 啟用但其 depends_on 任一未啟用 → ValueError（不靜默 skip）
    - schema 檔缺失 → FileNotFoundError
    - init_fn 例外直接向上拋（呼叫方決定是否 rollback）

    注意：本函式不開 / 不關 transaction；由呼叫方包在自己的 with conn: 內。
    """
    enabled = [
        s for s in _REGISTRY.values() if enabled_flags.get(s.flag, False)
    ]

    # 依賴啟用檢核（提前 fail，避免套到一半發現缺依賴）
    for s in enabled:
        for dep in s.depends_on:
            if not enabled_flags.get(dep, False):
                raise ValueError(
                    f"feature {s.flag!r} 啟用但依賴 {dep!r} 未啟用"
                )

    ordered = _topo_sort(enabled)
    applied: list[str] = []
    for spec in ordered:
        for rel_path in spec.schema_files:
            sql_path = project_root / rel_path
            if not sql_path.is_file():
                raise FileNotFoundError(
                    f"feature {spec.name} schema 缺檔：{sql_path}"
                )
            conn.executescript(sql_path.read_text(encoding="utf-8"))
            logger.info("feature %s 套用 schema: %s", spec.name, rel_path)
        if spec.init_fn is not None:
            spec.init_fn(conn)
            logger.info("feature %s init_fn 完成", spec.name)
        applied.append(spec.name)
    return applied
