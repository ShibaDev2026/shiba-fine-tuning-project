"""local_scanner.py — 掃描本機已安裝模型（Ollama + LM Studio）→ deep 補強 + 標 is_local_installed。

職責（SRP）：偵測本機安裝狀態並萃取深層規格，再回填到遠端 catalog。
- scan_ollama_installed：GET /api/tags（清單）+ POST /api/show（深層），host 取自 CONFIG（DIP）。
- scan_lms_installed：lms ls --json（LM Studio 模型來源即 HuggingFace，故 source='huggingface'）。
- enrich_catalog：本機模型比對 catalog → 命中升級 deep + is_local_installed；本機獨有補一列 deep。

設計取捨：
- 不重用 OllamaClient：那是 generate + 寫 ai_api_call_logs 的職責，與唯讀目錄探查不同 SRP。
- raw_metadata 丟棄 ollama show 的 'tensors'（巨大 per-layer dump，對選型無價值）。
- I/O 失敗（Ollama 未啟動 / lms 不可用）→ 印警告（非靜默）並回 []，不讓本機掃描失敗拖垮遠端 catalog。
- Ollama 多 tag 對映同一 library slug：標 installed，深層欄位 first-match-wins（catalog 為 slug 粒度）。
"""

from __future__ import annotations

import json
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass

from shiba_config import CONFIG

from .store import ModelRecord

# LM Studio type → HF pipeline 風格 usage 對映
_LMS_TYPE_USAGE = {"llm": "text-generation", "embedding": "feature-extraction"}


@dataclass
class LocalModel:
    """本機已安裝模型的深層資訊（scan_* 產出，enrich_catalog 消費）。"""

    source: str                          # 'ollama' | 'huggingface'(LM Studio)
    match_name: str                      # 比對 catalog 的鍵（ollama: base slug；hf: repo id）
    display_name: str                    # 完整本機名（ollama: name:tag；lms: modelKey）
    author: str | None = None
    usage: str | None = None
    model_format: str | None = None
    param_size: str | None = None
    context_length: int | None = None
    file_size_bytes: int | None = None
    quantization: str | None = None
    raw_metadata: str | None = None      # 全量 JSON（已丟 tensors）


# ----------------------------------------------------------------
# Ollama 掃描（HTTP API）
# ----------------------------------------------------------------


def _default_host() -> str:
    return CONFIG.services.ollama_base_url.rstrip("/")


def _http_get_json(url: str, timeout: int = 5) -> dict:
    with urllib.request.urlopen(url, timeout=timeout) as r:  # noqa: S310（CONFIG 提供的本地 host）
        return json.loads(r.read().decode("utf-8", "replace"))


def _http_post_json(url: str, payload: dict, timeout: int = 15) -> dict:
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310
        return json.loads(r.read().decode("utf-8", "replace"))


def scan_ollama_installed(host=None, fetch_tags=None, fetch_show=None) -> list[LocalModel]:
    """GET /api/tags + 逐模型 POST /api/show → LocalModel list。

    fetch_tags() -> dict、fetch_show(name) -> dict 可注入（測試免網路）。
    Ollama 未啟動 → 印警告回 []（不拖垮遠端 catalog 紀錄）。
    """
    host = host or _default_host()
    if fetch_tags is None:
        def _default_fetch_tags():
            return _http_get_json(host + "/api/tags")
        fetch_tags = _default_fetch_tags
    if fetch_show is None:
        def _default_fetch_show(name):
            return _http_post_json(host + "/api/show", {"name": name})
        fetch_show = _default_fetch_show

    try:
        tags = fetch_tags()
    except (urllib.error.URLError, OSError) as e:
        print(f"[local_scanner] Ollama /api/tags 無法連線，跳過 Ollama 掃描：{e}", file=sys.stderr)
        return []

    out: list[LocalModel] = []
    for m in tags.get("models", []):
        name = m.get("name") or m.get("model")
        if not name:
            continue
        details = m.get("details") or {}
        ctx, raw, usage = None, None, None
        try:  # 單一模型 show 失敗不影響其他
            show = fetch_show(name)
            ctx = _ollama_context_length(show.get("model_info") or {})
            usage = ", ".join(show.get("capabilities") or []) or None
            show.pop("tensors", None)
            raw = json.dumps(show, ensure_ascii=False)
        except (urllib.error.URLError, OSError) as e:
            print(f"[local_scanner] Ollama /api/show 失敗 model={name}：{e}", file=sys.stderr)
        out.append(
            LocalModel(
                source="ollama",
                match_name=name.split(":", 1)[0],        # 去 :tag → library slug
                display_name=name,
                usage=usage,
                model_format=details.get("format") or None,
                param_size=details.get("parameter_size") or None,
                context_length=ctx,
                file_size_bytes=m.get("size"),
                quantization=details.get("quantization_level") or None,
                raw_metadata=raw,
            )
        )
    return out


