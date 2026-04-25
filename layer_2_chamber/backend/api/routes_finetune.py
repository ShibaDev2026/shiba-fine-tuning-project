# layer_2_chamber/backend/api/routes_finetune.py
"""手動觸發 fine-tune pipeline + 觸發狀態 + Ollama 狀態"""

import sqlite3
import subprocess
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
import httpx

from ..core.config import get_db
from shiba_config import CONFIG

router = APIRouter(prefix="/api/v1/finetune", tags=["finetune"])

# Layer 3 host 服務 URL（host 環境 localhost:8001，docker 環境 host.docker.internal:8001）
_L3_BASE = CONFIG.services.layer3_base_url

EBBINGHAUS_INTERVALS = [1, 2, 4, 7, 15, 30]


@router.post("/trigger/{adapter_block}")
def trigger_finetune(adapter_block: int):
    """轉發手動觸發至 Layer 3 host 服務（HTTP POST）"""
    try:
        resp = httpx.post(f"{_L3_BASE}/trigger/{adapter_block}", timeout=600)
        resp.raise_for_status()
        return resp.json()
    except httpx.ConnectError:
        raise HTTPException(status_code=503, detail="Layer 3 服務未啟動（請執行 setup_layer3_launchd.sh）")
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=502, detail=f"Layer 3 回應錯誤：{e.response.text}")


@router.get("/runs")
def list_runs(conn: sqlite3.Connection = Depends(get_db)):
    """列出最近 10 次 fine-tune run"""
    rows = conn.execute(
        "SELECT * FROM finetune_runs ORDER BY id DESC LIMIT 10"
    ).fetchall()
    return [dict(r) for r in rows]


@router.get("/trigger-status")
def trigger_status(conn: sqlite3.Connection = Depends(get_db)):
    """各 adapter block 的觸發條件狀態"""
    target = 30
    result = {}
    for block in [1, 2]:
        approved_count = conn.execute(
            "SELECT COUNT(*) FROM training_samples WHERE adapter_block=? AND status='approved'",
            (block,),
        ).fetchone()[0]

        last_run = conn.execute(
            "SELECT finished_at FROM finetune_runs WHERE adapter_block=? AND status='done' ORDER BY id DESC LIMIT 1",
            (block,),
        ).fetchone()
        last_run_at = last_run["finished_at"] if last_run else None

        days_since = None
        next_interval = None
        if last_run_at:
            try:
                last_dt = datetime.fromisoformat(last_run_at.replace(" ", "T"))
                days_since = (datetime.utcnow() - last_dt).days
                next_interval = next((d for d in EBBINGHAUS_INTERVALS if d > days_since), EBBINGHAUS_INTERVALS[-1])
            except Exception:
                pass

        result[f"block{block}"] = {
            "approved_count": approved_count,
            "target": target,
            "days_since_last_run": days_since,
            "ebbinghaus_intervals": EBBINGHAUS_INTERVALS,
            "next_interval_days": next_interval,
            "last_run_at": last_run_at,
        }

    acc = conn.execute(
        """SELECT
            SUM(CASE WHEN user_accepted=1 THEN 1 ELSE 0 END) AS accepted,
            COUNT(*) AS total
           FROM router_decisions WHERE classification='local'"""
    ).fetchone()
    total_local = acc["total"] or 0
    accepted = acc["accepted"] or 0
    result["acceptance_rate"] = round(accepted / total_local, 4) if total_local > 0 else None

    return result


@router.get("/ollama")
def ollama_status():
    """Ollama 載入中模型 + 全部模型列表"""
    loaded = []
    all_models = []

    try:
        ps = subprocess.run(["ollama", "ps"], capture_output=True, text=True, timeout=10)
        for line in ps.stdout.strip().splitlines()[1:]:
            parts = line.split()
            if parts:
                loaded.append({"name": parts[0], "size": parts[1] if len(parts) > 1 else None})
    except Exception:
        pass

    try:
        ls = subprocess.run(["ollama", "list"], capture_output=True, text=True, timeout=10)
        for line in ls.stdout.strip().splitlines()[1:]:
            parts = line.split()
            if parts:
                all_models.append({
                    "name": parts[0],
                    "size": parts[2] if len(parts) > 2 else None,
                    "modified": " ".join(parts[3:]) if len(parts) > 3 else None,
                })
    except Exception:
        pass

    return {
        "loaded_models": loaded,
        "all_models": all_models,
        "vram_used": None,
    }
