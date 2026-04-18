"""paraphrase_service.py — 同義說法生成服務

對 exchange_embeddings 中變體不足的 instruction 生成同義說法，
擴充向量空間密度，提升語意召回覆蓋率。
"""

import json
import logging

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from layer_1_memory.lib.embedder import get_embedding
from layer_1_memory.lib.db import upsert_exchange_embedding
from ..core.config import OLLAMA_BASE_URL, REFINER_MODEL, REFINER_TIMEOUT, REFINER_OPTIONS

logger = logging.getLogger(__name__)

PARAPHRASE_BATCH   = 10   # 每次最多處理幾筆 instruction
PARAPHRASE_VARIANT = 5    # 每筆生成幾種同義說法
MIN_VARIANTS       = 3    # 變體數低於此值才補充


def _call_qwen_paraphrase(instruction: str) -> list[str]:
    """
    呼叫 Qwen 生成同義說法，回傳最多 PARAPHRASE_VARIANT 個字串。
    失敗時回傳空 list。
    """
    import urllib.request, urllib.error

    prompt = (
        f"給你一個操作描述，生成 {PARAPHRASE_VARIANT} 種不同的中文說法，"
        f"語意完全相同，只是用詞不同。不要加編號或解釋，只回傳 JSON array。\n"
        f"原始：「{instruction}」\n"
        f"回傳格式：[\"說法1\", \"說法2\", ...]"
    )

    payload = json.dumps({
        "model": REFINER_MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {**REFINER_OPTIONS, "num_ctx": 1024},
    }).encode()

    req = urllib.request.Request(
        f"{OLLAMA_BASE_URL}/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
    )

    try:
        with urllib.request.urlopen(req, timeout=REFINER_TIMEOUT) as resp:
            data = json.loads(resp.read())
            raw = data.get("response", "").strip()
            # 從回應中抽取 JSON array
            start = raw.find("[")
            end   = raw.rfind("]") + 1
            if start == -1 or end == 0:
                return []
            variants = json.loads(raw[start:end])
            return [v for v in variants if isinstance(v, str) and v.strip()][:PARAPHRASE_VARIANT]
    except Exception as e:
        logger.debug("Qwen paraphrase 呼叫失敗：%s", e)
        return []


def paraphrase_sparse_instructions(conn_factory) -> dict:
    """
    掃描 exchange_embeddings，對變體數 < MIN_VARIANTS 的 instruction 補充同義說法。
    conn_factory：呼叫後回傳 Layer 1 sqlite3.Connection（shiba-brain.db）
    """
    conn = conn_factory()
    try:
        # 只抓原始 instruction（source_instruction IS NULL），避免對 paraphrase 再 paraphrase
        rows = conn.execute("""
            SELECT e.instruction, e.commands, e.session_uuid,
                   COUNT(p.id) AS variant_count
            FROM exchange_embeddings e
            LEFT JOIN exchange_embeddings p ON p.source_instruction = e.instruction
            WHERE e.source_instruction IS NULL
            GROUP BY e.instruction
            HAVING variant_count < ?
            ORDER BY e.id ASC
            LIMIT ?
        """, (MIN_VARIANTS, PARAPHRASE_BATCH)).fetchall()
    finally:
        conn.close()

    if not rows:
        return {"paraphrased": 0, "variants_added": 0, "failed": 0}

    stats = {"paraphrased": 0, "variants_added": 0, "failed": 0}

    for row in rows:
        instruction  = row["instruction"]
        commands     = row["commands"]
        session_uuid = row["session_uuid"]

        variants = _call_qwen_paraphrase(instruction)
        if not variants:
            stats["failed"] += 1
            continue

        added = 0
        for variant in variants:
            vec = get_embedding(variant)
            if vec is None:
                continue
            try:
                upsert_exchange_embedding(
                    session_uuid=session_uuid,
                    instruction=variant,
                    commands=commands,
                    embedding=vec,
                    source_instruction=instruction,  # 標記來源，防止再次展開
                )
                added += 1
            except Exception as e:
                logger.debug("寫入 paraphrase embedding 失敗：%s", e)

        if added > 0:
            stats["paraphrased"] += 1
            stats["variants_added"] += added
            logger.info("instruction 補充 %d 個變體：%s", added, instruction[:50])

    return stats
