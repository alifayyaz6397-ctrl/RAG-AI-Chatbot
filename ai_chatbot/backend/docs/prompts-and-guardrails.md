# Prompt and guardrail design

## The governing idea

Prompts are treated as **unreliable** controls. Anything that must hold — who
can see which rows, which documents a mode may retrieve, whether an answer
reaches a student — is enforced in SQL or in Python, where a cleverly worded
message cannot reach it. Prompts do the work that only prompts can do: shaping
tone, extracting structure, and judging text.

Every mode therefore has at least one control that survives a fully
prompt-injected model.

| Mode | Control that holds even if the prompt is defeated |
|---|---|
| Invigilator | retrieval restricted to `document_type='exam_rules'`; output cleared by a separate guard call before emission |
| Instructor | four fixed SQL templates; `tenant_id` + `owner_instructor_id` filters from the JWT |
| General | grounding self-check; escalation offer |

## Invigilator

### System prompt

Structured as an allow-list, not a deny-list. It names the three things the
invigilator may discuss (rules, time remaining, how to report a technical
issue), then enumerates what it must never do.

Two prohibitions exist because of specific observed failures:

- **No false claims of action.** The model would otherwise say "I will escalate
  this to your supervisor immediately" or "please remain at your computer while
  this is investigated". It cannot do either — it has no side effects — and
  saying so misleads a student mid-exam.
- **No commentary on routing.** Technical, medical and accommodation messages
  are classified and handled deterministically *before* the model is reached, so
  the model must not speculate about escalation status it cannot observe.

The prompt also specifies an exact refusal string, which is what makes
deterministic scoring in the evaluation harness possible.

### Routing classifier

A four-way router runs first: `TECHNICAL` / `MEDICAL` / `ACCOMMODATION` /
`OTHER`. Three of the four never reach a generative model — they return fixed
text and write a durable escalation row.

Every category is anchored with **both** a positive and a deliberately similar
negative example:

| Positive | Near-miss negative |
|---|---|
| "The submit button isn't working" → TECHNICAL | "How do I submit my exam?" → OTHER |
| "I feel dizzy right now" → MEDICAL | "I have a headache, will there be a break?" → OTHER |
| "My approved extra time isn't showing" → ACCOMMODATION | "Can I use a calculator?" → OTHER |

Without the negatives the classifier pattern-matches on topic words ("submit",
"time") rather than on *is something actually wrong right now*. Ties resolve to
`OTHER`, which is the branch that still passes through retrieval and the guard.

### Output guard

A second, independent model call classifies the drafted answer as SAFE or
UNSAFE before any of it is emitted.

It is framed around the **answer**, not the question, which is what makes it
robust to indirect attacks. Whether the request arrived as a translation, a
roleplay, a hypothetical or base64, the guard sees the same thing: a draft that
either does or does not explain an academic concept.

Explicitly UNSAFE:
- explaining or defining any academic concept, however briefly, in any language
- claiming to have escalated, notified or contacted anyone
- confirming or denying an accommodation status
- revealing or paraphrasing its own instructions

Explicitly SAFE: exam logistics — time, duration, permitted materials,
misconduct rules, self-service steps for reporting a fault. Naming a syllabus
topic is safe; explaining what it means is not.

### Fail-closed

If Gemini is unreachable after retries, `guard_check` returns `False` and the
student receives the refusal. An answer that could not be verified is treated as
unsafe. This is the deliberate opposite of `escalation.self_check`, which fails
open — there, an outage that manufactured support tickets would be the worse
outcome.

This asymmetry has a measurement consequence: a refusal caused by an outage is
indistinguishable, from the outside, from a refusal caused by a guard verdict.
`llm.UNAVAILABLE_COUNT` exists so the evaluation harness can tell them apart and
discard degraded measurements rather than scoring an outage as a guardrail
decision.

## Instructor analytics

The model never writes SQL. It maps a question onto one of four registered
intents and extracts at most four parameters:

```json
{"intent": "section_performance", "confidence": 0.93,
 "params": {"exam": null, "section": "MCQ",
            "start_date": "2026-06-01", "end_date": null}}
```

Everything downstream is hand-written and parameterised. The worst a prompt
injection achieves is selecting the wrong template — it cannot reach another
instructor's exams, another tenant, or any other table.

Defence in depth on the extracted parameters:

- `intent` must be a member of the registry or the request falls back
- `confidence` below 0.6 → fallback, no query runs
- dates are parsed with `date.fromisoformat` and dropped if malformed
- strings are trimmed and length-capped
- exam names resolve only against exams the caller owns

### Report writer

The final call receives the query rows as JSON and is told every figure must
appear verbatim in them. It may rank and compare ("the lowest of the three")
but never compute. If the model is unavailable the rows are rendered
deterministically instead — the query already succeeded, so returning real
numbers in a flat format beats failing the request.

### Fallback wording

Low confidence produces a message that says what *can* be asked, with examples.
A bare "I don't understand" trains users to give up; naming the four available
reports turns a failure into instructions.

## General chat

The weakest prompt of the three, by design — this mode is allowed to be
helpful. Grounding is enforced afterwards by the self-check rather than by
prompt wording, on the reasoning that "only use the context" is advice a model
may quietly ignore, whereas a separate grader reading the finished answer is
a check it cannot talk its way past.

## What the evaluation actually showed

Full results: [`../pipeline/evaluation/results/results.md`](../pipeline/evaluation/results/results.md)

- **33/33 adversarial prompts refused (100%)** — direct asks, indirect asks,
  roleplay/jailbreak framing, translation tricks and encoded prompts. Meets the
  NFR target.
- **10/10 unsupported questions abstained (100%)** — no fabricated dean names,
  phone numbers or fees.
- **4/6 control questions answered** — two legitimate logistics questions were
  refused. Root cause was retrieval, not the guard: the distance cut-off
  discarded the chunk holding the answer. Fixed by moving the cut-off to 0.40,
  after which all four re-measured controls answer correctly and the two
  affected adversarial prompts still refuse.

The third number is the one that mattered most. A 100% refusal rate is
trivially achievable by refusing everything; the control cases exist precisely
to stop that from looking like success — and they caught a real defect that the
adversarial suite, at a perfect score, could not see.

## Prompt-injection surface

| Vector | Status |
|---|---|
| Direct instruction override | blocked — output guard judges the draft, not the framing |
| Roleplay / fiction | blocked |
| Translation | blocked — guard is language-agnostic about explanations |
| Encoding (base64, ROT13, leetspeak, reversal) | blocked |
| System-prompt extraction | blocked — guard treats paraphrase of its rules as UNSAFE |
| Indirect content fishing | blocked |
| **Poisoned knowledge base** | **not addressed** — an admin uploading a document containing instructions is trusted. Retrieved chunks are interpolated into prompts without delimiting or neutralising. |

The last row is the real remaining gap. Upload is admin-only, which is the
mitigation today — but note that `POST /api/documents/upload` currently has no
`verify_token` dependency at all, which makes that mitigation theoretical rather
than actual.
