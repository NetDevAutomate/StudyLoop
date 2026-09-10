# Council review — ADR-0011 "claim-centric learning memory" + Stage B store

**Reviewed:** `docs/adr/0011-claim-centric-learning-memory.md` @ `e334a7d0` and
`packages/learning-memory` @ `e334a7d0` (67 tests green).
**Seats (two model families, identical adversarial brief, run separately so neither saw the other):**

| seat | model | verdict | blocking | run id |
|---|---|---|---|---|
| A | gpt-5.6-terra | REJECT | 10 | `1a825201` |
| B | deepseek-3.2 | APPROVE-WITH-CHANGES | 7 | `654b46de` |

**Arbitration rule (same as the ruler council):** a finding is accepted only when the orchestrator
verified it against source or reproduced it with a probe against the committed store; the seats'
own probe claims were re-run independently. Council runs: 11 of the (lifted) 60.

## Orchestrator reproductions (in-memory `Store`, `:memory:`, no repo writes)

| id | probe | result |
|---|---|---|
| D1 | `search_prose("Which ADR path did the DoD and WP-9 require?")` — the DEV baseline's own failing query | `OperationalError: no such column: 9` — **reproduced** |
| D2 | `UPDATE evidence SET body='tampered'` after a claim cited it | succeeds; citation row survives — **reproduced** |
| D3 | `add_claim(..., citations=())` | claim inserted with 0 citations — **reproduced** |
| D4 | `INSERT INTO prose_fts(prose_fts) VALUES ('rebuild')` with one `tool_result` row present | tool text indexed (0 → 1 hits) — **reproduced** |
| D5 | 4 events over 2 turns, turn 2 an exact repeat of turn 1 | stored as 2 rows — **reproduced** |
| D6 | ingest child (lineage→PARENT) then PARENT | `lineage` rows = 0, never repaired — **reproduced** |
| D7 | tool-only session | `NoEvidenceError` — reproduced, **by design**; corpus impact measured below |

Corpus measurements (live `sessions.db`, read-only): of 143,603 user/assistant rows, **78,594
(54.7%) are exact within-session repeats**; 72,949 of those are tool-echo markers (`[tool:Bash]`
repeats 45,761×). Under typed events those are `tool_call` rows — position-free dedup collapses
every repeated tool call in a session to one row, so "retried = same tool call twice" can never
fire. Only **15 of 5,879 sessions (0.3%)** have zero prose events.

Fix-viability probes (SQLite 3.53.1, the pinned interpreter): FTS5 external content over a
**filtered VIEW** keeps `'rebuild'` and `'integrity-check'` prose-only (0 tool hits after rebuild);
a **phrase-token planner** (`"tok" OR "tok" …`, quotes doubled) survives every adversarial query
including D1's; **citations-first + `DEFERRABLE INITIALLY DEFERRED` FK + AFTER INSERT trigger**
refuses zero-citation claims, commits citations-first claims, and refuses orphan citations at commit.

## Dispositions

Legend: **ACCEPT-BLOCKING** (fix before Stage C ingests), **ACCEPT** (fix in the named stage),
**ACCEPT-AS-NOTE** (record; no change now), **REJECT** (with reason). A = seat A finding number,
B = seat B finding number.

### Accepted — blocking (Stage B.1, before any corpus ingest)

1. **Claims can be inserted with zero citations** (A1; B12 partially). Verified D3. Change:
   `add_claim` refuses an empty citation set; DB enforces it independently — `claim_citations.claim_id`
   FK becomes `DEFERRABLE INITIALLY DEFERRED`, citations are written first, and an AFTER INSERT
   trigger on `claims` aborts when no citation row exists. Mechanism proven above.
2. **Evidence is mutable after citation** (A2). Verified D2. Change: BEFORE UPDATE and BEFORE
   DELETE triggers on `evidence` RAISE(ABORT) unconditionally (evidence is append-only; a
   re-capture is a new row with a new id). `Store.connection` stays available for tests and the
   scorer but is documented as not part of the write contract.
