# Tier B 親評 gold batch 1 品質校準（6 題）

> 來源：gatekeeper_golden_samples（live DB）。grader=author（Claude 本 session 親撰+親評），
> 故 9.0 freeze 門檻對 Tier B 結構上接近 no-op；本檔供 Shiba 校準品質基準後再決定是否量產其餘 42 題。

## sid=75 ｜ git_ops ｜ score=9.5
**Q：** 如何建立一個新 branch 並切換過去？

**親評信心理由：** 基礎且無歧義的 git 操作；答案涵蓋現代/舊版兩種等價指令、起點參數、追蹤推送與驗證，完整正確。

**親撰參考答案（expected_output）：**

```
建立並切換到新 branch，有兩種等價做法：

# 方法 1：一步完成（推薦）
git switch -c <new-branch>      # Git 2.23+ 的現代指令
# 或舊版等價
git checkout -b <new-branch>

# 方法 2：分兩步
git branch <new-branch>         # 只建立，不切換
git switch <new-branch>         # 切換過去

說明：
- `-c`（switch）/ `-b`（checkout）= create，以「目前 HEAD」為起點建立新 branch。
- 從特定起點建立：git switch -c <new-branch> <start-point>（start-point 可為 commit、tag、其他 branch）。
- 建立後首次推送並設定追蹤：git push -u origin <new-branch>。

驗證：git branch --show-current 應印出 <new-branch>。
```

## sid=83 ｜ terminal_ops ｜ score=9.0
**Q：** 如何用一行指令找出目錄下所有超過 100MB 的檔案？

**親評信心理由：** 正確一行指令，並點出 find 的 M=MiB 語意與 macOS BSD find 行為；附排序進階版。

**親撰參考答案（expected_output）：**

```
# 方法 1：find（最通用，遞迴）
find . -type f -size +100M

# 帶大小並由大到小排序（人類可讀）
find . -type f -size +100M -exec du -h {} + | sort -rh

說明：
- -size +100M：大於 100 MiB（M = 1048576 bytes；find 的 M 是 MiB，非十進位 MB）。
- -type f：只找一般檔案，排除目錄。
- -exec du -h {} +：對命中檔案算人類可讀大小；+ 把多檔合併成少數幾次 du 呼叫（比 \; 高效）。
- sort -rh：-h 懂 K/M/G 單位，-r 由大到小。

macOS（BSD find）與 GNU find 的 -size 語意一致（+100M = 大於 100 MiB）。
```

## sid=91 ｜ code_gen ｜ score=9.5
**Q：** 寫一個 Python context manager 來計算程式區塊的執行時間。

**親評信心理由：** 提供 contextmanager 與 class 兩種慣用法；用 perf_counter（單調時鐘）、finally 確保例外時仍計時、__exit__ 回 False 不吞例外，符合最佳實務。

**親撰參考答案（expected_output）：**

```
import time
from contextlib import contextmanager


# 方法 1：contextmanager 裝飾器（最簡潔）
@contextmanager
def timer(label: str = "block"):
    """量測 with 區塊的 wall-clock 執行時間，離開時印出秒數。"""
    start = time.perf_counter()      # perf_counter：單調時鐘，不受系統時間調整影響
    try:
        yield
    finally:
        elapsed = time.perf_counter() - start
        print(f"[{label}] 耗時 {elapsed:.4f}s")


# 用法
with timer("資料載入"):
    do_something()


# 方法 2：class-based（需在區塊內取用 elapsed 時）
class Timer:
    def __init__(self, label: str = "block"):
        self.label = label

    def __enter__(self):
        self.start = time.perf_counter()
        return self                  # 回傳 self，讓區塊內可讀 self.elapsed

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.elapsed = time.perf_counter() - self.start
        print(f"[{self.label}] 耗時 {self.elapsed:.4f}s")
        return False                 # 回 False：不吞區塊內的例外

關鍵：用 perf_counter 而非 time.time（後者受系統校時影響）；finally / __exit__ 確保
即使區塊拋例外也會計時；__exit__ 回 False 才不會吞掉例外。
```

## sid=99 ｜ debugging ｜ score=9.5
**Q：** SQLite OperationalError: database is locked 如何診斷與修復？

**親評信心理由：** 與本專案 SQLite race hardening 一致；診斷（單 writer/長交易/未關連線）到修復（WAL/busy_timeout/縮短交易/序列化）層次完整。

