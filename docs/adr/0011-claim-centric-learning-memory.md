# ADR-0011: Claim-centric learning memory from agent sessions

**Status:** **measured — not established** (see *Outcome*, 2026-09-10) · **Version:** 1.2 (outcome recorded) · **Date:** 2026-09-10 · **Would have superseded (gates did not pass):**
the retrieval half of PR #18 (`memory_recall` over legacy concepts, ontology as a recall arm).
Retains PR #18's capture half (native evidence, hash binding, the bound-proof trigger design).

## Superseded sections (2026-09-10)

**The claim-centric learning-memory decision recorded in this ADR stands.** What is retired is
every reference below to the knowledge layers the owner ruled out of the solution on 2026-09-10:
**OKF import**, the **tier-1 ontology** (migration v48) and the **concept sidecar** (migration
v49, `memory_winddown`). Those layers, their code, their CLI verbs and their MCP surfaces are
removed from the product with no remnants — see
`docs/architecture/session-memory/receipts/okf-removal-inventory-2026-09-10.md`.

Read every mention of them in this document as **historical record only (RETIRED 2026-09-10)**,
never as a description of shipped or planned behaviour. Two mentions remain, deliberately
unedited, because they are load-bearing history rather than product description:

- the **Status** line above, which records what this ADR *would have* superseded had the gates
  passed (`memory_recall` over legacy concepts, ontology as a recall arm) — RETIRED 2026-09-10;
- **Decision point 5**, whose clause "The tier-1 ontology is not a recall arm" was already a
  negative constraint and is now moot, the ontology having been removed entirely — RETIRED
  2026-09-10.

The claims-and-evidence store (`packages/learning-memory`), the canonical typed-event model, the
derivation rules and the Outcome record are **not** affected by the ruling and remain in force.

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
2. **Evidence in the same transaction as events, one row per prose event.** The citation surface
   is the event, not the session: every `user`/`assistant_prose` event gets an evidence row whose
   body is that event's text (`origin=archive, basis=REPORTED` for history), so a claim's offsets
   survive re-derivation, reclassification and reordering, and quote ambiguity is bounded by one
   message. Where the harness still has the native transcript, its raw bytes are retained as an
   `OBSERVED` capture row alongside. Evidence is append-only (triggers refuse UPDATE/DELETE).
   *(v1.1 — council finding 7; the v1.0 session-sized concatenated body was withdrawn.)*
3. **Derivation runs in the export sweep.** A deterministic pass ($0) threads turns into exchanges,
   flags questions/errors/retries, tags concepts, detects cross-session recurrence, and writes the
   learning tier. A budgeted model pass distils exchanges into **claims** (Problem · Finding ·
   Decision · Procedure · Preference), **each with at least one quote-bound citation — enforced by
   the database, not the caller** (citations are written first under a deferred FK; an AFTER
   INSERT trigger aborts a citation-less claim), with sub-agent outcomes rolled up through
   lineage; Findings seed review items.
4. **Claims are the retrieval unit.** Serve claims first, sessions as drill-down. Index prose only.
   Embed claims, never messages. Read contract *(v1.1)*: a claim is **active** iff no claim
   `supersedes` it; **disputed** iff an active claim `contradicts` it; retrieval returns active
   claims and marks disputed ones, never silently dropping either. Supersession is same-session-
   or-lineage only; a cross-session replacement is a `corrects` relation. Natural-language input
   to any search surface goes through a planner that phrase-quotes every token — raw FTS syntax is
   a separate, explicit API.
5. **Lineage and harness/project are claim metadata**, usable as filters. The tier-1 ontology is
   not a recall arm.
6. **Session ids are unchanged** from today's exporters so every existing gold question, receipt and
   pin scores the new store without translation.

## Canonical model (PoC schema, package `packages/learning-memory`, own SQLite file)