3. **Natural-language queries crash `search_prose`** (A3). Verified D1 — the identical defect as
   F-B0-1 in the shipped retrofit. Change: `search_prose` routes all input through a planner that
   phrase-quotes every token and OR-joins them; raw FTS syntax only via an explicit
   `search_prose_raw`. Regression test: the 42 DEV queries that error in `baseline-dev-031dbab9.json`
   must all return without error. Stage F measures OR vs AND-then-OR-fallback on DEV.
4. **`'rebuild'` re-indexes tool output** (A4; B6 as cost note). Verified D4. Change: `prose_fts`
   external content points at a `prose_events` VIEW (`WHERE kind IN ('user','assistant_prose')`);
   triggers unchanged. Test: rebuild then assert zero hits on a tool-only token.
5. **Position-free dedup destroys the event stream** (A5; B2). Verified D5 + corpus 54.7%. Change:
   `content_hash` includes `turn_id` and `seq` (position-bearing), so every observed occurrence is a
   row; **re-import idempotence is preserved** because a re-parse of the same source yields the same
   positions. Exporter duplicates (adjacent identical rows — 37,433 assistant / 95 user in the
   corpus) are the *adapter's* job to collapse before emitting, with a count reported in
   `IngestResult`. ADR §"Implementation notes" bullet 2 is withdrawn.
6. **Deferred lineage is data loss** (A6; B5). Verified D6. Change: `lineage_pending(child_id,
   parent_id)` table written in the child's ingest transaction; the parent's ingest reconciles
   pending rows into `lineage` in its own transaction; `IngestResult.lineage_deferred` reports
   what is still pending. Circular pending pairs (B5) resolve trivially under this scheme because
   each side reconciles the other on arrival.
7. **Session-sized concatenated REPORTED evidence is not a stable citation target** (A7; B1; B7;
   B10). Verified on inspection (`_EVIDENCE_JOINER`; body changes if any event's text or order
   changes; `find()` ambiguity grows with body length). Change: **evidence is per event.** Each
   `user`/`assistant_prose` event gets one evidence row (`origin=archive`, `basis=REPORTED`,
   `event_id` FK, body = that event's text); OBSERVED native bytes remain one row per capture with
   the per-event REPORTED rows alongside as the citation surface. A claim cites a fragment, so
   re-derivation, reclassification or reordering cannot shift offsets; ambiguity is bounded by one
   message. The archive adapter's `kind` classifier is versioned (`classifier_version` on
   `sessions`) so B7's "reclassification changes the hash" is detectable, not silent.
8. **`content_hash`/citation identity through the archive classifier** (B7, B17). Accepted as part
   of 5 and 7: with position-bearing hashes and per-event evidence, a classifier change produces
   *new* event rows under a new `classifier_version` and leaves existing citations bound to the
   old fragments; `exchanges` gets `derivation_version` and is rebuilt per version rather than
   relying on `UNIQUE(session_id, turn_id)` surviving a renumbering.

### Accepted — Stage D (derivation) and Stage E (claims)

9. **"Latest non-superseded" is undefined** (A9; B4). Accepted. Stage E defines the read contract
   before the first claim is written: a claim is *active* iff no claim `supersedes` it; a claim is
   *disputed* iff an active claim `contradicts` it; `recall_claims` returns active claims and marks
   disputed ones, never silently dropping either; supersession is same-session-or-lineage only
   (cross-session replacement is a `corrects` relation, not a supersede). Recorded in the ADR now.
10. **Derivation rules are heuristics without a testable spec** (A12, A13, A14; B3, B9, B19).
    Accepted. Stage D ships `derive.py` with a versioned spec (`derivation_version`), a labelled
    cross-harness fixture set (≥ 20 exchanges per harness, hand-labelled by the orchestrator, not a
    model), and per-rule tests; exchange threading uses `turn_id` + tool-call correlation +
    lineage, and quarantines events it cannot thread instead of guessing. Concepts get a canonical
    id + alias table; `recurrence.session_ids JSON` is replaced by `concept_occurrences(concept_id,
    session_id, derivation_version, observed_at)`.
