# ADR-0011: Claim-centric learning memory from agent sessions

**Status:** proposed (PoC under measurement) · **Date:** 2026-09-10 · **Supersedes (if the gates pass):**
the retrieval half of PR #18 (`memory_recall` over legacy concepts, ontology as a recall arm).
Retains PR #18's capture half (native evidence, hash binding, the bound-proof trigger design).

## Context

StudyLoop's memory is one SQLite file holding 5,879 sessions from six coding-agent harnesses.
Measured on a blind, council-authored gold set of 175 questions (`receipts/gold-v2-receipt.json`):

- the shipped keyword path scores macro recall@5 **0.107** and throws on 46 % of natural questions;
- 53 % of stored messages are tool echoes flattened into `assistant` rows; 6,591 are exact duplicates;
- the learning tier (`study_progress`, `parked_topics`, `teach_back_scores`, `concepts`) holds **0 rows**;
- evidence exists for 618 sessions; the originals of the other 5,261 have been rotated away by the
  harnesses, so `sessions.db` is the only surviving copy of that history;
- the only layer that ever out-scored raw text was full-context distillation into claims
  (0.64 vs 0.48 at PoC; cheap truncated extraction lost at 0.24).

The learner's voice is 18,540 messages (13 %), 6,608 of them questions: small, dense, role-labelled.

## Decision

Capture is lossless and dumb; usefulness is **derived at capture time**, provenance-bound, and never
left to agent discipline at session end. Concretely:

1. **Canonical typed events**, not flat messages. Every adapter emits `kind ∈ {user, assistant_prose,
   tool_call, tool_result, system, thinking, error}` and a `turn_id` from the parser.
2. **Evidence in the same transaction as events.** Native bytes where the harness still has them;
   for the archive, the prose we hold, labelled `basis=REPORTED, origin=archive`.
3. **Derivation runs in the export sweep.** A deterministic pass ($0) threads turns into exchanges,
   flags questions/errors/retries, tags concepts, detects cross-session recurrence, and writes the
   learning tier. A budgeted model pass distils exchanges into **claims** (Problem · Finding ·
   Decision · Procedure · Preference), each quote-bound by trigger, with sub-agent outcomes rolled
   up through lineage; Findings seed review items.
4. **Claims are the retrieval unit.** Serve claims first (latest non-superseded, with quote and
   provenance), sessions as drill-down. Index prose only. Embed claims, never messages.
5. **Lineage and harness/project are claim metadata**, usable as filters. The tier-1 ontology is
   not a recall arm.
6. **Session ids are unchanged** from today's exporters so every existing gold question, receipt and
   pin scores the new store without translation.

## Canonical model (PoC schema, package `packages/learning-memory`, own SQLite file)

```sql
sessions(id PK, harness, project, branch, parent_id NULL REFERENCES sessions, started_at, ended_at, scope, intent, outcome)
events(id PK, session_id FK, turn_id INT, seq INT, kind CHECK(kind IN (...)), actor, text, tool_name, ts,
       content_hash, UNIQUE(session_id, content_hash))
evidence(id PK = sha256(payload), session_id FK, body, body_sha256, origin, basis, captured_at)
lineage(parent_id FK, child_id FK, PRIMARY KEY(parent_id, child_id))
prose_fts  -- FTS5 external-content over events WHERE kind IN ('user','assistant_prose'); tokenize measured (porter vs unicode61)
exchanges(id PK, session_id FK, turn_id, question_event_id, answer_event_ids JSON, is_question, had_error, retried, resolved)
concept_tags(exchange_id FK, concept, source CHECK(source IN ('vocab','alias','model')))
recurrence(concept, session_ids JSON, first_seen, last_seen, count)
claims(id PK, session_id FK, kind CHECK(kind IN ('Problem','Finding','Decision','Procedure','Preference')),
       title <=120, statement <=500, tags JSON 2..5, confidence 0.5..1.0, writer, created_at, supersedes NULL FK)
claim_citations(claim_id FK, evidence_id FK, start INT, end INT, quote)   -- code-point offsets
  TRIGGER claim_citation_bound_proof BEFORE INSERT: RAISE(ABORT) unless substr(evidence.body, start+1, end-start) = quote
  TRIGGER claims_immutable BEFORE UPDATE ON claims: RAISE(ABORT)
claim_relations(from_id, to_id, kind CHECK(kind IN ('supports','contradicts','corrects')))
review_items(id PK, claim_id FK, front, back, kind CHECK(kind IN ('flashcard','quiz','teach_back')), created_at)
```

Invariants (property-tested): re-import is a no-op by `content_hash`; no session row without ≥1
evidence row; a claim cannot be inserted with a non-binding quote; claims never change.

## Adapter contract

```python
class HarnessAdapter(Protocol):
    harness: str
    def discover(self) -> Iterable[SourceRef]: ...          # path or store row; mtime, size
    def parse(self, ref: SourceRef) -> ParsedSession: ...   # Session, list[Event], native_source: bytes, lineage: list[str]
```

The shared base owns dedupe, evidence, lineage, derivation. Each adapter ships a scrubbed golden
fixture and passes the shared contract suite: no tool text in prose events; `turn_id` on every event;
native source present; lineage where the harness supports sub-agents. The **archive adapter** reads
`sessions.db` and classifies `kind` deterministically; it is the only path for history.

## Derivation rules (deterministic pass)

- Exchange = a `user` event plus all following non-`user` events until the next `user` event.
- `is_question`: user text contains `?` or begins with an interrogative; `had_error`: any `error`
  or `tool_result` matching a failure lexicon in the exchange; `retried`: same tool_call signature
  twice; `resolved`: the exchange ends with `assistant_prose` and the next user turn is not a repeat.
- Concept tags: match the learner's topic vocabulary (`studyloop.topics`) and aliases; model tags
  only in the model pass, marked `source='model'`.
- Recurrence: a concept tagged in ≥ 2 distinct sessions ≥ 1 day apart → `struggled` backlog item.
- `intent` = first user event's prose (≤ 200 chars); `outcome` = last resolving `assistant_prose`.

## Evaluation binding

The PoC is scored by the frozen ruler (`validation-ruler.md @ a98331af`) on gold v2 (DEV in repo,
SEALED outside) with the existing harness: G1 (recall lift ≥ +0.05, macro ≥ 0.64), G2 (binding +
entailment audit), G4 (claim embeddings), G6 (decision correctness), operational budgets, G5 pilot.
**Answer-grain** — whether the top returned claim contains the gold's atomic answer — is reported
alongside recall@5 on every receipt. Every arm keeps the same session ids as `sessions.db`.

## Consequences

- If the gates pass: PR #18's `memory_recall`/legacy-concept path is superseded; its native
  capture and trigger design live on inside this package's store.
- If they fail: the record says which layer failed to lift, on a sealed set, with receipts.
- The live `sessions.db` is never written by the PoC; learning-tier export lands on a work copy.
- Retention becomes an explicit contract: harnesses rotate transcripts within weeks, so the sweep
  cadence and a doctor check on "age of last capture" are load-bearing.

## Open questions (to be settled by measurement, not debate)

Tokenizer for `prose_fts`/claims (porter vs unicode61); whether embeddings on claims clear G4;
whether lineage roll-up lifts relational recall; whether Findings make acceptable review items.