```sql
sessions(id PK, harness, project, branch, parent_id NULL REFERENCES sessions, started_at, ended_at, scope, intent, outcome,
         classifier_version, adapter_version)                       -- v1.1: provenance of the typing
events(id PK, session_id FK, turn_id INT, seq INT, kind CHECK(kind IN (...)), actor, text, tool_name, ts,
       content_hash, UNIQUE(session_id, content_hash))
  -- v1.1: content_hash covers (turn_id, seq, kind, actor, tool_name, text): every observed occurrence is a row;
  --       re-parse of the same source is still a no-op. Adjacent exporter duplicates are the adapter's to collapse.
evidence(id PK = sha256(payload), session_id FK, event_id NULL FK, body, body_sha256, raw BLOB NULL, origin, basis, captured_at)
  -- v1.1: one REPORTED row per prose event (event_id set); one OBSERVED row per native capture (raw bytes retained)
  TRIGGER evidence_immutable BEFORE UPDATE / BEFORE DELETE: RAISE(ABORT)
lineage(parent_id FK, child_id FK, PRIMARY KEY(parent_id, child_id))
lineage_pending(child_id FK, parent_id TEXT, PRIMARY KEY(child_id, parent_id))   -- v1.1: reconciled when the parent lands
prose_events  -- VIEW: SELECT id, text FROM events WHERE kind IN ('user','assistant_prose')
prose_fts     -- FTS5 external-content over prose_events (v1.1: so 'rebuild' stays prose-only); tokenize measured
exchanges(id PK, session_id FK, derivation_version, turn_id, question_event_id, answer_event_ids JSON,
          is_question, had_error, retried, resolved, UNIQUE(session_id, derivation_version, turn_id))
concepts(id PK, canonical)  concept_aliases(alias PK, concept_id FK)                  -- v1.1
concept_tags(exchange_id FK, concept_id FK, source CHECK(source IN ('vocab','alias','model')))
concept_occurrences(concept_id FK, session_id FK, derivation_version, observed_at)   -- v1.1: replaces recurrence.session_ids JSON
claims(id PK, session_id FK, kind CHECK(kind IN ('Problem','Finding','Decision','Procedure','Preference')),
       title <=120, statement <=500, tags JSON 2..5, confidence 0.5..1.0, writer, created_at, supersedes NULL FK)
  -- v1.1: id covers the canonical citation-set fingerprint and supersedes (Stage E)
claim_citations(claim_id FK DEFERRABLE INITIALLY DEFERRED, evidence_id FK, start INT, end INT, quote)   -- code-point offsets
  TRIGGER claim_citation_bound_proof BEFORE INSERT/UPDATE: RAISE(ABORT) unless substr(evidence.body, start+1, end-start) = quote
  TRIGGER claims_need_citation AFTER INSERT ON claims: RAISE(ABORT) unless ≥1 claim_citations row exists   -- v1.1
  TRIGGER claims_immutable BEFORE UPDATE ON claims: RAISE(ABORT)
claim_relations(from_id, to_id, kind CHECK(kind IN ('supports','contradicts','corrects')))
review_items(id PK, claim_id FK, front, back, kind CHECK(kind IN ('flashcard','quiz','teach_back')), created_at)
```

Invariants (property-tested): re-import of the same source is a no-op; every observed event
occurrence is a row; no session row without ≥1 evidence row; evidence never changes; a claim
cannot exist without a binding citation; claims never change; an FTS rebuild indexes no tool text;
a child ingested before its parent acquires its lineage edge when the parent lands.

## Adapter contract

```python
class HarnessAdapter(Protocol):
    harness: str
    def discover(self) -> Iterable[SourceRef]: ...          # path or store row; mtime, size
    def parse(self, ref: SourceRef) -> ParsedSession: ...   # Session, list[Event], native_source: bytes, lineage: list[str]
```

The shared base owns dedupe, evidence, lineage, derivation. *(v1.1)* `SourceRef` carries
`source_sha256`; `ParsedSession` carries `adapter_version`, `classifier_version` and
`exporter_dupes_collapsed` (adjacent identical rows the adapter folded before emitting — 37,528 in
the archive). Each adapter ships a scrubbed golden fixture and passes the shared contract suite:
no tool text in prose events; `turn_id` on every event and `(turn_id, seq)` monotone; a closed
actor vocabulary; ISO-8601 UTC `ts`; `Session.id` derived from the source; native source present
where the harness has one; lineage where the harness supports sub-agents. The **archive adapter**
reads `sessions.db` and classifies `kind` deterministically under a named `classifier_version`; it
is the only path for history.

## Derivation rules (deterministic pass)

*(v1.1)* These rules ship as `derive.py` under a `derivation_version`, with a hand-labelled
cross-harness fixture set (≥ 20 exchanges per harness, labelled by the orchestrator, not a model)
and one test per rule. Events that cannot be threaded deterministically are quarantined
(`exchanges.resolved = NULL`, reason recorded), never guessed.

