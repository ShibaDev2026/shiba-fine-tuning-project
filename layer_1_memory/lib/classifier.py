"""
classifier.py — 規則型事件分類器（Phase 1）
根據訊息內容與工具使用情況，將 session 分類為 7 種 event_type。
一個 session 可同時有多個 event_type（回傳 list）。

Phase 2 起將由 Gemma E2B（max_tokens=150，JSON-only）接管分類。
"""

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .parser import ParsedSession

# ============================================================
# 分類規則定義
# 每個 event_type 對應：關鍵字清單、工具條件（可選）
# ============================================================

# 中英文關鍵字規則（不區分大小寫）
_KEYWORD_RULES: dict[str, list[str]] = {
    "debugging": [
        "error", "traceback", "exception", "stacktrace",
        "fix", "bug", "issue", "problem", "fail", "failed",
        "修復", "報錯", "錯誤", "除錯", "debug", "崩潰", "異常",
    ],
    "architecture": [
        "schema", "design", "flow", "diagram", "architecture",
        "structure", "pattern", "refactor", "rewrite",
        "架構", "設計", "流程", "重構", "模式", "規範",
    ],
    "git_ops": [
        "commit", "branch", "merge", "push", "pull", "rebase",
        "cherry-pick", "stash", "tag", "clone", "fetch",
        "git", "版控", "版本控制",
    ],
    "terminal_ops": [
        "docker", "chmod", "chown", "systemctl", "service",
        "apt", "brew", "pip", "npm", "yarn", "pnpm",
        "bash", "shell", "terminal", "cli",
        "終端機", "指令", "命令列",
    ],
    "fine_tuning_ops": [
        "mlx", "lora", "gguf", "ollama", "finetune", "fine-tune",
        "fine_tune", "training", "checkpoint", "adapter",
        "quantiz", "ggml", "llama.cpp",
        "訓練", "微調", "模型",
    ],
    "knowledge_qa": [
        "what is", "how to", "explain", "describe", "why",
        "什麼是", "如何", "說明", "解釋", "為什麼", "怎麼", "介紹",
    ],
    # code_gen 是補漏型，最後決定
}

# 工具名稱對應（有這些工具 = terminal_ops / git_ops 更確定）
_TERMINAL_TOOLS = {"Bash"}
_CODE_TOOLS = {"Write", "Edit", "NotebookEdit"}


def classify_session(session: "ParsedSession") -> list[str]:
    """
    分析 session 的所有訊息，回傳 event_type 清單（不重複）。
    規則優先順序：fine_tuning_ops > debugging > git_ops >
                  terminal_ops > architecture > knowledge_qa > code_gen
    """
    # 彙整所有訊息文字（user + assistant）
    all_text = _collect_text(session)

    # 工具使用名稱集合
    used_tools: set[str] = set()
    for m in session.all_messages:
        used_tools.update(m.tool_names)

    detected: list[str] = []

    # 逐一判斷（有 code_gen 以外的 7 種）
    for event_type in [
        "fine_tuning_ops",
        "debugging",
        "git_ops",
        "terminal_ops",
        "architecture",
        "knowledge_qa",
    ]:
        if _matches_keywords(all_text, _KEYWORD_RULES[event_type]):
            detected.append(event_type)

    # git_ops 補強：有使用 Bash("git ...")
    if "git_ops" not in detected and _has_git_bash(session):
        detected.append("git_ops")

    # terminal_ops 補強：有使用 Bash tool（且非純 git）
    if "terminal_ops" not in detected and _TERMINAL_TOOLS & used_tools:
        if not _is_only_git(session):
            detected.append("terminal_ops")

    # code_gen：有大量程式碼輸出 + Write/Edit tool + 非 debugging
    if _CODE_TOOLS & used_tools and "debugging" not in detected:
        # 確認確實有 code block（``` 出現次數 > 2）
        if all_text.count("```") > 2:
            detected.append("code_gen")

    # 若完全沒偵測到 → knowledge_qa（純問答 fallback）
    if not detected:
        detected.append("knowledge_qa")

    # 去重，保持一致順序
    seen: set[str] = set()
    result: list[str] = []
    for t in detected:
        if t not in seen:
            seen.add(t)
            result.append(t)

    return result


def classify_text(text: str) -> list[str]:
    """
    直接對文字字串進行分類（供 stop_hook 快速測試用）。
    回傳 event_type 清單。
    """
    detected: list[str] = []

    for event_type in [
        "fine_tuning_ops",
        "debugging",
        "git_ops",
        "terminal_ops",
        "architecture",
        "knowledge_qa",
    ]:
        if _matches_keywords(text.lower(), _KEYWORD_RULES[event_type]):
            detected.append(event_type)

    if text.count("```") > 2 and "debugging" not in detected:
        detected.append("code_gen")

    if not detected:
        detected.append("knowledge_qa")

    return list(dict.fromkeys(detected))  # 去重保順序


# ============================================================
# 內部輔助函式
# ============================================================

def _collect_text(session: "ParsedSession") -> str:
    """彙整 active branch 所有訊息的文字內容（小寫）"""
    # 找 active branch 的訊息
    active_branch = next(
        (b for b in session.branches if b.is_active),
        None,
    )
    if active_branch:
        messages = active_branch.messages
    else:
        messages = session.all_messages

    parts = [m.content for m in messages if m.content]
    return " ".join(parts).lower()


def _matches_keywords(text: str, keywords: list[str]) -> bool:
    """檢查文字是否包含任一關鍵字（呼叫方須先 lower）"""
    return any(kw in text for kw in keywords)


def _has_git_bash(session: "ParsedSession") -> bool:
    """判斷是否有透過 Bash 執行 git 指令"""
    git_pattern = re.compile(r"\bgit\s+\w+", re.IGNORECASE)
    for m in session.all_messages:
        content = m.raw_entry.get("message", {}).get("content", [])
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_use" and block.get("name") == "Bash":
                cmd = block.get("input", {}).get("command", "")
                if git_pattern.search(cmd):
                    return True
    return False


def _is_only_git(session: "ParsedSession") -> bool:
    """判斷 Bash 工具是否只用於 git 指令（避免誤分類為 terminal_ops）"""
    git_pattern = re.compile(r"^\s*git\s+", re.IGNORECASE)
    has_non_git_bash = False
    for m in session.all_messages:
        content = m.raw_entry.get("message", {}).get("content", [])
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_use" and block.get("name") == "Bash":
                cmd = block.get("input", {}).get("command", "")
                if cmd and not git_pattern.match(cmd):
                    has_non_git_bash = True
    return not has_non_git_bash
