#!/usr/bin/env bash
# statusline_rag.sh — 自建輕量 statusLine（不依賴 claude-hud；該 plugin 已被卸除）
# 顯示一行：模型 / 📁 目錄 / ⎇ git branch / 🧠 RAG:N
#   RAG:N = 本地召回筆數，取自 <project>/.remember/rag_echo.md 首行 rag_count
#           （由 session_start_hook 每次 prompt 覆寫；檔在=hook 有跑，0=跑了沒命中）
#
# 設計約束：
# - 純顯示、容錯：任一欄缺值（jq/git 失敗、非 repo、無 echo 檔）皆靜默省略該段。
# - 自我 scope：用 statusline JSON 的 project_dir 定位 echo 檔，僅有該檔的專案亮 RAG 燈。
# - 不依賴 executable bit（settings 以 `bash <path>` 啟動），避免 chmod +x。

input=$(cat)

# 一次 jq 取多欄；@tsv 會跳脫欄內 tab/換行，故用 IFS=tab 切，路徑含空白也安全
IFS=$'\t' read -r model cur proj cwd < <(printf '%s' "$input" | jq -r '
  [ (.model.display_name // ""),
    (.workspace.current_dir // ""),
    (.workspace.project_dir // ""),
    (.cwd // "") ] | @tsv' 2>/dev/null)

dir="${cur:-$cwd}"
base=$(basename "${dir:-?}")
branch=$(git -C "$dir" rev-parse --abbrev-ref HEAD 2>/dev/null)

# RAG 指示燈
root="${proj:-$cwd}"
rag=""
if [ -n "$root" ] && [ -f "$root/.remember/rag_echo.md" ]; then
  n=$(sed -n 's/.*rag_count=\([0-9][0-9]*\).*/\1/p' "$root/.remember/rag_echo.md" | head -1)
  [ -n "$n" ] && rag=" 🧠 RAG:${n}"
fi

# ANSI：cyan 模型 / dim 圖示 / magenta branch
C='\033[36m'; M='\033[35m'; D='\033[2m'; R='\033[0m'
out="${C}${model}${R}"
[ -n "$base" ]   && out="${out} ${D}📁${R} ${base}"
[ -n "$branch" ] && out="${out} ${D}⎇${R} ${M}${branch}${R}"
out="${out}${rag}"
printf '%b' "$out"
