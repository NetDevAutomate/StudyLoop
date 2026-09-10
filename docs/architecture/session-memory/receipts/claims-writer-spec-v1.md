# Claims writer spec v1 — pre-registered before the first writer run (Stage E.0)

**Declared:** 2026-09-10, before any model has written a claim into `learning-memory.db`.
Ruler binding: G2 ("wind-down produces citation-bound concepts whose quotes entail the
proposition, audited"), the ≤ 400 writer-run cap, writer model `claude-sonnet-5`, $0 external
spend (kiro roster only). ADR-0011 v1.1 Decision 3 ("each with at least one quote-bound citation —
enforced by the database"), Decision 4 (read contract), council dispositions 9, 12, 13, 18.

## What a writer run is

One sub-agent run over **one session**: it receives the session's citable evidence rows
(`visible_evidence(session_id)` — per-event `REPORTED` prose with `evidence_id`, ordered by
turn/seq) plus the derived exchange flags for that session (`derive-v1`: `is_question`,
`had_error`, `resolved`, concept tags), and returns **0–8 claims** as JSON. It never receives:
retrieval code, the ruler, any gold file, any other session, the store path, or the ability to
write. The orchestrator's harness validates and inserts; the model proposes only.

## Model and parameters (frozen for E.1 and E.2)

- Model: `claude-sonnet-5` (ruler). `spawn_run model=claude-sonnet-5`, one session per run.
- Prompt: `scripts/knowledge_proof/writer_prompt_v1.md`; its sha256 is recorded on every receipt
  and on every claim row's `writer` field as `sonnet5/writer-v1/<sha8>`.
- No tools for the writer beyond reading the packet it is given. No web. No spawning.
- Output schema (strict JSON, rejected on any deviation):
  `{"claims":[{"kind":"Problem|Finding|Decision|Procedure|Preference","title":"≤120","statement":"≤500","tags":["2..5"],"confidence":0.5..1.0,"citations":[{"evidence_id":"…","quote":"exact substring"}]}]}`

## Population rule (gold-blind by construction)

- Population = the 342 ingested PoC sessions (`poc-set-g2.json`), ordered by
  `sha256(session_id)` ascending. **E.1 pilot** = the first 40 in that order. **E.2** = the
  remainder, in that order, until the writer-run cap or the population is exhausted.
- The writer environment has **no read access to any gold file** — asserted by a test that greps
  the writer packet builder and the prompt for `gold`, `sealed`, `receipts/`, and by the packet
  being built from the store alone.
- 26 DEV gold sessions lie inside the population (amendment-003). No builder run computes the
  SEALED overlap.

## Insertion contract (what the harness enforces, per claim)

1. Schema validity (above); `tags` 2–5 distinct lower-case tokens; `confidence` ∈ [0.5, 1.0].
2. **≥ 1 citation**, each `quote` a non-empty, unambiguous (overlap-aware) substring of the named
   evidence row's body — resolved by `Store.add_claim`; refused otherwise. A refused citation
   refuses the whole claim (no partial insert).
3. `evidence_id` must belong to the session in the packet (cross-session citation refused).
4. Duplicate claim (same content id) → counted, not re-inserted.
5. Every refusal is recorded with reason in the run receipt; **unbound writes = 0 by
   construction**, and the receipt proves it by re-checking every inserted citation with SQLite's
   own `substr()` after the run.

## Budgets

- Writer runs: E.1 ≤ 40, E.2 ≤ 302 (population remainder), retries ≤ 1 per session on a
  transport/JSON failure only (never on "no claims"). Hard cap 400 (ruler).
- Per run: packet ≤ 48 KiB of evidence text (largest sessions are truncated to the first N
  evidence rows that fit; truncation recorded); response ≤ 8 claims.
- Wall: the pilot must finish inside one monitor cycle budget (≤ 40 runs × ~2 min).

## G2 audit design (pre-registered)

- **Yield:** share of population sessions (primary denominator `n_prose_ge10 = 200`; literal
  `n_messages_ge10 = 345` also reported) with ≥ 1 inserted claim. Gate: ≥ 90 %.
- **Unbound writes:** 0, proven by post-run `substr()` re-check of every citation.
- **Blinded entailment audit:** a random 100 inserted claims (seed 20260910, drawn after E.2 or
  after E.1 if E.2 is not reached), each shown to a **second model family** (deepseek-3.2; gpt-5.6
  as tie-break) as `(statement, quote)` **only** — no title, tags, session, or writer identity —
  with the question "does the quote entail the statement? yes / partial / no", and a required
  one-line reason. Gate: ≥ 95 % `yes`. Every `partial`/`no` is classified into the taxonomy below.
- **Failure taxonomy (fixed now):** `over-claim` (statement exceeds quote), `wrong-subject`
  (quote about something else), `hallucinated-detail` (statement adds facts), `procedure-not-
  shown` (claims a step the quote does not contain), `preference-inferred` (a preference stated as
  fact), `quote-too-thin` (quote true but trivially short), `other`.
- **Mutation tests** (ruler): altered body, stale offsets, wrong evidence id, misaligned code-point
  span — already proven at the store level in Stage B/B.1 (`test_claim_citations.py`,
  `test_claims_immutable.py`); re-run and cited on the G2 receipt.

## What is deliberately NOT in v1

No supersession (`supersedes` stays NULL: the writer sees one session, so there is nothing to
supersede); no `claim_relations`; no review-item generation; no tool-output citations (archive
holds none); no lineage roll-up. Each is a later spec version.

## Reading the result

- If yield ≥ 90 % and entailment ≥ 95 %: G2 passes on the pilot+population and the claims arm may
  be declared in `fusion-spec-v2.md` for DEV look 3.
- If yield < 90 %: report the distribution of "no claims" sessions by harness and prose count;
  investigate the *prompt*, never relax the trigger or the denominator.
- If entailment < 95 %: report the taxonomy; the writer is not fit; the claims arm is **not**
  declared and Stage E stops with the receipt.
