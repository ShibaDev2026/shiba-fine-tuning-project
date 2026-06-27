# C-Pack: Packed Resources For General Chinese Embeddings (BGE)

> arXiv: https://arxiv.org/abs/2309.07597 ｜ ar5iv: https://ar5iv.labs.arxiv.org/html/2309.07597 ｜ SIGIR 2024
> 作者: Shitao Xiao, Zheng Liu, Peitian Zhang, Niklas Muennighoff et al.（BAAI / FlagEmbedding）｜ 2023

## 關鍵詞
Chinese embeddings, C-MTEB, C-MTP, BGE, retrieval vs reranking 分離評估, contrastive fine-tuning

## 對應 Layer / Roadmap 階段
- **Layer 1（本專案 embedding 家族源頭）+ P1/P2** — bge-m3（[[paper-12]]）的同源前身（BGE/FlagEmbedding）。其 C-MTEB 把 **retrieval 與 reranking 列為獨立任務分別評估**，直接支持本專案「golden set 的 gt 應獨立標註、不該抽自 retriever 自身」的方法論（破 cosine-bound）。

## 核心結論（帶實證數字）
1. **C-Pack 三件**：**C-MTEB**（6 類任務、35 資料集）/ **C-MTP**（100M 無標 text pair + 838K 標註）/ **C-TEM 模型**（small 24M / base 102M / large 326M）。
2. **BGE-large 中文 SOTA**：avg **63.96** vs M3E-large 57.66 / Multilingual-E5-large 58.84（約 +10%）。
3. **retrieval 與 reranking 在 C-MTEB 分開評**：retrieval 量 top-k 相似文件、reranking 量「1 正 + N 負」候選排序——**兩任務本質不同**。

## 方法機制拆解
- 三階段訓練：① MAE-style 純文字 pretrain ② 無標資料對比學習 general fine-tune（**batch size 19,200** 大批量）③ 標註資料 instruction-based task fine-tune。

## 速查（綁本專案具體設計決策）
| C-Pack 機制 | 本專案落地 |
|---|---|
| **retrieval / reranking 獨立任務獨立標註** | **直接背書本專案 golden set 修法**：gt 不該抽自 bi-encoder（cosine-bound 根源），應像 C-MTEB 獨立標註 reranking 候選——連 08 DREAM 補標 [[paper-08]]。 |
| **中文 embedding 家族（BGE）** | bge-m3 的中文能力來源；本專案中文指令語料用 BGE 系是對的選擇，C-MTEB 可當中文召回的標準評測。 |
| **instruction-based fine-tune** | 若 P5 微調 embedding，instruction 格式是 BGE 既有範式。 |

## 侷限 / 與本專案差異
1. 作者自承資料過濾「策略簡單」、多任務型別影響「可能互相抵觸」。
2. C-Pack 是通用中文 embedding；本專案是「中文指令模式」特定 domain，C-MTEB 分數不直接代表指令召回品質（需自建類 C-MTEB 的指令召回評測）。
3. 是 bge-m3 前身（單功能 dense）；bge-m3（[[paper-12]]）已加 sparse/multi-vector。
