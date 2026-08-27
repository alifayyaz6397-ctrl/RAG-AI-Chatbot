# Backend documentation

| Document | Covers |
|---|---|
| [architecture.md](architecture.md) | component map, request flows, layers of defence, module reference |
| [endpoints.md](endpoints.md) | every route, auth, request/response shapes, status codes |
| [rag-pipeline.md](rag-pipeline.md) | chunking, embedding, retrieval, thresholds, confidence scoring |
| [prompts-and-guardrails.md](prompts-and-guardrails.md) | prompt design, the output guard, injection surface |
| [../pipeline/evaluation/results/results.md](../pipeline/evaluation/results/results.md) | latest red-team and hallucination results |
| [../pipeline/evaluation/results/threshold-tuning.md](../pipeline/evaluation/results/threshold-tuning.md) | retrieval cut-off measurement and validation |

## Running the backend

```bash
cd backend/pipeline
python -m uvicorn main:app --reload --port 8000
```

Interactive API docs at `http://127.0.0.1:8000/docs`.

Dependencies are declared in [`../requirements.txt`](../requirements.txt)
(`pip install -r ../requirements.txt`).

## Environment

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `DATABASE_URL` | yes | — | Postgres connection string (pgvector required) |
| `GEMINI_API_KEY` | yes | — | Google AI Studio key |
| `JWT_SECRET` | yes | — | HS256 signing secret |
| `GEMINI_MODEL` | no | `gemini-3.6-flash` | model for all generative calls |
| `ESCALATION_SIMILARITY_THRESHOLD` | no | `0.65` | below this, offer a human |
| `EXAM_MAX_DISTANCE` | no | `0.40` | exam-mode retrieval cut-off — see [rag-pipeline.md](rag-pipeline.md#the-exam-mode-cut-off-was-035-now-040) |

### Free-tier quota

Google's free tier allows **20 generate-content requests per day, per model**.
One invigilator turn costs up to three (route → draft → guard), so a full
evaluation run cannot complete in a single day on a free key. The harness caches
after every case and resumes; switching `GEMINI_MODEL` gives a fresh 20.

## Migrations

Idempotent SQL in [`../pipeline/migrations/`](../pipeline/migrations/), applied
in filename order:

```bash
psql "$DATABASE_URL" -f migrations/week6_message_feedback.sql
psql "$DATABASE_URL" -f migrations/week6_support_tickets_id.sql
psql "$DATABASE_URL" -f migrations/week7_kb_tenant_scope.sql
psql "$DATABASE_URL" -f migrations/week7_document_ingest_status.sql
```

## Evaluation

```bash
cd backend/pipeline
python evaluation/harness.py                 # run/resume everything
python evaluation/harness.py --suite redteam
python evaluation/harness.py --only encoded,translation
python evaluation/harness.py --report-only   # rebuild the table, no API calls
```

Writes `evaluation/results/results.md` (the table) and
`evaluation/results/raw_results.json` (full responses, resumable cache).
Nothing is persisted to `conversations`, `escalations` or `support_tickets` —
both generators run with `persist=False`.

## Open issues

These are known and deliberately not silently patched.

1. ~~`POST /api/documents/upload` has no `verify_token`~~ — **fixed**. The route
   now requires a token and rejects any role other than `admin`, and the
   uploaded filename is passed through `os.path.basename` so a name like
   `../../main.py` cannot escape the temp directory.
2. ~~`user_info.tenant_id` defaults to `'uet_default'`~~ — no longer reproduces;
   every row in `user_info`, `students`, `exams` and `conversations` is `'uet'`.
3. ~~Exam-mode distance cut-off too strict~~ — **fixed**, 0.35 → 0.40 after
   measuring every red-team prompt against four cut-offs. Working and validation
   in [threshold-tuning.md](../pipeline/evaluation/results/threshold-tuning.md).
4. **`results.md` is still the 0.35 measurement.** It reports control-01 and
   control-06 as failures, which is exactly what the 0.40 cut-off was changed to
   fix, so the headline control rate (66.7%) understates current behaviour.
   Re-run `python evaluation/harness.py --refresh` when model quota allows —
   49 cases at up to 3 model calls each does not fit in a free tier's daily 20.
5. **Legacy conversation rows** contain a `retrived_chunk_id` typo and, in the
   oldest rows, cosine distances stored where chunk ids belong. Read paths
   tolerate both; no migration has been written.
6. **Older document endpoints return `{"error": ...}` with HTTP 200** rather
   than a status code. `upload` now raises proper 4xx codes; `list_documents`,
   `delete_document` and `citation-stats` still do not.
7. **`validate_sql`'s tenant check is a substring test.** `admin_analytics.py`
   requires the literal `:tenant_id` to appear somewhere in a generated query
   that touches a tenant-scoped table, which proves the placeholder is present
   but not that it actually filters each table. Admin-only, and the value bound
   to it always comes from the verified JWT, so the blast radius is small — but
   it is weaker than the surrounding code reads.
8. **First-token latency does not meet the 1-second NFR, by design.** Both the
   student and exam paths buffer the whole answer before sending a byte,
   because the escalation self-check and the invigilator guard both have to
   inspect a *finished* answer. `stream_text()` then slices it so the UI still
   types it out. Meeting the NFR literally would mean streaming unverified text
   to a student mid-exam, which is the one thing the guard exists to prevent.
9. **Transport is chunked `text/plain`, not SSE.** The spec names Server-Sent
   Events; the frontend reads the body with a `ReadableStream` reader instead.
   Functionally equivalent for a single unidirectional stream, but it is a
   deviation from the written architecture.
10. **The stack is Gemini, not OpenAI.** `gemini-3.6-flash` and
    `gemini-embedding-001` (3072-dim) stand in for GPT-4o and
    `text-embedding-3-small` (1536-dim); chunking is 500 tokens rather than 512.
