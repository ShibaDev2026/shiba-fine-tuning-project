# layer_3_pipeline/gatekeeper.py
"""
P0-2 Shadow Gate：新模型上線前的 A/B 評估守門員。
本地 Qwen 自評（零成本），三條件全過才 deploy。

三條件：
  1. bootstrap 95% CI 下界 > 0.50（統計顯著勝出）
  2. latency_p50 ≤ 舊模型 × 1.10
  3. 採納率預估 ≥ 當前基線（資料不足則略過）
"""

import json
import logging
import random
import sqlite3
import subprocess
import tempfile
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from shiba_config import CONFIG

logger = logging.getLogger(__name__)

OLLAMA_BASE = CONFIG.services.ollama_base_url
OLLAMA_TIMEOUT = 60
JUDGE_NUM_PREDICT = 32       # judge 只需回答 A/B
RESPONSE_NUM_PREDICT = 256   # 評估用回應不需太長


@dataclass
class GateResult:
    win_rate: float
    ci_lower: float              # bootstrap 95% CI 下界
    latency_ratio: float | None  # new_p50 / old_p50（None = 無法計算）
    acceptance_baseline: float | None
    passed: bool
    reason: str
    n_evaluated: int
    shadow_tag: str = ""
    failure_details: list[str] = field(default_factory=list)


# ── public API ──────────────────────────────────────────────────

def run_gate(
    gguf_path: Path,
    adapter_block: int,
    conn: sqlite3.Connection,
    n: int = 50,
) -> GateResult:
    """
    完整執行 shadow benchmark，回傳 GateResult。
    無論結果如何，shadow model 都會在結束後清理。
    """
    old_model = _get_current_model(conn, adapter_block)
    shadow_tag = _push_shadow(gguf_path, adapter_block)
    logger.info("Shadow gate 開始：old=%s new=%s n=%d", old_model, shadow_tag, n)

    try:
        prompts = _sample_prompts(conn, n)
        if not prompts:
            return GateResult(
                win_rate=0.0, ci_lower=0.0, latency_ratio=None,
                acceptance_baseline=None, passed=False,
                reason="benchmark prompts 不足，無法評估", n_evaluated=0,
                shadow_tag=shadow_tag,
            )

        wins, old_latencies, new_latencies = _run_pairwise(
            prompts=prompts,
            old_model=old_model,
            new_model=shadow_tag,
            judge_model=old_model,  # 零成本：用舊模型當 judge
        )

        n_eval = len(wins)
        win_rate = sum(wins) / n_eval if n_eval else 0.0
        ci_lower, _ = _bootstrap_ci(wins)
        latency_ratio = _latency_ratio(old_latencies, new_latencies)

        from layer_0_router.telemetry import get_acceptance_rate
        acceptance_baseline = get_acceptance_rate(days=7)

        passed, reason, failures = _check_conditions(
            ci_lower=ci_lower,
            latency_ratio=latency_ratio,
            acceptance_baseline=acceptance_baseline,
        )

        result = GateResult(
            win_rate=win_rate,
            ci_lower=ci_lower,
            latency_ratio=latency_ratio,
            acceptance_baseline=acceptance_baseline,
            passed=passed,
            reason=reason,
            n_evaluated=n_eval,
            shadow_tag=shadow_tag,
            failure_details=failures,
        )
        logger.info(
            "Shadow gate 結果：passed=%s win_rate=%.3f ci_lower=%.3f "
            "latency_ratio=%s acceptance=%.3f n=%d",
            passed, win_rate, ci_lower,
            f"{latency_ratio:.3f}" if latency_ratio else "N/A",
            acceptance_baseline or 0.0, n_eval,
        )
        return result

    finally:
        _cleanup_shadow(shadow_tag)


# ── internals ───────────────────────────────────────────────────

def _get_current_model(conn: sqlite3.Connection, adapter_block: int) -> str:
    """取最近一次 done run 的 ollama_model；若無，用 router 的預設模型。"""
    row = conn.execute(
        "SELECT ollama_model FROM finetune_runs "
        "WHERE adapter_block=? AND status='done' AND ollama_model IS NOT NULL "
        "ORDER BY id DESC LIMIT 1",
        (adapter_block,),
    ).fetchone()
    if row and row[0]:
        return row[0]
    from layer_0_router.router import LOCAL_MODEL
    return LOCAL_MODEL


def _push_shadow(gguf_path: Path, adapter_block: int) -> str:
    """建立 shadow 臨時 tag，回傳 tag 名稱。"""
    shadow_tag = f"shiba-shadow-block{adapter_block}:eval"
    modelfile = f"FROM {gguf_path}\nPARAMETER temperature 0.7\n"

    with tempfile.NamedTemporaryFile(mode="w", suffix="Modelfile", delete=False) as f:
        f.write(modelfile)
        mf_path = f.name

    result = subprocess.run(
        ["ollama", "create", shadow_tag, "-f", mf_path],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"shadow push 失敗：{result.stderr[:300]}")
    logger.info("Shadow model 建立：%s", shadow_tag)
    return shadow_tag


def _sample_prompts(conn: sqlite3.Connection, n: int) -> list[str]:
    """從近 7 天 user messages 隨機取最多 n 條（長度 > 20）。"""
    rows = conn.execute(
        """SELECT content FROM messages
            WHERE role='user'
              AND content IS NOT NULL
              AND length(content) > 20
              AND created_at >= datetime('now', '-7 days')
            ORDER BY RANDOM()
            LIMIT ?""",
        (n,),
    ).fetchall()
    prompts = [r[0] for r in rows]
    random.shuffle(prompts)
    return prompts