def _ollama_context_length(model_info: dict) -> int | None:
    """從 model_info 找 '{family}.context_length'（如 qwen3moe.context_length）。"""
    for k, v in model_info.items():
        if k.endswith(".context_length") and isinstance(v, int):
            return v
    return None


# ----------------------------------------------------------------
# LM Studio 掃描（lms ls --json）
# ----------------------------------------------------------------


def scan_lms_installed(run=None) -> list[LocalModel]:
    """lms ls --json → LocalModel list（source='huggingface'）。

    run(args) -> stdout str 可注入（測試免 subprocess）。lms 不可用 → 印警告回 []。
    """
    if run is None:
        run = _run_lms_ls
    try:
        items = json.loads(run(["lms", "ls", "--json"]))
    except (FileNotFoundError, OSError, json.JSONDecodeError, subprocess.SubprocessError) as e:
        print(f"[local_scanner] lms ls 不可用，跳過 LM Studio 掃描：{e}", file=sys.stderr)
        return []

    out: list[LocalModel] = []
    for it in items:
        key = it.get("indexedModelIdentifier") or it.get("modelKey") or it.get("path")
        if not key:
            continue
        quant = it.get("quantization")
        out.append(
            LocalModel(
                source="huggingface",                        # LM Studio 模型源即 HF
                match_name=key,
                display_name=it.get("modelKey") or key,
                author=it.get("publisher") or None,
                usage=_LMS_TYPE_USAGE.get(it.get("type"), it.get("type")),
                model_format=it.get("format") or None,
                param_size=it.get("paramsString") or None,
                context_length=it.get("maxContextLength"),
                file_size_bytes=it.get("sizeBytes"),
                quantization=(quant.get("name") if isinstance(quant, dict) else None),
                raw_metadata=json.dumps(it, ensure_ascii=False),
            )
        )
    return out


def _run_lms_ls(args: list[str]) -> str:
    proc = subprocess.run(args, capture_output=True, text=True, timeout=30)
    return proc.stdout


# ----------------------------------------------------------------
# 整合：本機 → catalog 回填
# ----------------------------------------------------------------


def scan_all_installed(host=None) -> list[LocalModel]:
    """Ollama + LM Studio 本機模型合一（runner 便利入口）。"""
    return scan_ollama_installed(host=host) + scan_lms_installed()


def enrich_catalog(catalog: list[ModelRecord], locals_: list[LocalModel]) -> list[ModelRecord]:
    """本機模型回填 catalog：命中升級 deep + is_local_installed；本機獨有補 deep 列。

    回傳新 list（命中的 catalog 物件就地升級，本機獨有列追加於後）。
    """
    idx = {(r.source, r.name): r for r in catalog}
    result = list(catalog)
    for lm in locals_:
        rec = idx.get((lm.source, lm.match_name))
        if rec is not None:
            rec.is_local_installed = 1
            rec.detail_level = "deep"
            # first-match-wins：只補 catalog 尚缺的深層欄位（不覆蓋遠端既有值）
            if rec.context_length is None:
                rec.context_length = lm.context_length
            if rec.file_size_bytes is None:
                rec.file_size_bytes = lm.file_size_bytes
            if rec.quantization is None:
                rec.quantization = lm.quantization
            if rec.param_size is None:
                rec.param_size = lm.param_size
            if rec.usage is None:
                rec.usage = lm.usage
            if rec.local_raw_metadata is None:
                rec.local_raw_metadata = lm.raw_metadata
        else:
            new_rec = ModelRecord(
                source=lm.source,
                name=lm.display_name,                # 本機獨有 → 用完整本機名
                detail_level="deep",
                author=lm.author,
                source_url=_local_source_url(lm),
                usage=lm.usage,
                model_format=lm.model_format,
                param_size=lm.param_size,
                context_length=lm.context_length,
                file_size_bytes=lm.file_size_bytes,
                quantization=lm.quantization,
                is_local_installed=1,
                local_raw_metadata=lm.raw_metadata,
            )
            result.append(new_rec)
            idx[(lm.source, lm.match_name)] = new_rec    # 同鍵後續者改走 enrich，不重複追加
    return result


def _local_source_url(lm: LocalModel) -> str | None:
    if lm.source == "ollama":
        return "https://ollama.com/library/" + lm.match_name
    if lm.source == "huggingface":
        return "https://huggingface.co/" + lm.match_name
    return None


__all__ = [
    "LocalModel",
    "scan_ollama_installed",
    "scan_lms_installed",
    "scan_all_installed",
    "enrich_catalog",
]
