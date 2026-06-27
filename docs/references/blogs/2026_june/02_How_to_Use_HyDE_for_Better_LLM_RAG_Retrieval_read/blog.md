---
title: "How to Use HyDE for Better LLM RAG Retrieval"
subtitle: "Building an advanced local LLM RAG pipeline with hypothetical document embeddings"
url: https://medium.com/data-science/how-to-use-hyde-for-better-llm-rag-retrieval-a0aa5d0e23e8
author: Dr. Leon Eversberg
published: 2024-10-04
read_time: 9 min read
source_type: blog
relevance: 5
source: local saved HTML (full version)
fetch_failed: false
project_link: 直接支撐 roadmap P2 HyDE 決策（注入點 rag.py:_vector_search）—HyDE 用 LLM 把短/口語 query 先生成一份「假設文件」再嵌入，縮短 query 與長正式記憶文件之間的 embedding 落差；作者明指此法對未經 supervised 標註訓練的 contriever 型 embedding（如 all-MiniLM）有效，正對應本專案短控制詞 query vs 長 session 文件的召回問題。
---

# How to Use HyDE for Better LLM RAG Retrieval

**Subtitle:** Building an advanced local LLM RAG pipeline with hypothetical document embeddings

**By Dr. Leon Eversberg — 9 min read · Oct 4, 2024**

*Figure (cover): "Implementing HyDE is very simple in Python." (Image by the author)*

> 本檔為作者完整文章的結構化重述（prose 為摘述、非逐字轉錄），保留全部技術細節、**5 個 code block（逐字）**、**References（逐字）**。先前「member-only 截斷版／未取得 code」誠實註記已移除——本機 HTML 經確認為完整版（正文延續過先前截斷點、含 Table of Contents、Implementing HyDE、Is It Worth It、Conclusion、References）。

## Intro — RAG retrieval recap

LLM 可藉由存取外部文件補充知識。基本的 RAG pipeline 由四部分組成：user query、把文字轉成高維向量的 embedding 模型、在 embedding 空間中搜尋與 query 相似文件的 retrieval 步驟，以及用召回文件產生答案的 generator LLM [1]。retrieval 是關鍵環節：若 retriever 沒在 corpus 中找到正確文件，LLM 就無從產生可靠答案。

retrieval 的一個典型問題是：user query 往往是**很短、文法/拼字/標點不完美**的問句，而對應的目標文件卻是一**長段書寫良好的文字**。這種長度與格式上的落差會降低 query 與 document 在 embedding 空間中的相似度。

*Figure: 取自 MS MARCO 資料集的 query 與對應 passage，示意 query 與 document 通常長度與格式不同。(Image by the author)*

> **HyDE is a proposed technique to improve the RAG retrieval step by converting the user question into a hypothetical document.**

## Table Of Contents
- HyDE Retrieval — Contriever — When to Use HyDE
- Implementing HyDE
- Is Implementing HyDE Worth It?
- Conclusion
- References

## HyDE Retrieval

Hypothetical Document Embeddings（HyDE）最早由 2022 年論文 *"Precise Zero-Shot Dense Retrieval without Relevance Labels"* 提出 [2]。其目標是把 user query 轉換成一份「document」，讓 retriever 的任務變得更容易。

*Figure（取自 [2]）：預訓練 LLM 把 user query 轉成一份假設性的 fake document；retriever 再用這份 fake document 去知識庫中搜尋相似的真實文件。*

做法是用一個現成 LLM（如 ChatGPT、Llama 等）配一個簡單指令——例如 "write a document that answers the question"——把 user query 轉成一份生成的 fake document。**把短問句轉成較長的假設性段落，是 HyDE 的核心概念。**

這份生成的 fake document 很可能包含幻覺數字與不實陳述，但這並不重要：因為 fake document 會被 encoder 編成 embedding 向量，僅用於語意相似度搜尋。依 HyDE 論文，encoder 扮演「有損壓縮器」，會濾掉 fake document 中幻覺的細節，留下一個應與真實 corpus 文件 embedding 非常相近的向量。

最後，contriever 用生成的 fake document 在文件 embedding 空間中搜尋最接近的真實文件，通常以 dot product 或 cosine similarity 計算。總結：HyDE 不是在「query—document」embedding 空間做相似度搜尋，而是在「（假設）document—（真實）document」embedding 空間做搜尋。