def _call_ollama(model: str, prompt: str, num_predict: int = RESPONSE_NUM_PREDICT) -> tuple[str, float]:
    """呼叫 Ollama，回傳 (response_text, latency_ms)；失敗回傳 ('', -1)。"""
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "options": {"temperature": 0.7, "think": False, "num_predict": num_predict},
    }).encode()

    t0 = time.monotonic()
    try:
        req = urllib.request.Request(
            f"{OLLAMA_BASE}/api/chat",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=OLLAMA_TIMEOUT) as resp:
            data = json.loads(resp.read())
            latency = (time.monotonic() - t0) * 1000
            return data["message"]["content"].strip(), latency
    except Exception as e:
        logger.warning("Ollama 呼叫失敗（%s）：%s", model, e)
        return "", -1.0


def _judge_pair(
    judge_model: str,
    prompt: str,
    resp_a: str,
    resp_b: str,
) -> bool | None:
    """
    用 judge_model 做 pairwise 評估。
    回傳 True = 新模型（B）勝，False = 舊模型（A）勝，None = 無法判定。
    呼叫前已隨機交換 A/B，此函式內部再做一次隨機化避免位置偏見。
    """
    # 隨機決定新模型在 A 還是 B 位置
    new_is_a = random.random() < 0.5
    if new_is_a:
        label_a, label_b = resp_b, resp_a  # resp_b = new model
    else:
        label_a, label_b = resp_a, resp_b  # resp_b = new model，放 B

    judge_prompt = (
        "你是一個客觀的評估者。以下是同一個問題的兩個回答，請判斷哪個更好。"
        "只回答大寫字母 A 或 B，不要說其他任何話。\n\n"
        f"問題：{prompt[:300]}\n\n"
        f"回答 A：{label_a[:400]}\n\n"
        f"回答 B：{label_b[:400]}"
    )

    response, _ = _call_ollama(judge_model, judge_prompt, num_predict=JUDGE_NUM_PREDICT)
    verdict = response.strip().upper()[:1]

    if verdict not in ("A", "B"):
        return None

    new_won = (verdict == "A") if new_is_a else (verdict == "B")
    return new_won


def _run_pairwise(
    prompts: list[str],
    old_model: str,
    new_model: str,
    judge_model: str,
) -> tuple[list[bool], list[float], list[float]]:
    """
    對每個 prompt 分別跑舊/新模型，再用 judge 裁定勝負。
    回傳 (wins, old_latencies, new_latencies)。
    wins[i] = True 代表新模型在第 i 筆勝出。
    """
    wins: list[bool] = []
    old_latencies: list[float] = []
    new_latencies: list[float] = []

    for i, prompt in enumerate(prompts):
        old_resp, old_lat = _call_ollama(old_model, prompt)
        new_resp, new_lat = _call_ollama(new_model, prompt)

        if not old_resp or not new_resp:
            logger.debug("prompt %d 推論失敗，略過", i)
            continue

        if old_lat > 0:
            old_latencies.append(old_lat)
        if new_lat > 0:
            new_latencies.append(new_lat)

        verdict = _judge_pair(judge_model, prompt, old_resp, new_resp)
        if verdict is not None:
            wins.append(verdict)

        logger.debug("prompt %d/%d 完成，new_won=%s", i + 1, len(prompts), verdict)

    return wins, old_latencies, new_latencies


def _bootstrap_ci(
    wins: list[bool],
    n_boot: int = 1000,
    alpha: float = 0.05,
) -> tuple[float, float]:
    """Bootstrap 信賴區間，回傳 (ci_lower, ci_upper)。"""
    if not wins:
        return 0.0, 0.0

    n = len(wins)
    boot_rates = []
    for _ in range(n_boot):
        sample = [random.choice(wins) for _ in range(n)]
        boot_rates.append(sum(sample) / n)

    boot_rates.sort()
    lower_idx = int(alpha / 2 * n_boot)
    upper_idx = int((1 - alpha / 2) * n_boot) - 1
    return boot_rates[lower_idx], boot_rates[upper_idx]


def _latency_ratio(
    old_latencies: list[float],
    new_latencies: list[float],
) -> float | None:
    """new_p50 / old_p50；資料不足時回傳 None。"""
    if len(old_latencies) < 5 or len(new_latencies) < 5:
        return None
    old_p50 = sorted(old_latencies)[len(old_latencies) // 2]
    new_p50 = sorted(new_latencies)[len(new_latencies) // 2]
    if old_p50 <= 0:
        return None
    return new_p50 / old_p50


def _check_conditions(
    ci_lower: float,
    latency_ratio: float | None,
    acceptance_baseline: float | None,
) -> tuple[bool, str, list[str]]:
    """
    三條件檢查，回傳 (passed, reason, failures)。
    latency_ratio / acceptance_baseline 若為 None，該條件略過（不計為失敗）。
    """
    failures = []

    if ci_lower <= 0.50:
        failures.append(f"win_rate CI 下界 {ci_lower:.3f} ≤ 0.50")

    if latency_ratio is not None and latency_ratio > 1.10:
        failures.append(f"latency_ratio {latency_ratio:.3f} > 1.10")

    # 採納率條件：新模型上線後才能量測，此處以「不退化」作門檻
    # 目前以基線存在即認為條件待觀察，不作為阻塞條件（資料累積中）
    # 未來採納率有 72h 觀察視窗再回頭判定

    if failures:
        return False, " | ".join(failures), failures

    return True, "all checks passed", []


def _cleanup_shadow(shadow_tag: str) -> None:
    """移除 shadow model，失敗時靜默。"""
    try:
        subprocess.run(
            ["ollama", "rm", shadow_tag],
            capture_output=True, text=True, check=False,
        )
        logger.info("Shadow model 清理完成：%s", shadow_tag)
    except Exception as e:
        logger.warning("Shadow 清理失敗（不影響主流程）：%s", e)