- Exchange = a `user` event plus all following non-`user` events until the next `user` event,
  correlated by `turn_id`, tool-call id where the harness has one, and lineage for sub-agent
  traffic.
- `is_question`: user text contains `?` or begins with an interrogative; `had_error`: any `error`
  or `tool_result` matching a versioned failure lexicon in the exchange; `retried`: same
  `(tool_name, normalised arguments)` twice in one exchange; `resolved`: the exchange ends with
  `assistant_prose` and the next user turn is not a repeat.
- Concept tags: match the learner's topic vocabulary (`studyloop.topics`) through `concepts` +
  `concept_aliases` (canonical id, casing-insensitive); model tags only in the model pass, marked
  `source='model'`.
- Recurrence: a concept with `concept_occurrences` in ≥ 2 distinct sessions ≥ 1 day apart →
  `struggled` backlog item.
- `intent` = first user event's prose (≤ 200 chars); `outcome` = last `assistant_prose` of the last
  `resolved` exchange.

## Evaluation binding

The PoC is scored by the frozen ruler (`validation-ruler.md @ a98331af`) on gold v2 (DEV in repo,
SEALED outside) with the existing harness: G1 (recall lift ≥ +0.05, macro ≥ 0.64), G2 (binding +
entailment audit), G4 (claim embeddings), G6 (decision correctness), operational budgets, G5 pilot.
**Answer-grain** — whether the top returned claim contains the gold's atomic answer — is reported
alongside recall@5 on every receipt. Every arm keeps the same session ids as `sessions.db`.

*(v1.1 — council finding 13)* Every arm receipt carries a **run manifest**: adapter versions,
`classifier_version`, `derivation_version`, writer model id + prompt sha256 + parameters, corpus
digest, store schema version. The single SEALED look is executed on a **fresh work copy rebuilt
from the manifest**, never on the store the DEV looks were tuned against.

## Consequences

- If the gates pass: PR #18's `memory_recall`/legacy-concept path is superseded; its native
  capture and trigger design live on inside this package's store.
- If they fail: the record says which layer failed to lift, on a sealed set, with receipts.
- The live `sessions.db` is never written by the PoC; learning-tier export lands on a work copy.
- Retention becomes an explicit contract: harnesses rotate transcripts within weeks, so the sweep
  cadence and a doctor check on "age of last capture" are load-bearing.

## Implementation notes accepted from Stage B (2026-09-10) — as revised by the council (v1.1)

- ~~`lineage` edges whose parent is not yet ingested are deferred and land on the child's re-ingest~~
  **Withdrawn (council 6):** reproduced as data loss — the edge never landed when the parent arrived
  later. Replaced by `lineage_pending`, reconciled in the parent's ingest transaction.
- ~~`content_hash` covers text and kind, not position, so exact duplicates collapse~~ **Withdrawn
  (council 5):** on the archive this collapses 54.7% of user/assistant rows, including every
  repeated tool call in a session, so `retried` could never fire. Position is in the hash; adjacent
  exporter duplicates are collapsed by the adapter and counted.
- `body_sha256` is taken over native bytes for `OBSERVED` evidence and over the UTF-8 prose for
  `REPORTED`; the row is a capture receipt of what was actually read. *(v1.1: raw bytes retained.)*
- Hardening beyond the ADR text: `claim_citations` CHECKs `length(quote) > 0` and `end > start`
  (a zero-width extent would bind vacuously), and a BEFORE UPDATE twin of the bound-proof trigger
  so citations cannot be rebound after the fact.
- `INSERT OR IGNORE` was rejected for events because it swallows CHECK and FK violations; the
  dedupe conflict is handled explicitly and any other violation fails the whole ingest.

## Council record

Two-family adversarial review of v1.0 + the Stage B store (gpt-5.6-terra REJECT/10 blocking;
deepseek-3.2 APPROVE-WITH-CHANGES/7 blocking). Seven defects reproduced by the orchestrator against
the committed store; dispositions of all 42 findings in
`docs/architecture/session-memory/receipts/council-adr-0011.md`. v1.1 is this document. Stage B.1
(store hardening) precedes any corpus ingest; its acceptance tests are the seven reproductions
flipping to refused/correct.

## Implementation notes accepted from Stage B.1 (2026-09-10)

Schema v2; all seven reproductions flipped under the orchestrator's own probes (132 tests; every
new guard proven load-bearing by removing it and watching its test fail — 17/17).

