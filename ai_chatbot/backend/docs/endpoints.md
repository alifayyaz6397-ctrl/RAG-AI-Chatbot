# Endpoint reference

Base URL in development: `http://127.0.0.1:8000`

All routes except `/signup` and `/login` require a bearer token:

```
Authorization: Bearer <jwt>
```

`role`, `linked_id` and `tenant_id` are read from the verified token on every
request and never from the request body. There is no endpoint that lets a
caller assert who they are.

## Conventions

| Status | Meaning |
|---|---|
| 400 | malformed input (bad `message_id`, unknown rating) |
| 401 | missing / expired / invalid token |
| 403 | authenticated but wrong role |
| 404 | not found **or** not yours — deliberately indistinguishable |
| 422 | query-parameter validation (page < 1, page_size > 100) |
| 503 | Gemini unreachable after retries |

> Some older document endpoints return `{"error": "..."}` with HTTP 200 instead
> of a status code. Endpoints added in weeks 5–6 use real status codes. The
> inconsistency is pre-existing and noted rather than silently changed.

---

## Auth

### `POST /signup`
Student self-registration. The `student_id` must already exist in `students`.

```json
{ "student_id": "2025-CS-01", "username": "ali", "password": "..." }
```
→ `{ "access_token": "...", "role": "student" }`

### `POST /login`
```json
{ "username": "ali", "password": "..." }
```
→ `{ "access_token": "...", "role": "student|instructor|admin" }`

### `GET /me`
→ `{ "role", "linked_id", "tenant_id", "username" }`

---

## Chat

### `POST /api/chat` — general student chat
```json
{ "question": "What are the exam conduct rules?" }
```

Returns a **plain-text stream** (`text/plain`). The escalation verdict is
carried in response headers, never in the body:

| Header | Example | Meaning |
|---|---|---|
| `X-Escalation-Offered` | `true` / `false` | whether a human hand-off was offered |
| `X-Confidence` | `0.7592` | cosine similarity of the best chunk |
| `X-Conversation-Id` | `conv-188` | id of the stored conversation |
| `X-Ticket-Id` | `ticket-002` | present only when a ticket was opened |

These are listed in the CORS `expose_headers` config; browser JS cannot read
custom headers otherwise.

When escalation is offered, the body also ends with a plain-English sentence
offering staff follow-up, so a client that ignores the headers still behaves
reasonably.

### `POST /api/exam/chat` — invigilator (students only)
```json
{ "question": "Am I allowed to use a calculator?" }
```
Plain-text stream. Restricted to `document_type='exam_rules'` chunks and
guarded by a second model pass. Non-students receive an error.

### `POST /api/instructor/chat` — analytics (instructors only)
```json
{ "question": "Which section are my students weakest in?" }
```
Returns **JSON**, not a stream, because the payload is a result table:

```json
{
  "answer": "Your students are weakest in the ShortAnswer section...",
  "intent": "section_performance",
  "confidence": 0.95,
  "params": { "exam": null, "section": null, "start_date": null, "end_date": null },
  "data": {
    "title": "Average score per section (weakest first)",
    "columns": ["section", "scores_counted", "average_score_percent", "..."],
    "rows": [["ShortAnswer", 253, 67.34, 17.0, 100.0]]
  },
  "resolved": true,
  "conversation_id": "conv-151"
}
```

`resolved: false` with `data: null` means the question could not be mapped to
one of the four reports; `answer` then explains what can be asked instead.

- `403` — caller is not an instructor
- `503` — classification could not run

### `GET /api/instructor/exams`
The exams this instructor owns — lets a UI show what is reportable.

---

## Conversation history

### `GET /api/conversations`
The caller's own conversations, newest first.

| Query | Default | Notes |
|---|---|---|
| `page` | 1 | ≥ 1 |
| `page_size` | 20 | 1–100 |
| `mode` | — | `general` \| `exam` \| `instructor` |

