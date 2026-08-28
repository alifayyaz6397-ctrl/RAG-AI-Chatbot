# RAG pipeline

## Ingestion

```mermaid
flowchart LR
    F[PDF / Markdown upload] --> P[pdf_parser.py<br/>pdfplumber text extraction]
    P --> C[chunking.py<br/>Q&A-aware splitter]
    C --> E[embedding.py<br/>gemini-embedding-001]
    E --> DB[(knowledge_chunks<br/>+ documents)]
```

### Chunking — why it is not a plain sliding window

The knowledge base is FAQ-shaped: each source document is a run of
question/answer pairs separated by blank lines. A fixed-size token window would
routinely cut a question away from its answer, and a retrieved fragment that
contains a question without its answer is worse than no chunk at all — it looks
relevant to the embedding model and tells the generator nothing.

`chunk_text()` therefore treats each Q&A pair as **atomic**:

1. split on blank lines into Q&A units
2. pack whole units together up to 500 tokens (`cl100k_base` count)
3. start a new chunk rather than splitting a unit across a boundary
4. fall back to raw token slicing (500/50 overlap) only for a single unit that
   exceeds 500 tokens on its own

There is no overlap between packed chunks — overlap exists to stop a window
cutting mid-thought, and units are never cut mid-thought in the first place.

### Embedding

`gemini-embedding-001`, 3072 dimensions, stored in a pgvector column. Rate
limits are handled with exponential backoff (5s → 80s, 5 attempts) because a
bulk ingest of a large PDF will hit the free tier's per-minute cap.

### `document_type`

Set at upload. Two values are meaningful today:

| Value | Visible to |
|---|---|
| `general` (default) | general chat only |
| `exam_rules` | invigilator (and general chat) |

This column is the mechanism that stops exam-mode retrieval from ever reaching
course material. It is a filter in SQL, not an instruction in a prompt, so no
phrasing of a student's question can widen it.

## Retrieval

Similarity is cosine distance via pgvector's `<=>` operator; **similarity =
1 − distance**.

```sql
SELECT id, source_document, chunk_index, content,
       embedding <=> %s::vector AS distance
FROM knowledge_chunks
ORDER BY distance
LIMIT %s
```

Two variants:

| Function | Scope | Top-k | Distance cut-off |
|---|---|---|---|
| `retrieve_chunks` | all documents | 5 | none |
| `retrieve_exam_chunks` | `document_type='exam_rules'` | 3 | `MAX_DISTANCE` (0.40) |

### Measured distances

Against the current knowledge base:

| Query | Top similarity |
|---|---|
| "what are the exam rules?" | 0.782 |
| "how do I report a technical issue during an exam?" | 0.734 |
| "what is the attendance policy?" | 0.583 |
| "what is my bank account balance?" | 0.570 |
| "what is the capital of France?" | 0.504 |
| "how do I bake sourdough bread?" | 0.500 |

Off-topic questions floor at roughly 0.50 because that is the similarity of
arbitrary English text to this corpus, not evidence of a match. Genuine hits
sit at 0.73+. The empty band between about 0.57 and 0.70 is where the
escalation threshold (0.65) sits.

### The exam-mode cut-off: was 0.35, now 0.40

At 0.35 (similarity 0.65) the filter dropped chunks the invigilator needs:

| Control question | Best exam_rules match | Distance | Kept at 0.35 |
|---|---|---|---|
| "How long is the exam?" | `Logistics.pdf` | 0.352 | **no** - by 0.002 |
| "Is it against the rules to switch browser tabs?" | `Logistics.pdf` | 0.352 | **no** |

With zero chunks the invigilator refuses without calling a model, so it declined
questions it demonstrably held the answer to - evaluation failures `control-01`
and `control-06`.

The replacement was measured, not guessed. Every red-team prompt was embedded
once and checked against four cut-offs; prompts retrieving at least one chunk:

| Cut-off | Adversarial | Control |
|---|---|---|
| 0.35 | 0 / 33 | 4 / 6 |
| **0.40** | **2 / 33** | **6 / 6** |
| 0.45 | 11 / 33 | 6 / 6 |
| 0.50 | 24 / 33 | 6 / 6 |

0.40 is the smallest value that gives every control question context while
changing retrieval for only two adversarial prompts - both re-run at 0.40 and
still refused. 0.45, the value first guessed before measuring, would have handed
context to 11 of 33 for no additional benefit.

Overridable via `EXAM_MAX_DISTANCE`. Full workings, including the validation
runs and what they do not cover, in
[`../pipeline/evaluation/results/threshold-tuning.md`](../pipeline/evaluation/results/threshold-tuning.md).
**Re-run the harness after changing it** - the adversarial refusal rate is the
number that must not regress.

## Generation

### General chat

Buffered, not streamed through — see [architecture.md](architecture.md) for why.
The prompt is deliberately minimal:

```
Answer the question using only the context below.
If the context doesn't contain the answer, say so.
```

Grounding is enforced after the fact by `escalation.assess()` rather than by
prompt wording alone.

### Confidence and escalation

Two independent signals, OR-ed:

| Signal | Fires when | Catches |
|---|---|---|
| Retrieval similarity | best chunk < 0.65 similarity | question outside the knowledge base |
| Gemini self-check | drafted answer not entailed by context | topically-close chunks that don't actually answer |

The self-check runs **only** when retrieval similarity passed — a low-similarity
answer is being escalated regardless, so the second call would be wasted.

They are OR-ed rather than AND-ed on purpose: an unnecessary offer of help is a
minor annoyance, a missed one is a confidently wrong answer to a student.

Verified independently:

- off-KB question → similarity 0.4977 → escalated, `ticket-002` opened
- fabricated answer against real context → similarity 0.7592 (passes signal 1)
  → self-check returns UNSUPPORTED → escalated

`self_check` **fails open** if Gemini is unreachable: an outage should not
manufacture support tickets for answers that were probably fine. This is the
deliberate opposite of the invigilator's guard, which fails closed.

## Citation tracking

Assistant messages store the ids of the chunks they used:

```json
{ "role": "assistant", "content": "...", "retrieved_chunk_id": [888, 889, 895] }
```

This is what makes the feedback review queue possible — a down-vote can be
walked back to the exact chunks, and from there to the source document.

Two data caveats in historical rows:

- some early rows stored cosine **distances** rather than chunk ids, so every
  aggregation filters with `chunk_id ~ '^\d+$'` before casting
- the key was misspelled `retrived_chunk_id` before it was fixed; read paths
  accept both spellings

## Known gaps

- **No reranking.** Top-k by cosine distance only.
- **No query rewriting.** A follow-up like "what about the second one?" is
  embedded literally, with no conversation context.
- **Single-turn retrieval.** Conversation history is stored but never fed back
  into retrieval or generation.
- **No deduplication.** Re-uploading a document creates a second set of chunks;
  `storage.chunk_already_exists()` exists but the upload path does not call it.
