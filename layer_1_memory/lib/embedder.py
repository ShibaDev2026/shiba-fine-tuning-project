"""embedder.py — Ollama embedding API 封裝（bge-m3）

bge-m3：BAAI 多語言 embedding，dim=1024、ctx=8192；中文召回優於 nomic-embed-text。
切換日：2026-05-20；舊 nomic 向量需 backfill（exchange_embeddings 全量重 embed）。
"""

import json
import math
import urllib.request
import urllib.error

from shiba_config import CONFIG

EMBED_MODEL = "bge-m3"
EMBED_DIM   = 1024


def get_embedding(text: str, base_url: str | None = None) -> list[float] | None:
    """
    向 Ollama 請求 embedding 向量。
    base_url 未指定時依 runtime 從 CONFIG 讀取。
    Ollama 離線或失敗時回傳 None（由呼叫端 fallback 到 FTS5）。
    """
    if base_url is None:
        base_url = CONFIG.services.ollama_base_url
    payload = json.dumps({"model": EMBED_MODEL, "prompt": text}).encode()
    req = urllib.request.Request(
        f"{base_url}/api/embeddings",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            return data.get("embedding")
    except Exception:
        return None


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """計算兩個向量的餘弦相似度，範圍 [-1, 1]"""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)