```json
{
  "conversations": [
    { "id": "conv-140", "user_id": "2026-SE-03", "role": "student",
      "mode": "exam", "rating": null, "escalated": true,
      "created_at": "2026-08-11T09:25:25", "message_count": 2,
      "preview": "can i have extra time?" }
  ],
  "page": 1, "page_size": 20, "total": 99, "has_more": true
}
```

### `GET /api/conversations/{conversation_id}`
Full message list plus cited chunk ids.

```json
{
  "id": "conv-138", "mode": "exam", "escalated": false,
  "messages": [
    { "role": "user", "content": "what are exam rules?", "retrieved_chunk_ids": [] },
    { "role": "assistant", "content": "During your exam...",
      "retrieved_chunk_ids": [888, 889, 895] }
  ],
  "retrieved_chunk_ids": [888, 889, 895]
}
```

Admins may read any conversation **within their own tenant**. Anyone else
reading someone else's gets `404`, identical to a genuinely missing id.

Historical rows contain two legacy typos (`assisstant`, `retrived_chunk_id`);
the read path normalises both, so clients only ever see `assistant` and
`retrieved_chunk_ids`.

### `GET /api/admin/conversations` — admin only
Same shape as `/api/conversations`, across all users in the admin's tenant.

Filters: `user_id`, `role`, `mode`, `escalated`, plus `page` / `page_size`.

---

## Feedback

### `POST /api/feedback`
```json
{ "message_id": "conv-140:1", "rating": "down", "comment": "wrong info" }
```

`message_id` is `"<conversation_id>:<message_index>"`. Messages live inside a
jsonb array and have no id of their own, so this pair is the address.

Rules enforced:
- rating must be `up` or `down`
- the target must be an **assistant** message (index 0 is normally the question)
- the conversation must be visible to the caller
- one vote per user per message — re-posting updates the existing row

→ `{ "feedback_id": 12, "message_id": "conv-189:1", "rating": "down", ... }`

### `GET /api/admin/feedback` — admin review queue (admin only)
Query: `rating` (default `down`), `limit` (1–200).

```json
{
  "totals": { "up": 0, "down": 7 },
  "weak_documents": [
    { "document_id": 26, "filename": "Accessibility_Accommodations.pdf",
      "negative_count": 2, "chunks_implicated": 1 }
  ],
  "weak_chunks": [
    { "chunk_id": 887, "document_id": 26,
      "filename": "Accessibility_Accommodations.pdf",
      "chunk_preview": "UET Lahore -- Accessibility and Accommodation...",
      "negative_count": 2 }
  ],
  "items": [
    { "feedback_id": 5, "message_id": "conv-131:1", "mode": "exam",
      "question": "My extra time accommodation isn't showing",
      "answer_preview": "...", "comment": "answer did not match the rules doc" }
  ]
}
```

`weak_documents` is the point of the endpoint: it walks down-votes → cited
chunks → source document, so a weak knowledge-base file is visible directly
rather than inferred by reading complaints.

Answers that cited nothing still appear in `items` — those are the
hallucination candidates.

---

## Documents (admin)

| Route | Notes |
|---|---|
| `GET /api/documents` | list with chunk counts |
| `POST /api/documents/upload` | `.pdf` / `.md`, 20 MB cap, `document_type` defaults to `general`; use `exam_rules` to make a doc visible to the invigilator |
| `GET /api/documents/{id}/chunks` | chunk preview |
| `DELETE /api/documents/{id}` | deletes chunks then the document |
| `GET /api/documents/citation-stats` | retrieval counts per document |

> `POST /api/documents/upload` currently has **no `verify_token` dependency** —
> it is the one write endpoint that is unauthenticated. Flagged, not changed,
> because fixing it changes behaviour the frontend may rely on.

---

## Exam mode

### `GET /api/exam_mode`
→ `{ "exam_mode": true }` when the caller has an exam in progress right now
(matched on department + semester against `exams.start_at` / `end_at`).
The frontend uses this to decide whether to call `/api/chat` or `/api/exam/chat`.