**親撰參考答案（expected_output）：**

```
「database is locked」= 有連線持有寫鎖（或在 busy_timeout 內搶不到鎖）。

診斷：
1. 是否多 process / 多連線同時寫：SQLite 同時間只允許一個 writer。
2. 是否有未 commit 的長交易（BEGIN 後遲遲不 COMMIT，持鎖不放）。
3. 是否有 cursor / connection 未關閉（殘留鎖擋住 writer）。
4. lsof <db檔> 看哪些 process 持有檔案。

修復（由輕到重）：
1. 開 WAL 模式：PRAGMA journal_mode=WAL;（讀寫不互斥，大幅降低 locked）。
2. 設等待：PRAGMA busy_timeout=5000;（搶鎖時等而非立刻拋錯）。
3. 縮短交易：寫入儘快 COMMIT，避免「BEGIN→慢操作→COMMIT」。
4. 單一 writer 序列化：用連線池 / 鎖把寫入收斂到單一路徑。
5. 確保每個 connection / cursor 以 with 或 try/finally 確實關閉。

預防：寫入端統一 PRAGMA journal_mode=WAL; PRAGMA busy_timeout=5000;，
並把多步寫入包成單一交易（減少搶鎖次數）。
```

## sid=107 ｜ architecture ｜ score=9.0
**Q：** SQLite 與 PostgreSQL 在 multi-process 寫入場景下如何選擇？

**親評信心理由：** 判斷題；答案以寫入併發為主軸給出可操作的選擇準則，並強調先量測再決定（YAGNI）。架構題本有額外深度空間故給 9.0 非 9.5。

**親撰參考答案（expected_output）：**

```
核心差異：SQLite 是「單寫者」嵌入式資料庫，PostgreSQL 是「多寫者」client-server。

選 SQLite 當：
- 寫入併發低且可序列化（單機、寫入頻率不高）。
- 開 WAL 後讀寫不互斥已足夠（多讀 + 偶發寫）。
- 要零維運、單檔可攜、嵌入程序內（無獨立 server）。
- 注意：仍受「同時一個 writer」限制 → 高併發寫會排隊 / locked。

選 PostgreSQL 當：
- 多 process / 多機真正併發寫入，需 row-level locking 與 MVCC。
- 需連線池、複雜交易隔離級別、外部工具共享存取。
- 資料量大、需進階索引 / 查詢規劃 / 複寫。
- 願承擔獨立 server 的維運成本。

一句話判準：寫入是「可序列化的低頻」→ SQLite + WAL 最省且夠用；
寫入是「真多寫者高併發」→ 上 PostgreSQL。先量測實際寫入 QPS 再決定，
不要為「未來可能高併發」提前上 PG（YAGNI）。
```

## sid=115 ｜ knowledge_qa ｜ score=9.0
**Q：** MLX 的 unified memory 架構與傳統 GPU 記憶體的差異是什麼？

**親評信心理由：** 對 MLX unified memory（無獨立 VRAM、CPU/GPU 共用同一份資料、lazy eval、上限=總 RAM）描述正確，並給出本地 LLM 實務影響。

**親撰參考答案（expected_output）：**

```
MLX 的 unified memory（統一記憶體）vs 傳統 GPU 獨立顯存（VRAM）：

傳統 GPU（如 NVIDIA discrete GPU）：
- CPU 記憶體（RAM）與 GPU 記憶體（VRAM）是兩塊獨立實體記憶體。
- 資料要在 CPU↔GPU 間搬移（透過 PCIe），有明確 copy 成本與延遲。
- 須顯式管理 host/device 記憶體與傳輸（如 cudaMemcpy）。

MLX（Apple Silicon unified memory）：
- CPU 與 GPU 共用「同一塊」實體記憶體，無獨立 VRAM。
- array 不綁定特定 device；CPU 與 GPU 直接存取同一份資料，無需 copy。
- 省去 host↔device 傳輸成本，利於大模型（權重不必在兩塊記憶體各放一份）。
- 採 lazy evaluation，實際計算延後到需要結果時才觸發。
- 限制：可用記憶體上限 = 機器總 RAM（與系統 / 其他程式共享），
  不像 discrete GPU 有獨立專用 VRAM 容量。

實務影響：Mac 上跑本地 LLM，「總 RAM 即可用模型記憶體」；
64GB Mac 可載入遠大於同價位 discrete GPU VRAM 的模型，但會與系統共用。
```
