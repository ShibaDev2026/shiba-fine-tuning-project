"""paraphrase feature 模組（PR-O-7）。

對應 CONFIG.features.paraphrase_service；feature off 時 background 排程不註冊 hook，
排程 tick 內取不到 hook 即跳過 paraphrase 整段。
schema_files=()：不另建專屬表（source_instruction 在核心 exchange_embeddings）
init_fn：註冊 "paraphrase" hook → paraphrase_sparse_instructions
"""

from __future__ import annotations

import sqlite3

from core.feature_registry import FeatureSpec, register, register_hook

from .service import paraphrase_sparse_instructions


def _init(conn: sqlite3.Connection) -> None:
    register_hook("paraphrase", paraphrase_sparse_instructions)


register(
    FeatureSpec(
        name="paraphrase",
        flag="paraphrase_service",
        schema_files=(),
        depends_on=(),
        init_fn=_init,
    )
)