- **Evidence ids are content-addressed within a session**, so identical prose text shares one
  evidence row whose `event_id` names the first occurrence. Forced by "reordering changes no
  existing evidence id": any position-bearing id would mint fresh rows on a reordered re-parse and
  strand old citations. Ambiguity is unaffected (the body is still one message); every occurrence
  remains reachable from a citation by body-join, so drill-down is intact.
- `ParsedSession.evidence_basis` removed: basis and origin are derived from what the store actually
  received (`native` when bytes are present, else `archive`), so a caller-set label could not be
  authoritative. The zero-evidence guard counts *citable* rows (`event_id IS NOT NULL`), so a
  tool-only session is rejected even when native bytes are held.
- `sessions.parent_id` is not retro-filled when a parent lands late — `lineage`/`lineage_pending`
  is the edge record; a declared `parent_id` is also treated as a lineage edge.
- `adapter_version` defaults to `"unspecified"`; Stage C's contract suite refuses the default.
- Planner strips `Cc`/`Cs` code points before phrase-quoting: FTS5 parses its expression as a C
  string, so a NUL truncates the phrase and the closing quote is never seen (found by the property
  test, not by hand).
- **Consequence surfaced by B.1:** with append-only evidence and `evidence.event_id` a real FK,
  prose events are effectively undeletable. Redaction or secret-scrubbing is therefore a
  *new-row / new-store* operation (re-capture under a new `classifier_version` with the scrubbed
  text; the old rows stay for the citations that bound to them, or the store is rebuilt from
  scrubbed sources). No such policy exists yet; it is a Stage E prerequisite for any claim that
  cites command output, and a Stage H item for the doctor.

## Implementation notes accepted from Stage C.1 — archive adapter (2026-09-10)

Whole archive ingested read-only (`file:…?mode=ro`; the live DB's mtimes predate the run) into
`~/.local/share/studyloop/knowledge-proof/learning-memory.db`: **5,838 of 5,879 sessions, 106,362
events, 52,034 citable per-event evidence rows, 485 lineage edges, 15.9 s, 264 MB.** Accounting
closes exactly: 143,903 archive messages = 106,362 events + 37,354 adjacent exporter duplicates
collapsed + 187 rows inside the 41 rejected sessions. FTS holds 59,547 docs = 59,547 prose events,
zero non-prose. Receipt: `ingest-archive-v1.json` (copied to `receipts/`).

Corpus facts that corrected the brief (all measured by the adapter, recorded in its module docstring):

- **Tool markers carry no arguments — ever.** 75,493 `[tool:NAME]` rows are bare; the 4 "payloads"
  are a second marker. The archive records *that* a tool ran and its name, never its input or
  output. Consequence for Stage D: `retried` on history can only mean *same tool name twice in an
  exchange*; the ADR's `(tool_name, normalised arguments)` form applies to native captures only.
- **`messages.seq` cannot order a transcript** (678 NULL, 924 duplicate pairs, 5,615 sessions not
  starting at 0); order is `messages.id`. **`sessions.content_hash` is NULL for every row**, so
  `source_sha256` is computed over the session's `(id, content)` rows.
- **`source_session_id` self-references** in 126 non-`agent-*` sessions are skipped and counted;
  the 485 `agent-*` parent edges are exactly as measured and every parent exists. **2,992 `agent-*`
  sessions have no recoverable parent** — lineage roll-up is testable on 485 sessions only.
- **Learner voice hides inside XML for two harnesses.** Kilocode wraps the request in `<task>`,
  grok in `<user_query>`; a blanket "user XML → system" rule discarded 395 rows and rejected 167
  sessions (126 kilocode sessions had nothing else). Classifier allowlist
  `USER_PROSE_XML_TAGS = {task, user_query}` keeps them as `user` **with the wrapper intact** —
  unwrapping would make the citation surface bytes the archive never held. Rejections fell to 41,
  all `NoEvidenceError` and all verified machine-only (15 with no user/assistant rows; 19 gemini
  single-error sessions; 7 LiteLLM envelope pairs; 5 pure harness injections).
- **Judgement calls, held by the orchestrator:** `<teammate-message>` (149 rows) stays `system` —
  an orchestrator's brief to a sub-agent is directive prose but not the learner's voice, which is
  what the ADR measures. Roo/Kilocode XML tool invocations (`<execute_command>`, `<read_file>`, …;
  163 rows) are `tool_call`, honouring the contract's "no tool text in prose events";
  `<think>`/`<thinking>`/`<scratchpad>` (19) are `thinking`.
- **Digest.** `corpus_digest` is the pinned `score.py` function, imported not reimplemented; on the
  DEV split it yields `9aa2b495…`, identical to `baseline-dev-031dbab9.json`. The `a0df30bb…` value
  in the gold receipts is the *whole-gold* digest and includes SEALED sessions, which no builder
  run may read; the orchestrator's brief cited the wrong one. Receipts name which split they digest.
- Smoke on the real store (orchestrator, scratch copy): the DEV baseline's crashing query returns a
  relevant top hit in 360 ms cold / 31 ms warm (p95 40 ms over 20 natural queries; budget ≤ 500 ms);
  a real archive quote binds a claim; a fabricated quote is refused.

## Implementation notes accepted from Stage D — deterministic derivation (2026-09-10)

`derive-v1` over the whole store: **5,838 sessions in 19.3 s; 15,995 exchanges (11,860 threaded =
exactly the `user` event count; 4,135 quarantined `pre_first_user`); 109 concepts from the shipped
`extractors/topic_vocab.json` (sha `203020fa…`), 35,136 tags, 25,571 occurrences, 106 recurrence
candidates; intent 91.9 % (the rest have no `user` event), outcome 37.6 %.** Idempotent on the
real corpus: a second run reproduces byte-identical content hashes on all four written surfaces.

- The ADR's `studyloop.topics` vocabulary is the learner's **three** configured areas — too coarse
  to derive a graph from. The shipped `extractors/topic_vocab.json` (7 areas, 103 terms,
  learner-authored) is the `source='vocab'` list; it is copied into the package and hash-pinned.
- **32.4 % of consecutive learner turns are byte-identical re-asks** (2,103 / 6,497). The builder
  suspected the near-repeat rule over-fired on short strings, measured it (a length guard reclaims
  6 of 2,211 pairs), and shipped the rule verbatim. The re-ask rate is a corpus fact worth its own
  learning signal.
- Quarantine reason is recoverable from row shape (`resolved IS NULL`; `question_event_id IS NULL`
  ⇒ `pre_first_user`) rather than a new column, to avoid a schema bump before Stage C re-ingest.
- 6,800 concept tags sit on quarantined pre-first-user prose blocks — legitimate (assistant prose
  is taggable) and recorded here so it is not mistaken for leakage.

**Measured rule accuracy against the orchestrator's hand labels** (60 exchanges, stratified by
harness, seed 20260910; labelled by the orchestrator, not a model, per this ADR):

