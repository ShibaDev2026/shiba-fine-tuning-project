"""
parser.py — 解析 Claude Code .jsonl 對話檔
輸入：~/.claude/projects/<hash>/<session-id>.jsonl
輸出：ParsedSession（含 messages、branches、統計數據）

解析邏輯：
1. 每筆 entry 含 uuid / parentUuid / type / message
2. 透過 parentUuid 建立 DAG
3. 偵測分支（葉節點不同 = rewind 發生）
4. 取最新 leaf 的路徑 = active branch
5. 計算：exchange_count / files_modified / commits / tool_counts
"""

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ============================================================
# 資料結構
# ============================================================

@dataclass
class ParsedMessage:
    """單一訊息的解析結果"""
    uuid: str
    parent_uuid: str | None
    role: str                      # 'user' | 'assistant'
    content: str | None            # 純文字內容
    has_tool_use: bool
    tool_names: list[str]
    raw_entry: dict                # 原始 JSON entry（供進階分析）


@dataclass
class ParsedBranch:
    """一條對話分支的解析結果"""
    branch_idx: int
    is_active: bool
    leaf_uuid: str | None
    messages: list[ParsedMessage]  # 按順序排列的訊息
    exchange_count: int            # user/assistant 對話回合數
    files_modified: list[str]      # 從 tool_use 解析出的修改檔案
    commits: int                   # git commit 次數


@dataclass
class ParsedSession:
    """整個 session 的解析結果"""
    session_uuid: str
    project_hash: str
    project_path: str
    branches: list[ParsedBranch]
    # 彙整統計（取 active branch 數值）
    exchange_count: int
    files_modified: int
    commits: int
    tool_counts: dict[str, int]
    all_messages: list[ParsedMessage]


# ============================================================
# 主要解析函式
# ============================================================