11. **Ambiguous short quotes are refused** (B16). Accepted, softened by 7: with per-event evidence
    the ambiguity window is one message, so "Yes" repeated across a session no longer collides. The
    `context_before/after` disambiguator is **rejected** — it would let a writer bind a quote by
    adding text the evidence does not contain adjacent to it.
12. **Claim identity excludes citations and predecessor** (A15). Accepted for Stage E: `claim_id`
    covers the canonical citation-set fingerprint and `supersedes`, so two claims with identical
    text but different proof are distinct rows.

### Accepted — evaluation and operations (Stage F / H)

13. **No reproducible run identity; derivation tunable against DEV** (A10; B12). Accepted — this is
    the ruler's anti-gaming clause made concrete. Stage F: every arm receipt carries a **run
    manifest** (adapter versions, `classifier_version`, `derivation_version`, writer model id +
    prompt sha256 + parameters, corpus digest, store schema version) and the SEALED look is
    executed on a **fresh work copy built from the manifest**, never on the DEV-tuned store. B12's
    "embed gold answers in claim text" vector is closed by the existing gold-blind writer rule
    (hash-ordered population, SEALED never selectable) plus G2's blinded entailment audit; a claim
    whose statement is not entailed by its citations fails G2 regardless of recall.
14. **Operational durability unspecified** (A17; B8, B15, B24). Accepted for Stage H: WAL only when
    the store path is on a local filesystem (fail closed to `DELETE` journaling otherwise); store
    size, FTS rebuild time, and capture-age reported on the final receipt; `doctor` "age of last
    capture" check recorded in ADR consequences already — implementation is Stage G/H.
15. **Native bytes are hashed, not retained** (A16). Accepted for Stage C: OBSERVED evidence stores
    the raw bytes (BLOB) plus the decoded citation text; both hashed. Storage cost is measured at
    ingest and reported.
16. **Adapter Protocol too weak** (A11; B11). Accepted for Stage C: `SourceRef` gains
    `source_sha256`; `ParsedSession` gains `adapter_version`, `classifier_version`,
    `exporter_dupes_collapsed`; the shared contract suite asserts monotone `(turn_id, seq)`, a
    closed actor vocabulary, ISO-8601 UTC `ts`, and `Session.id` derived from the source.

### Accepted as notes (recorded, no change now)

17. **Prose-less sessions are rejected** (B14). 15/5,879 sessions (0.3%). Keep the invariant —
    a session with nothing citable has nothing to retrieve — and report the rejected ids in the
    Stage C ingest receipt.
18. **Tool output excluded from evidence** (A8). Partially accepted: with per-event evidence (7),
    `tool_result`/`error` events *may* carry evidence rows too (citable, never indexed for recall).
    Deferred to Stage E as a measured question — whether Findings need tool-output citations — not
    adopted now, because 53% of the archive is tool echo and redaction policy for command output
    does not exist yet.
19. **`tags` 2..5 minimum and `confidence` 0.5..1.0 floor** (B21, B22). Rejected as blocking, kept
    as notes: the floors exist so a writer cannot emit a hedge as a claim; G2's audit will show
    whether writers pad tags with filler, and the floor is revisited on that evidence.
20. **Review-item generation unspecified** (B18); **writer identity unverified** (B23);
    **tokenizer migration** (B20); **concept-tag source ambiguity** (B9). Notes; Stage D/E scope.

### Rejected

- **B13** (hash case sensitivity) — the seat verified it is not an issue.
- **B25** ("new schema may change gold answers even with same session ids") — the gold binds to
  session ids, and the ruler scores whatever the arm returns; a different answer *is* the
  measurement, not a compatibility risk.
- **B5's "allow NULL parent_id lineage rows"** — replaced by the pending table (6), which keeps
  `lineage` FK-clean.
- **A8's "keep all typed events as evidence now"** — see 18.

## Outcome

The claim-centric bet stands; the **store as built is not fit to ingest the corpus** until items
1–8 land. ADR revised to v1.1 with the changes above; Stage B.1 (store hardening) is inserted
before Stage C, with the seven reproductions above as its acceptance tests (each must flip from
reproduced to refused/correct). No gate threshold or statistic in the ruler changed.