| flag | agree / 60 | false + | false − | what the labels show |
|---|---|---|---|---|
| `is_question` | 42 | 17 | 1 | the interrogative rule fires on imperative briefs ("Analyse…", "Review…", "can you please commit…") and on `?` inside pasted instructions; most learner turns on this corpus are *requests* |
| `had_error` | 51 | 7 | **2** | the lexicon scans **answers only**, so a learner pasting a Traceback — the highest-value learning signal — is missed (items 34, 36, 40); false positives are prose *about* errors |
| `retried` | 48 | 12 | 0 | name-only on the archive means "a tool called ≥ 2× in one exchange", which is ordinary agentic work; the archive holds no arguments, so this cannot be made precise from history |
| `resolved` | 48 | 7 | 5 | misses are answers-to-something-else and mid-work prose; the near-repeat rule is right |
| concepts | recall ≥ 0.90 against labelled central concepts | — | — | precision not graded (vocab match is mechanical) |

Disposition: the label set is a **measurement gate**, not a build gate. Tests fail on any
regression below the measured floors and `xfail` with the number until the 90 % target is met.
The fixes the labels justify are a **`derive-v2`** with a re-label pass, not a silent patch to v1:
(1) `had_error` scans the *user* turn too; (2) `is_question` requires learner voice
(not a pasted brief/system marker) and treats polite imperatives as requests; (3) `retried` on
archive is renamed `repeated_tool_use` in the learning tier, with `retried` reserved for native
captures that carry arguments. The learning-tier export (Stage D.2) consumes `resolved`,
`had_error` and recurrence — so D.2 waits for v2, or exports with the measured accuracy stated.

## Open questions (to be settled by measurement, not debate)

Tokenizer for `prose_fts`/claims (porter vs unicode61); whether embeddings on claims clear G4;
whether lineage roll-up lifts relational recall; whether Findings make acceptable review items.