### Contriever

什麼是 contriever、HyDE 為何要用它？HyDE 論文的核心動機是：並非總有夠大的資料集可訓練一個 query-document 相似度搜尋的 retriever。

contriever 是用 **contrastive learning（對比學習）** 訓練的 retriever（embedding 模型）。對比學習是一種 self-supervised 學習，訓練集不需要標註 [3]。這在缺乏大量標註資料時特別有用，例如要訓練英文以外語言的 retriever。

以對比學習訓練的 embedding 模型，學習區分語意相似（高分）與語意不相似（低分）的文字。訓練時文字配對取自同一文件（positive pair）或不同文件（negative pair），retriever 被訓練去區分 positive 與 negative 配對。

*Figure：用對比學習訓練 retriever——positive document 取自與 query 同一份文件，negative document 取自不同文件；retriever 學會給 positive 高分、negative 低分。(Image by the author)*

訓練好的 contriever 可直接使用，也可當作預訓練模型再用標註資料進一步 fine-tune。重點：contriever 以 self-supervised 方式（搜尋文件間相似性、不需標註）訓練，而 HyDE 指令透過建立 fake document 把 user 問句轉進這個「document 空間」。

### When to Use HyDE

是否該用 HyDE，關鍵在於你選的 **embedding 模型**。

一個熱門、通用且免費的 encoder 是 sentence-transformers 套件的 `all-MiniLM-L12-v2`（託管於 Hugging Face）。其 model card 寫道：該專案以 self-supervised contrastive learning 目標、在非常大規模的句級資料集上訓練 sentence embedding；以預訓練的 `microsoft/MiniLM-L12-H384-uncased` 為基礎、在 10 億句對資料集上 fine-tune。

也就是說，這個 encoder 正是 HyDE 的適用對象：它以 self-supervised 對比學習、在 document-document 配對上訓練、無標註。因此 HyDE 應能提升此 embedding 的召回表現。

反之，若你的 encoder 已**經 supervised 方式專門針對語意搜尋**（尤其是 **asymmetric semantic search**）訓練，就不需要 HyDE。asymmetric semantic search 指：有一個短問句、要找一段較長的段落來回答——正是 RAG 的典型用途。這類 encoder 的常用訓練集是 MS MARCO（源自真實 Bing 問句 + 人工答案的問答資料集）。Sentence Transformers 中的 `msmarco-*`、`multi-qa-*` 等模型已在標註的 question-document 資料上訓練，**理論上不會**因 HyDE 受益。

至於多數商用 embedding（如 OpenAI 的 text-embedding 系列），我們不知道其訓練方式，所以 HyDE 可能有效也可能無效。

## Implementing HyDE

以下用 Python 實作一個基本版 HyDE。先寫一個簡單的 LLM class，初始化本地 `Qwen2.5-0.5B-Instruct`；模型夠小，沒有 GPU 時也能在 CPU 上跑。

```python
from transformers import AutoModelForCausalLM, AutoTokenizer
import torch


class LLM:
    def __init__(
        self,
        model_name="Qwen/Qwen2.5-0.5B-Instruct",
    ):
        self.device = "cuda" if torch.cuda.is_available() else "cpu"

        self.model = AutoModelForCausalLM.from_pretrained(
            model_name,
            torch_dtype="auto",
        ).to(self.device)
        self.tokenizer = AutoTokenizer.from_pretrained(model_name)

    def generate(self, prompt, temperature=0.7, max_new_tokens=256):

        messages = [{"role": "user", "content": prompt}]
        text = self.tokenizer.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True
        )
        model_inputs = self.tokenizer([text], return_tensors="pt").to(self.device)

        generated_ids = self.model.generate(
            **model_inputs,
            max_new_tokens=max_new_tokens,
            do_sample=True,
            temperature=temperature,
        )
        generated_ids = [
            output_ids[len(input_ids) :]
            for input_ids, output_ids in zip(model_inputs.input_ids, generated_ids)
        ]

        return self.tokenizer.batch_decode(generated_ids, skip_special_tokens=True)[0]
```

接著需要一個 encoder 模型來計算 sentence embeddings。用 `sentence_transformers` 幾行就能取得本地的 `all-MiniLM-L12-v2` contriever：