def parse_jsonl(jsonl_path: Path) -> ParsedSession | None:
    """
    解析單一 .jsonl 檔案，回傳 ParsedSession。
    若檔案無效或為空則回傳 None。
    """
    if not jsonl_path.exists():
        logger.warning("jsonl 檔案不存在：%s", jsonl_path)
        return None

    # 從路徑解析 session UUID 與 project hash
    session_uuid = jsonl_path.stem
    project_hash = jsonl_path.parent.name

    # 讀取所有 entries
    entries: list[dict] = []
    with open(jsonl_path, "r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError as e:
                logger.debug("第 %d 行 JSON 解析失敗：%s", line_no, e)

    if not entries:
        logger.warning("jsonl 為空：%s", jsonl_path)
        return None

    # 解析所有訊息
    messages = [_parse_entry(e) for e in entries if _is_message_entry(e)]
    messages = [m for m in messages if m is not None]

    if not messages:
        return None

    # 從 entries 取得 project path（summary entry 通常含此資訊）
    project_path = _extract_project_path(entries) or str(jsonl_path.parent)

    # 建立 DAG 並分析分支
    branches = _build_branches(messages)

    # 計算 tool_counts（全 session 彙整）
    tool_counts = _compute_tool_counts(messages)

    # 取 active branch 的統計數據
    active = next((b for b in branches if b.is_active), branches[0] if branches else None)

    return ParsedSession(
        session_uuid=session_uuid,
        project_hash=project_hash,
        project_path=project_path,
        branches=branches,
        exchange_count=active.exchange_count if active else 0,
        files_modified=len(active.files_modified) if active else 0,
        commits=active.commits if active else 0,
        tool_counts=tool_counts,
        all_messages=messages,
    )


# ============================================================
# 內部輔助函式
# ============================================================

def _is_message_entry(entry: dict) -> bool:
    """判斷 entry 是否為對話訊息（非 summary / meta 記錄）"""
    entry_type = entry.get("type", "")
    return entry_type in ("user", "assistant")


def _parse_entry(entry: dict) -> ParsedMessage | None:
    """將一筆 jsonl entry 轉換為 ParsedMessage"""
    uuid = entry.get("uuid")
    if not uuid:
        return None

    parent_uuid = entry.get("parentUuid")
    role = entry.get("type", "unknown")  # 'user' | 'assistant'

    # 解析訊息內容
    message = entry.get("message", {})
    content_text, has_tool_use, tool_names = _extract_content(message)

    return ParsedMessage(
        uuid=uuid,
        parent_uuid=parent_uuid,
        role=role,
        content=content_text,
        has_tool_use=has_tool_use,
        tool_names=tool_names,
        raw_entry=entry,
    )


def _extract_content(message: dict) -> tuple[str | None, bool, list[str]]:
    """
    從 message dict 萃取：純文字內容、是否有 tool_use、工具名稱清單。
    message.content 可能是字串或 content block 列表。
    """
    content = message.get("content")
    has_tool_use = False
    tool_names: list[str] = []
    text_parts: list[str] = []

    if isinstance(content, str):
        return content or None, False, []

    if isinstance(content, list):
        for block in content:
            if not isinstance(block, dict):
                continue
            block_type = block.get("type", "")
            if block_type == "text":
                text = block.get("text", "")
                if text:
                    text_parts.append(text)
            elif block_type == "tool_use":
                has_tool_use = True
                tool_name = block.get("name", "")
                if tool_name:
                    tool_names.append(tool_name)
            elif block_type == "tool_result":
                # tool_result 不計入文字內容
                pass

    text = "\n".join(text_parts) or None
    return text, has_tool_use, tool_names


def _build_branches(messages: list[ParsedMessage]) -> list[ParsedBranch]:
    """
    根據 parentUuid 建立 DAG，偵測分支（多個子節點 = rewind）。
    回傳所有分支，最新的 leaf 對應的分支標為 is_active=True。
    """
    # 建立 uuid → message 映射
    by_uuid: dict[str, ParsedMessage] = {m.uuid: m for m in messages}

    # 建立 parent → children 映射
    children: dict[str | None, list[str]] = {}
    for m in messages:
        parent = m.parent_uuid
        children.setdefault(parent, []).append(m.uuid)

    # 找所有葉節點（無子節點）
    all_uuids = set(by_uuid.keys())
    leaf_uuids = [
        uid for uid in all_uuids
        if uid not in children or not children[uid]
    ]

    if not leaf_uuids:
        # 無葉節點，將所有訊息視為單一線性分支
        return [_build_single_branch(messages, branch_idx=0, is_active=True)]

    # 從每個葉節點往根追溯，建立路徑
    branches_paths: list[list[str]] = []
    for leaf in leaf_uuids:
        path = _trace_path(leaf, by_uuid)
        branches_paths.append(path)

    # 去重：相同路徑只保留一條
    seen_paths: set[tuple] = set()
    unique_paths: list[list[str]] = []
    for path in branches_paths:
        key = tuple(path)
        if key not in seen_paths:
            seen_paths.add(key)
            unique_paths.append(path)

    # 最長路徑（最多訊息）的分支視為 active
    unique_paths.sort(key=len, reverse=True)

    result: list[ParsedBranch] = []
    for idx, path in enumerate(unique_paths):
        branch_messages = [by_uuid[uid] for uid in path if uid in by_uuid]
        is_active = (idx == 0)
        branch = _analyze_branch(branch_messages, branch_idx=idx, is_active=is_active)
        result.append(branch)

    return result


def _trace_path(leaf_uuid: str, by_uuid: dict[str, ParsedMessage]) -> list[str]:
    """從葉節點往根追溯，回傳由根到葉的 UUID 路徑"""
    path = []
    current = leaf_uuid
    visited: set[str] = set()

    while current and current not in visited:
        visited.add(current)
        path.append(current)
        msg = by_uuid.get(current)
        if not msg or not msg.parent_uuid:
            break
        current = msg.parent_uuid

    path.reverse()  # 由根到葉
    return path


def _build_single_branch(
    messages: list[ParsedMessage], branch_idx: int, is_active: bool
) -> ParsedBranch:
    """將訊息清單直接封裝為單一分支"""
    return _analyze_branch(messages, branch_idx=branch_idx, is_active=is_active)


def _analyze_branch(
    messages: list[ParsedMessage], branch_idx: int, is_active: bool
) -> ParsedBranch:
    """分析分支內容，計算統計數據"""
    leaf_uuid = messages[-1].uuid if messages else None

    # 計算 exchange_count（相鄰 user + assistant 算一回合）
    exchange_count = 0
    prev_role = None
    for m in messages:
        if m.role == "user" and prev_role != "user":
            exchange_count += 1
        prev_role = m.role

    # 從 tool_use 解析修改的檔案（Write / Edit tool）
    files_modified = _extract_files_modified(messages)

    # 從 Bash tool 結果偵測 git commit
    commits = _count_commits(messages)

    return ParsedBranch(
        branch_idx=branch_idx,
        is_active=is_active,
        leaf_uuid=leaf_uuid,
        messages=messages,
        exchange_count=exchange_count,
        files_modified=files_modified,
        commits=commits,
    )


def _extract_files_modified(messages: list[ParsedMessage]) -> list[str]:
    """從 Write / Edit tool_use 的 input 中解析修改的檔案路徑"""
    files: set[str] = set()
    for m in messages:
        if not m.has_tool_use:
            continue
        content = m.raw_entry.get("message", {}).get("content", [])
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") != "tool_use":
                continue
            tool_name = block.get("name", "")
            if tool_name in ("Write", "Edit", "NotebookEdit"):
                file_path = block.get("input", {}).get("file_path", "")
                if file_path:
                    files.add(file_path)
    return list(files)


def _count_commits(messages: list[ParsedMessage]) -> int:
    """
    從訊息內容偵測 git commit 次數。
    策略：在 assistant 訊息中尋找 Bash tool 執行 git commit 的工具呼叫，
    或在 tool_result 中尋找 commit hash 格式的輸出。
    """
    count = 0
    commit_pattern = re.compile(r"\bgit\s+commit\b", re.IGNORECASE)
    hash_pattern = re.compile(r"\[.+\s+[0-9a-f]{7,}\]")  # [branch abc1234]

    for m in messages:
        content = m.raw_entry.get("message", {}).get("content", [])
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            # 在 tool_use 的 input 中找 git commit 指令
            if block.get("type") == "tool_use" and block.get("name") == "Bash":
                cmd = block.get("input", {}).get("command", "")
                if commit_pattern.search(cmd):
                    count += 1
            # 在 tool_result 的輸出中找 commit hash 格式
            elif block.get("type") == "tool_result":
                result_content = block.get("content", "")
                if isinstance(result_content, str) and hash_pattern.search(result_content):
                    # 不重複計算（已在 tool_use 計算過）
                    pass

    return count


def _extract_project_path(entries: list[dict]) -> str | None:
    """從 summary entry 萃取 project 路徑"""
    for entry in entries:
        # Claude Code 的 summary entry 通常含 cwd 或 projectPath
        if entry.get("type") in ("summary", "init"):
            path = entry.get("cwd") or entry.get("projectPath")
            if path:
                return path
    return None


def _compute_tool_counts(messages: list[ParsedMessage]) -> dict[str, int]:
    """統計整個 session 中各工具的使用次數"""
    counts: dict[str, int] = {}
    for m in messages:
        for tool_name in m.tool_names:
            counts[tool_name] = counts.get(tool_name, 0) + 1
    return counts
