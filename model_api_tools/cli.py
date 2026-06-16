"""cli.py — model_api_tools 的 CLI 觸發 adapter。

職責（SRP）：只負責「解析命令列參數 → 組 ScrapeParams → 呼叫 run_scrape → 印摘要」，
不含抓取 / 掃描 / SQL 邏輯（全委派 core.runner）。與 api.py 共用同一份 core（DIP）。

用法：
    python -m model_api_tools.cli --source both --start 2025-06-01 --end 2026-06-15
    python -m model_api_tools.cli --source ollama --max-records 50 --dry-run
"""

from __future__ import annotations

import argparse
import json

from .core.hf_scraper import DEFAULT_HF_FORMATS, DEFAULT_HF_WHITELIST
from .core.runner import ScrapeParams, run_scrape

# CLI --source 值 → ScrapeParams.sources tuple（hf 為 huggingface 的對外簡寫）
_SOURCE_MAP = {
    "ollama": ("ollama",),
    "hf": ("huggingface",),
    "both": ("ollama", "huggingface"),
}


def _csv_tuple(s: str | None, default: tuple) -> tuple:
    """逗號分隔字串 → 去空白 tuple；None / 空 → default。"""
    if not s:
        return default
    parts = tuple(p.strip() for p in s.split(",") if p.strip())
    return parts or default


def build_params(args: argparse.Namespace) -> ScrapeParams:
    """argparse Namespace → ScrapeParams（CLI 與 API body 對映一致）。"""
    return ScrapeParams(
        sources=_SOURCE_MAP[args.source],
        start=args.start,
        end=args.end,
        max_records=args.max_records,
        hf_whitelist=_csv_tuple(args.whitelist, DEFAULT_HF_WHITELIST),
        formats=_csv_tuple(args.formats, DEFAULT_HF_FORMATS),
        scan_local=not args.no_scan_local,
    )


def _build_parser() -> argparse.ArgumentParser:
    """組 argparse parser（單一出口，便於測試與 --help）。"""
    p = argparse.ArgumentParser(
        prog="model_api_tools.cli",
        description="觸發式爬取 Ollama / HuggingFace 模型清單，寫入 search_model_list。",
    )
    p.add_argument("--source", choices=("ollama", "hf", "both"), default="both",
                   help="爬取來源（預設 both）")
    p.add_argument("--start", default=None, help="起始日期 YYYY-MM-DD（預設今天-365d）")
    p.add_argument("--end", default=None, help="結束日期 YYYY-MM-DD（預設今天）")
    p.add_argument("--max-records", type=int, default=None, dest="max_records",
                   help="HF 每 lane（author×format）安全上限；None=不限")
    p.add_argument("--whitelist", default=None,
                   help=f"HF author 白名單，逗號分隔（預設 {','.join(DEFAULT_HF_WHITELIST)}）")
    p.add_argument("--formats", default=None,
                   help=f"HF 格式 lane，逗號分隔（預設 {','.join(DEFAULT_HF_FORMATS)}）")
    p.add_argument("--no-scan-local", action="store_true", dest="no_scan_local",
                   help="略過本機掃描 / deep enrich")
    p.add_argument("--dry-run", action="store_true", dest="dry_run",
                   help="只印解析後參數，不抓取、不寫 DB")
    return p


def _params_view(p: ScrapeParams) -> dict:
    """ScrapeParams → 可序列化 dict（dry-run / 顯示用）。"""
    return {
        "sources": list(p.sources),
        "start": p.start,
        "end": p.end,
        "max_records": p.max_records,
        "hf_whitelist": list(p.hf_whitelist),
        "formats": list(p.formats),
        "scan_local": p.scan_local,
    }


def main(argv: list[str] | None = None, *, runner=run_scrape) -> int:
    """CLI 進入點。runner 可注入（DIP / 測試免網路免 DB）。

    --dry-run：只回報「將執行什麼」，不碰網路 / DB（回傳 0）。
    """
    args = _build_parser().parse_args(argv)
    params = build_params(args)

    if args.dry_run:
        print("[dry-run] 解析參數，未執行爬取：")
        print(json.dumps(_params_view(params), ensure_ascii=False, indent=2))
        return 0

    summary = runner(params)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