```python
from sentence_transformers import SentenceTransformer

encoder_model = SentenceTransformer("all-MiniLM-L12-v2", device="cpu")
```

有了這兩個元件，就能計算 hypothetical document 的 encoding：

```python
qwen = LLM()
question = "was ronald reagon a democrat?"
hypothetical_document = qwen.generate(
    f"Write a paragraph that answers the question. Question: {question}"
)

>> print(hypothetical_document)
```

印出 hypothetical document，會得到一段（看似像 Wikipedia、但充滿幻覺事實的）段落，例如把 Reagan 出生地、政黨、選舉對手都寫錯。乍看像真的，但其中有許多幻覺事實——不過因為這不是真實文件，有錯誤沒關係。

接著，取一段真實的 Wikipedia 文字，分別計算 question、Wikipedia document、hypothetical document 的 embeddings：

```python
wikipedia = """Ronald Wilson Reagan[a] (February 6, 1911 – June 5, 2004) was an American politician and actor who served as the 40th president of the United States from 1981 to 1989. 
A member of the Republican Party, he became an important figure in the American conservative movement, and his presidency is known as the Reagan era. """

hypothetical_document_embedding = encoder_model.encode(hypothetical_document)
question_embedding = encoder_model.encode(question)
wikipedia_embedding = encoder_model.encode(wikipedia)
```

現在檢查 hypothetical document embedding 是否真的比 question embedding 更接近真實 document embedding。用 encoder 的 similarity 函式（底層為 cosine similarity，範圍 -1 到 +1：-1 反向、0 垂直、+1 同向）：

```python
>> print(encoder_model.similarity(hypothetical_document_embedding, wikipedia_embedding))
>> tensor([[0.8039]])

>> print(encoder_model.similarity(question_embedding, wikipedia_embedding))
>> tensor([[0.4566]])
```

可見 hypothetical document embedding（0.8039）在 embedding 空間中明顯比 question embedding（0.4566）更接近真實 document embedding。HyDE 成功縮短了 question 與 document 之間的 domain gap。

*Figure：HyDE 視覺化——在「(fake) document—(real) document」embedding 空間中做相似度搜尋。(Image by the author)*

代價是：生成 hypothetical document 需要額外用 LLM 運算，這是 HyDE 的缺點。

## Is Implementing HyDE Worth It?

近期研究 *"Searching for Best Practices in Retrieval-Augmented Generation"* [4] 比較了 RAG 的多種 retrieval 方法，發現 HyDE 相較 baseline embedding 提升了召回表現；而 **hybrid search 結合 HyDE** 整體效果最佳。有趣的是，把**原始 query 與 hypothetical document 串接（concatenate）** 還能得到更好的結果。另一方面，HyDE 因每個 query 都需額外 LLM 呼叫來生成 fake document，會增加延遲與成本。

該研究建議：在兼顧最佳表現與可容忍延遲下，預設採用 **Hybrid Search with HyDE**；若更重效率，Hybrid Search（結合稀疏 BM25 + dense original embedding）能以相對低延遲達到顯著表現 [4]。

## Conclusion

HyDE 是改善 RAG pipeline retrieval 環節的進階技巧。藉由從 query 建立 hypothetical fake document，把相似度搜尋從「question—document」空間搬到「document—document」空間。HyDE 針對的使用情境是：embedding 模型**尚未**以標註的 question-document 資料做 supervised 語意搜尋 fine-tune。由於只需幾次額外 LLM 呼叫，HyDE 非常容易實作。它是工具箱中的一塊積木，可與 hybrid search、retrieval 後接 reranker 等其他進階 RAG 技巧組合使用。

## References

- [1] P. Lewis et al., *Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks* (2021), arXiv:2005.11401
- [2] L. Gao, X. Ma, J. Lin, J. Callan, *Precise Zero-Shot Dense Retrieval without Relevance Labels* (2022), arXiv:2212.10496
- [3] G. Izacard et al., *Unsupervised Dense Information Retrieval with Contrastive Learning* (2022), Transactions on Machine Learning Research (08/2022)
- [4] X. Wang et al., *Searching for Best Practices in Retrieval-Augmented Generation* (2024), arXiv:2407.01219

---

*Author's related series (referenced at article end): "How to Use Re-Ranking for Better LLM RAG Retrieval"、"How to Use Hybrid Search for Better LLM RAG Retrieval".*
