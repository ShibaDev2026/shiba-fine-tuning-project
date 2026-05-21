"""advanced_compressor feature 模組（PR-O-8）。

對應 CONFIG.features.advanced_compressor；feature off → layer_0_router.compressor
走截斷 fallback；feature on → 註冊 "compress_context" hook 走 Gemma snapshot。
schema_files=()：純 service 模組，不建任何表
"""

from __future__ import annotations

import sqlite3

from core.feature_registry import FeatureSpec, register, register_hook

from .service import compress_context_advanced


def _init(conn: sqlite3.Connection) -> None:
    register_hook("compress_context", compress_context_advanced)


register(
    FeatureSpec(
        name="advanced_compressor",
        flag="advanced_compressor",
        schema_files=(),
        depends_on=(),
        init_fn=_init,
    )
)