## Outcome (2026-09-10) — measured under the frozen ruler; recorded, not argued

The PoC was built (Stages B–E: store, adapter, derivation, two writer versions, a 345-session
claims population) and scored on gold v2 by the committed harness. Receipts are hash-chained in
`docs/architecture/session-memory/receipts/`; every gate reading was reviewed by a two-family council.

| gate | result | receipt |
|---|---|---|
| **G1 recall** | **NOT ESTABLISHED.** SEALED: fused arm `B1_clean_plus_claims` macro recall@5 **0.129** (bar 0.64); it is significantly *worse* than the prose control alone (−0.154, CI95 [−0.252, −0.065]), replicating DEV look 3 (−0.140). Claims alone: 0.091 SEALED / 0.130 DEV, zero on paraphrase. | `stage-g1-sealed-look.json`, `stage-f-look3-claims.json`, `stage-f-look3-mechanism.json` |
| **G2 binding** | **NOT ESTABLISHED — INSTRUMENT.** Binding invariant held (0 unbound writes over 2,057 citations, two writers). Yield 74.5–82.8 % on the primary denominator (gate 90 %); misses dominated by sessions with no learner turn. Blinded entailment could not be measured: the same auditor model scored identical items 82 → 16 → 86 "yes" across three runs; the two families disagreed by 14–21 points on both writers. writer-v2 > writer-v1 on every seat. | `g2-pilot-e1.json`, `g2-pilot-e1c.json`, `g2-population-e2.json`, `g2-pilot-e1c-audit-instrument.md` |
| G3–G6, G5 pilot | **Not reached.** | — |
| **Composite** | "The knowledge layers improve agent decisions" **may not be written.** | `stage-g1-sealed-reading.md`, `council-stage-f-g1.md` |

**What is established (a product finding, not a knowledge-layer result).** The pre-declared prose
control `B1_clean` — prose-only FTS over the archive-ingested store with a phrase-token OR planner,
declared in fusion-spec-v1 before any look and never tuned — outscored the shipped retrieval path on
SEALED by **+0.168** (CI95 lower +0.076; non-inferior on K, P, R), replicating DEV (+0.184). Look 2
attributed most of that to the shipped AND-first planner (F-B0-1: +0.142 of it). Fixing the planner in
`agent-session-tools` is the actionable outcome of this programme.

**Why the claims arm failed (retained evidence).** Equal-weight reciprocal rank fusion over a
high-recall, low-precision claims list (~127 sessions per question from the OR planner) displaces
prose rank-1/2 gold sessions: of 17 DEV questions lost by fusion, the gold was at prose rank ≤ 2 in
12 and absent from the claims list in 16. Claims *do* carry relational signal (R 0.207 vs shipped
0.103 on DEV) and none for paraphrase — they are written in the assistant's vocabulary. Any future
claims arm must be a **re-ranker or a weighted, precision-gated candidate source**, pre-registered
afresh; it is not a peer list.

**Deviations recorded.** (1) The SEALED look ran on a byte-identical read-only *copy* of the store
(sha `f5e923e8…`, unchanged since the E.2 receipt and look 3), not on a copy "rebuilt from the
manifest" as v1.1 §Evaluation binding states; no arm was tuned against the store — every write was
writer output under a pre-registered spec. (2) `score.corpus_digest` omits the ruler's "retrieval
configuration in force" input; retrieval configuration is pinned by other receipt fields
(`b0_pin`, `candidate_commit`, `fusion_spec.sha256`). (3) Result receipts' `gold_corpus_digest_at_authoring`
carries the superseded original digest; the mechanical check against amendment-002's per-split
reference passed for every receipt. All three are in `council-stage-f-g1.md`.

**Open questions — answered or closed.** Tokenizer: porter unicode61 was used throughout; not
separately tested. Embeddings on claims (G4): not reached. Lineage roll-up: not reached. Findings as
review items: writer-v2 produced 1,227 claims with 0 unbound writes; their *fidelity* could not be
measured with a single-model blinded audit — the audit method itself needs a reliability floor before
this question is answerable.

**Follow-ons (not built in this programme, no gate left to pass):** planner fix in
`agent-session-tools` (the established result); audit-method redesign (≥ 3 seats, inter-seat
agreement floor, graded rubric) before any future G2; a claims-as-re-ranker spec if the knowledge
layer is pursued again; derive-v2 rule fixes; native adapters (C.2); learning-tier export (D.2).
