# Changelog

所有版本變更依照 [Keep a Changelog](https://keepachangelog.com/zh-TW/1.0.0/) 格式記錄。
版本號遵循 [Semantic Versioning](https://semver.org/lang/zh-TW/)。

## [0.1.0] - 2026-04-17

### Added

- **Layer 1 記憶層**核心實作
  - `layer_1_memory/lib/parser.py`：解析 Claude Code JSONL session 檔案（branch 追蹤、tool_use 偵測）
  - `layer_1_memory/lib/classifier.py`：規則型事件分類器（7 種 event_type）
  - `layer_1_memory/lib/db.py`：SQLite 連線管理、schema 初始化、migration 機制
  - `layer_1_memory/lib/rag.py`：FTS5 記憶查詢與 RAG context 格式化
  - `layer_1_memory/hooks/stop_hook.py`：Claude Code Stop Hook，背景 spawn 同步
  - `layer_1_memory/hooks/sync_session.py`：背景同步主邏輯（parse → classify → upsert DB）
  - `layer_1_memory/hooks/session_start_hook.py`：SessionStart Hook，RAG 注入歷史 context
  - `layer_1_memory/db/schema.sql`：四層 schema（projects / sessions / branches / messages + FTS5）
  - `layer_1_memory/config.yaml`：路徑、閾值設定
  - `layer_1_memory/setup.sh`：一鍵部署腳本（venv、DB 初始化、settings.json hooks 寫入）
- **單元測試** `tests/memory/`：db / parser / classifier / rag 共 18 個測試案例，全數通過
