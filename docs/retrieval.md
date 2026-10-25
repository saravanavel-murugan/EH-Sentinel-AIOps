# Knowledge & Retrieval (RAG) — Phase 4

**Project:** EventHub Ops – Sentinel
**Phase 4 artifact** — embeddings + semantic search over a knowledge base (runbooks, FAQ,
escalation guidelines, policy), wired into the A4/A5 agents, with a with/without-retrieval
comparison, a retrieval-quality test, and explicit "no relevant info" handling.

> **Reproduce (from `capstone_agent/`):**
> ```bash
> python scripts/ingest_documents.py      # knowledge/raw -> knowledge/processed/chunks.json
> python scripts/build_faiss_index.py      # chunks -> knowledge/faiss_index/{index.faiss,index.pkl}
> python -m evaluation.retrieval_eval       # -> data/evaluation/retrieval_eval.{json,md}
> ```
> Offline by default. For OpenAI embeddings: `SENTINEL_EMBEDDINGS=openai` + `OPENAI_API_KEY`,
> then rebuild the index.

---

## 1. Pipeline

```
knowledge/raw/*.md
   │  document_loader.load_documents
   ▼
loaded docs
   │  chunker.chunk_documents  (markdown heading-aware + size-bound)
   ▼
knowledge/processed/chunks.json   (23 chunks from 4 docs)
   │  embedder.get_embedder  (OpenAI text-embedding-3-small | offline fake, L2-normalized)
   ▼
faiss_store.FaissStore.build  (IndexFlatIP == cosine on normalized vectors)
   ▼
knowledge/faiss_index/{index.faiss, index.pkl}
   │  retriever.Retriever  (embed query -> top-k -> min_score threshold)
   ▼
retrieved snippets  (or "NO_RELEVANT_KNOWLEDGE_FOUND")
```

**Modules** (`retrieval/`): `document_loader.py`, `chunker.py`, `embedder.py`, `faiss_store.py`,
`retriever.py`. **Scripts**: `scripts/ingest_documents.py`, `scripts/build_faiss_index.py`.

---

## 2. Knowledge base

`knowledge/raw/` (markdown, Kafka-ops domain, PII-safe placeholders):

| File | Content |
|------|---------|
| `runbooks.md` | RB-01..RB-05: consumer lag, broker/under-replicated, connector failure, producer errors, schema compatibility |
| `faq.md` | Operator FAQ (noise vs incident, severity, approval, recovery) |
| `escalation_guidelines.md` | P1–P4 response + escalation triggers |
| `company_policy.md` | Autonomy/approval, redaction, prompt-injection, audit |

Ingestion produced **23 chunks** (company_policy 8, escalation 7, runbooks 6, faq 2).

---

## 3. Embeddings (configurable)

| `SENTINEL_EMBEDDINGS` | Backend | Dim | Use |
|-----------------------|---------|-----|-----|
| `openai` | `OpenAIEmbeddings(text-embedding-3-small)` | 1536 | real / evaluation (needs `OPENAI_API_KEY`) |
| `fake` (default) | deterministic md5 bag-of-words hashing | 256 | offline verification, no key |

Both return L2-normalized vectors, so FAISS inner-product search equals cosine similarity.
The same `OPENAI_API_KEY` drives chat (`SENTINEL_LLM=openai`) and embeddings — one switch flips
the whole system (see README).

---

## 4. How retrieval connects to the agents

The multi-agent `enrich` node builds a symptom-focused query from the signal (metric + entity,
with metric-name expansion) and attaches the top-k snippets to the grounded context as
`retrieved_knowledge`. Then:

- **A4 (Root-Cause Hypothesis)** grounds hypotheses/next-checks in the retrieved runbook and cites
  the source.
- **A5 (Remediation Recommendation)** bases its actions on the retrieved runbook step and cites it;
  with no runbook it recommends safe diagnostics only.

Retrieval is optional: `MultiAgentSentinel(use_retrieval=False)` disables it (used for the
comparison), and the pipeline degrades gracefully if no index exists.

---

## 5. "No relevant information" handling (required)

The retriever applies a `min_score` threshold (default 0.30). If no chunk clears it, it returns
`found=False` and `format_snippets` emits `NO_RELEVANT_KNOWLEDGE_FOUND`. A4/A5 are instructed to
proceed without a runbook and say so rather than fabricate one.

Evidence (offline): off-domain queries are correctly rejected —
"chocolate cake" best score 0.26, "weather forecast" 0.19, both < 0.30 → `found=False`.

---

## 6. Retrieval quality (hit@k) — evidence

From `python -m evaluation.retrieval_eval` on 10 labelled queries
(`data/evaluation/retrieval_queries.json`), offline fake embedder:

| Metric | Result |
|--------|--------|
| hit@1 (relevant queries) | 6 / 8 (75%) |
| hit@3 (relevant queries) | **8 / 8 (100%)** |
| correct "no relevant info" (non-relevant) | **2 / 2 (100%)** |

The two hit@1 misses (consumer-lag, P1-escalation) are the **offline lexical embedder** ranking a
broad FAQ/overview chunk just above the specific runbook; both still appear in top-3. With OpenAI
embeddings, semantic separation is sharper and hit@1 is expected to improve. Re-run with
`SENTINEL_EMBEDDINGS=openai` to measure the live numbers.

---

## 7. With vs without retrieval — improvement over baseline

Running the A1–A8 pipeline on the 4 actionable incidents, retrieval ON vs OFF:

| | A4/A5 cite an approved runbook |
|--|-------------------------------|
| **WITH retrieval** | **4 / 4** |
| WITHOUT retrieval | 0 / 4 |

Example (tc-01 payments lag): with retrieval, A5 → "Follow runbook step for consumer_lag (per
runbooks.md :: RB-01 Consumer lag rising)"; without retrieval, A5 → generic "Run diagnostic for
consumer_lag" with "no runbook found". Retrieval turns advice into **runbook-grounded, citeable**
guidance — the concrete improvement over the pre-retrieval agent.

---

## 8. Artifacts

- Pipeline: `retrieval/*.py`; scripts: `scripts/ingest_documents.py`, `scripts/build_faiss_index.py`
- Knowledge: `knowledge/raw/*.md`, `knowledge/processed/chunks.json`, `knowledge/faiss_index/`
- Eval harness: `evaluation/retrieval_eval.py`; labelled queries: `data/evaluation/retrieval_queries.json`
- Results: `data/evaluation/retrieval_eval.{json,md}`

> Provider note: evidence generated offline (fake embedder + fake chat model), reproducible
> without a key. Set `SENTINEL_EMBEDDINGS=openai` + `SENTINEL_LLM=openai` + `OPENAI_API_KEY` and
> rebuild the index to reproduce with real embeddings.
