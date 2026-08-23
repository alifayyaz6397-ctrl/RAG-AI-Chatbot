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

> The checked-in `venv/` is missing `pyjwt`, `bcrypt` and `python-multipart`,
> so the app does not start with it. Install `requirements.txt` into a fresh
> environment, or use a system Python that already has them.

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

1. **`POST /api/documents/upload` has no `verify_token`.** The only
   unauthenticated write endpoint. Anyone who can reach the API can add
   documents to the knowledge base, which is also the prompt-injection surface.
2. **`user_info.tenant_id` defaults to `'uet_default'`** while every other table
   uses `'uet'`. The instructor login `farrukh` resolves to zero owned exams:
   `UPDATE user_info SET tenant_id = 'uet' WHERE username = 'farrukh';`
3. ~~Exam-mode distance cut-off too strict~~ — **fixed**, 0.35 → 0.40 after
   measuring every red-team prompt against four cut-offs. Working and validation
   in [threshold-tuning.md](../pipeline/evaluation/results/threshold-tuning.md).
   `results.md` is still the 0.35 measurement; re-run with `--refresh` to
   regenerate it at 0.40 when quota allows.
4. **Legacy conversation rows** contain a `retrived_chunk_id` typo and, in the
   oldest rows, cosine distances stored where chunk ids belong. Read paths
   tolerate both; no migration has been written.
5. **Older document endpoints return `{"error": ...}` with HTTP 200** rather
   than a status code, unlike routes added in weeks 5–6.
