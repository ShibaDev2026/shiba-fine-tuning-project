# HyDE: Precise Zero-Shot Dense Retrieval without Relevance Labels (Hypothetical Document Embeddings)

> arXiv: https://arxiv.org/abs/2212.10496 ｜ ar5iv: https://ar5iv.labs.arxiv.org/html/2212.10496
> 作者: Luyu Gao, Xueguang Ma, Jimmy Lin, Jamie Callan｜ 2022
> （2022 舊論文無 arxiv HTML，數字取自 ar5iv 渲染）

## 關鍵詞
hypothetical document embeddings, zero-shot dense retrieval, query-document asymmetry, InstructGPT, Contriever, dense bottleneck

## 對應 Layer / Roadmap 階段
- **Roadmap P2（Agentic 召回）+ Layer 1 RAG** — 直擊本專案痛點：**短指令查詢 ↔ Library 模式文件的措辭不對稱**（query 是口語短句、文件是結構化模式）。HyDE 用 LLM 先生成「假設模式文件」再 embed，把查詢拉進文件空間 → 補召回涵蓋率（memory: pool recall top3=0.677 的缺口）。

## 核心結論（帶實證數字）
1. **零標籤大幅勝無監督 dense、逼近 fine-tuned**（nDCG@10）：
   - **TREC DL19**：HyDE **61.3** vs Contriever 44.5（+16.8）vs ContrieverFT 62.1（僅差 0.8）。
   - **DL20**：HyDE 57.9 vs Contriever 42.1。
2. **BEIR 低資源任務**（nDCG@10）：SciFact **69.1** vs Contriever 64.9（甚至贏 ContrieverFT 67.7）；TREC-COVID **59.3** vs 27.3（+32）。
3. **多語言 Mr.TyDi**（MRR@100）：Swahili 41.7 vs 38.3、Korean **30.6** vs 22.3、Japanese 30.7 vs 19.5——**跨語言一致增益**，對中文場景是正向訊號。

## 方法機制拆解
1. **生成**：zero-shot 指示 InstructGPT（text-davinci-003）依 query 生成「假設文件」（可能含錯誤事實）。
2. **編碼**：用無監督對比學習編碼器（Contriever / 非英文用 mContriever）把假設文件 embed 成向量。
3. **檢索**：用該向量在語料 embedding 空間做相似度檢索。
4. **關鍵洞察**：編碼器的「dense bottleneck 過濾掉假設文件的錯誤細節」——把預測接地到真實語料，不受合成內容品質拖累。

## 速查（綁本專案具體設計決策）
| HyDE 機制 | 本專案落地 |
|---|---|
| **query→生成假設文件→embed** | 本地模型（Qwen/GLM）依 Shiba 短指令生成「假設指令模式文件」（含預期工具鏈/步驟）→ 用 bge-m3 embed → 召回真實 Pattern。**直接補短查詢召回涵蓋率**，且解 [[project-rag-injection-transparency]] 的 `is_short_query` 兩難（短但有意義的 query 可先 HyDE 擴寫再召回，不必一刀攔）。 |
| **dense bottleneck 濾錯誤細節** | 即使本地模型生成的假設模式不完美，embed 後仍接地真實 Library——降低對生成品質的依賴。 |
| **跨語言一致增益** | 中文指令場景的正向背書（Korean/Japanese 均 +8~+11 MRR）。 |
| **零標籤** | 不需先建好 golden set 即可上線，符合 P1 早期 Library 尚小的階段。 |

## 侷限 / 與本專案差異
1. **多一次 LLM 生成 = 延遲與成本**：每次召回前先生成假設文件，本地模型推論成本需評估（對應 13% 採納天花板的 EV）。
2. **假設文件可能整段離題**：query 本身模糊時生成易跑偏；本專案可結合 `is_low_signal_query` gate 先擋無意義 query 再 HyDE。
3. domain：HyDE 驗於 web/QA/事實查核；本專案是「指令模式」檢索，假設文件的生成 prompt 需重設計（生成「該怎麼做這個任務」而非「答案文件」）。
4. encoder 是 Contriever；本專案用 bge-m3，HyDE 範式可直接套用 bge-m3 dense head。
