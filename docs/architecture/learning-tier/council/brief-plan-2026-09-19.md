# Council brief — Learning tier: feed it, then measure one judge (planning round)

**Date:** 2026-09-19 · **Coordinator:** Kiro (agent) · **Owner:** Andy · **Repo:** StudyLoop, `main` at `4f8e3e0f`
**Ask of this council:** validate an EXECUTION PLAN for a new branch that (1) makes the mentor agent actually
*write* learning signals on every supported harness, proven by programmatic simulation of a learner, and
(2) measures one external judgement model (TypeSafe Jev) on struggle classification against the repo's
frozen human-labelled gold, without wiring it into the product. Be adversarial about sequencing, false finish
lines, privacy and data loss. Every BLOCKING/MAJOR finding must carry a concrete check (command, `file:line`,
number to recompute). Say UNVERIFIED rather than assume. Follow §8 exactly.

## 1. What StudyLoop is (enough to reason about the code)

Local-first study tool for one learner (AuDHD-aware Socratic mentoring, spaced repetition, study plans). A
*mentor agent* runs inside the learner's own coding harness — the six supported harnesses are exactly
`kiro`, `claude`, `codex`, `opencode`, `pi`, `grok` (`packages/studyloop/src/studyloop/harnesses.py:28-49`;
`opencode`/`grok` are `PREVIEW_HARNESSES`). Agent definitions live under `agents/<harness>/` with shared
material under `agents/shared/`; `scripts/install-agents.sh` projects them and `scripts/update-agent-manifest.py`
regenerates `agents/manifest.json` (content hashes, also tracked in `.secrets.baseline` — regenerate with a
**whole-repo** `detect-secrets scan --baseline`, never a single path).

**Standing rule (owner, non-negotiable):** agent features reach an LLM only through the user's harness
subscription, never through an API key StudyLoop requires. Optional API-key providers exist as a *provider
axis* (`content/generators/provider_profiles.py`, ruled "keep — a provider axis, not an adapter" 2026-09-10):
off without a key, every existing output byte-identical when unset.

The mentor talks to the product through the `studyloop` MCP server (`packages/studyloop/src/studyloop/mcp/tools.py`)
and the `studyloop` CLI. Learning state lives in one SQLite file, `~/.config/studyloop/sessions.db` (924 MB live,
schema 48), rebuilt as a filtered clean start on 2026-09-12; the pre-rebuild file is archived cold at
`~/.config/studyloop/archive/sessions-archived-20260912.db` (1.30 GB) with a 2026-12-12 review date.

## 2. Why these two items, and what was already found

An evaluation of Jev (a "System One" judgement model: text `state` + typed questions → typed answers with
probabilities and a confidence; no text generation) ran a Stage 0 access spike on 2026-09-19
(`docs/architecture/jev-judge/receipts/stage0-access-2026-09-19.md`, branch `feat/jev-judge`, `88018c90`):

- Pedagogical teach-back dimensions (own words, structure, depth) scored where a human would, confidence ≥ 0.87.
- **Accuracy was blind to a planted Python-semantics error** (82 % of mass on the "accurate" levels); its
  confidence was lowest (0.52), so a gate would have routed it to "ask the learner".
- Identical calls drifted ≤ 0.06 on a 0–3 scale: *consistent, not deterministic*. Tests assert levels/bands;
  CI replays fixtures, never calls live.
- Vendor's own jaggedness page: cannot count, compare dates or do arithmetic → the decision engine and
  completion review (`learning/decision.py`, `planning/views.py`) are **out of scope by design**.

The coordinator's assessment to the owner: a better judge bolted onto a pipe nobody opens produces zero.
The learning tier is **unfed**: zero calls to any studyloop writer tool in 143,973 historical messages
(established 2026-09-12). Hence the order: **feed first (item 1), measure a judge second (item 2)**.

## 3. Established facts — verified 2026-09-19 against the tree and the live DB (read-only)

### 3.1 Writers that exist

| Writer | Where | Writes |
|---|---|---|
| `log_topic(topic, status, note)` | `mcp/tools.py:583` | `session-topics.md` + `study_progress` via `history.record_progress` (`:597-618`) |
| `log_struggle(question, topic_tag, context)` | `mcp/tools.py:850` | `parking.park_topic(..., source="struggled")` (`:862-864`) |
| `record_topic_progress(topic_id, priority, confidence)` | `mcp/tools.py:538` | backlog priority / resolved |
| `record_study_progress(course, card_hash, correct)` | `mcp/tools.py:114` | card review result |
| `log_review_outcome(...)` | `mcp/tools.py:648` | review outcome |
| `record_plan_learning(...)` | `mcp/tools.py:131` | plan learning record (plan-close programme, landed) |
| **Teach-back** — `record_teachback(concept, topic, scores(5×1–4), review_type, angle, notes, session_id)` | `history/teachback.py:27` | `teach_back_scores` (CHECK `BETWEEN 1 AND 4`, migration 10 in `agent-session-tools/.../migrations.py:500-515`) |

**F1. There is no MCP teach-back writer.** `mcp/tools.py` exposes only `get_teachback_history` (`:432,460`).
Teach-back is CLI-only: `studyloop teachback "<concept>" -t <topic> --score "3,3,4,3,2" --type structured --angle ...`
(`cli/_teachback.py:52`, five-int validator `:16-46`). `agents/shared/teach-back-protocol.md` ("Recording
Teach-Back Scores") instructs the agent to run that shell command after proposing the score to the learner
and adjusting on disagreement (metacognitive calibration step, `teach-back-protocol.md:127-140`).

### 3.2 What each harness's mentor may call today

| Harness | Definition | studyloop grants (verified by grep of the file) |
|---|---|---|
| kiro | `agents/kiro/study-mentor.json` | `tools: ["@studyloop"]` (**all** tools available) but `allowedTools` pre-approves only `get_concept_context, get_study_history, get_next_action, get_topic_suggestions, get_active_topics, log_topic` — every other writer prompts the learner for approval per call |
| claude | `agents/claude/socratic-mentor.md` + `agents/claude/settings.json` + `mcp.json` | **zero** `mcp__studyloop__*` entries in `settings.json`; zero tool references in `socratic-mentor.md` |
| opencode | `agents/opencode/study-mentor.md` | frontmatter `permission: "studyloop *": allow` — everything |
| codex | `agents/codex/AGENTS.md` | no `studyloop…(log_|record_|get_)` reference matched; grant mechanism UNVERIFIED by the coordinator |
| pi | `agents/pi/AGENTS.md` + `extensions/studyloop-session-export.ts` | same as codex: UNVERIFIED |
| grok | **no `agents/grok/` directory exists**; adapter `packages/studyloop/src/studyloop/adapters/grok.py` | where the grok mentor's prompt/grants come from: UNVERIFIED |

**F2. The persona's only concrete "record progress" instruction points at a different tool.**
`agents/kiro/study-mentor/persona.md:23` "6. End of Session — Record progress, surface parking lot, suggest next
review"; `:32` "Record progress: `uv run tutor-checkpoint <skill-name> --notes ...`" — that is
`agent_session_tools.tutor_checkpoint:main` (`packages/agent-session-tools/pyproject.toml:51`), not a studyloop
writer. No persona line names `log_struggle`, `record_topic_progress`, `record_study_progress`,
`log_review_outcome` or a teach-back write, and none states a *trigger* ("when X, call Y").

Existing parity/contract tests that could host step-1 assertions: `tests/test_adapter_parity.py`,
`tests/test_docs_harness_tier_contract.py`, `tests/test_web_agent_matrix.py`, `tests/test_agent_launcher.py`.

### 3.3 Programmatic simulation of a learner — what already exists

- **Acceptance tier** (`docs/acceptance-testing.md`, `tests/acceptance/`): opt-in `STUDYLOOP_ACC=1`, never CI;
  drives a **real harness binary** through the real product with a scratch HOME (`isolation.py`), a
  `turn_script.py`, `evidence.py`, and pluggable **learner actors** (`actors/`): `scripted` (default,
  deterministic pre-written answers), `gateway` (LiteLLM alias plays the learner), `direct` (provider_profiles),
  `harness` (a second harness plays the learner). Unknown harness/actor name fails loudly; missing binary or
  credential skips *by name*. `test_harness_matrix_live.py` runs the six-harness matrix.
- **UAT tier** (`STUDYLOOP_UAT=1`) grades pedagogy against a written rubric.
- **e2e browser suite** fakes the agent (`fake_agent` dual-mode SAYS→VERDICT).
- **`scripts/plan_agent_harness.py`**: maintainer harness driving the real plan agent with a scripted learner;
  asserts model-independent invariants; writes a fixture so CI replays one real conversation's outcome
  sub-second with no subscription. **This judgement-vs-plumbing split is the house precedent.**
- Recorded lesson: a scripted learner that "knows the answers" flatters the score; the vague persona is the
  truer test. A scripted learner also cannot test whether the agent *notices* something — that needs the owner once.

### 3.4 The struggle ruler (item 2)

- Gold: `packages/studyloop/tests/fixtures/eval_golden.json` — **13 sessions: 8 positive, 5 negative**;
  labels are free-form `(topic, concept)` slugs, **23 distinct**, e.g. `('aws','lakeformation-service-linked-role')`,
  `('python','nominal-vs-structural-subtyping')`, `('graphrag','mbox-email-ingestion')`.
- Split: `eval_split.json` — train 8 / held_out 5, frozen ("the hill-climber optimises ONLY on train").
- Runner: `extractors/eval_runner.py` — reads transcripts from the **live** `sessions.db` read-only; metrics
  fixed as the boundary the optimiser may not mutate: topic Jaccard on normalised keys, confidence precision,
  confidence recall, **false-positive rate on negatives MUST be 0**; appends to `results.tsv`
  (exists in the main checkout, 6,968 bytes, not tracked); makes **live Bedrock calls** via
  `extractors/llm.py:extract_struggles`; `extractors/pipeline.py:35 pre_filter(session_id, source, messages)`
  requires `source in STUDY_SOURCES`.
- The Bedrock extractor is parked four-way broken (never invoked; needs AWS creds — violates the harness rule;
  recall stuck at 1/9 across 83 ledger rows; pre-filter keyed on a role this corpus does not use).

**F3. The ruler is partly in cold storage.** Live DB holds **10 of 13** gold sessions. The three missing —
`agent-aa1015b3cd2de6078`, `agent-adb2db81040728397`, `agent-a86e019` (claude_code) — are **all negatives**,
two from *train*, one from *held_out*; they exist in the cold archive with 196 / 187 / 150 messages.
**Live negatives: 2 of 5.** The FP = 0 gate has two-fifths of its teeth unless the eval reads live ∪ archive.

**F4. `history/search.py:118 struggle_topics(days, min_sessions)` is not a control arm.** It is a
cross-session frequency heuristic (user messages containing `?` in the last N days, keyword `Counter`, topics in
3+ sessions). It does not label a *session*, so it cannot be scored against per-session gold. The coordinator
previously called it the "deterministic baseline"; that was wrong.

**F5. Jev cannot name a concept.** Its primitives are Choice (bounded options), Score (rubric levels), Noul
(is this true, 0–1). Gold labels are open-vocabulary slugs. Any Jev arm needs either a bounded candidate list
(coverage of the 23 labels by any list the learner's data could supply is UNMEASURED) or a separate namer.
Limits: 64k tokens per request, 32k for `state` + longest question; accuracy falls with irrelevant state
("context rot"); `jev-1.13.0` pinned, `$0.042 / Mtok`; not trained on customer data, ZDR enterprise-only.
Sending transcripts to the vendor is acceptable for the owner's personal repo **only after scrubbing** — a live
bearer token was found in one session's text during the 2026-09-09 privacy gate; `agent-session-tools` has a
scrubber (`tests/test_scrubber.py`).

## 4. Item 1 — feed the tier: design space and the coordinator's proposal

**Goal.** A mentor session on any supported harness records the learning signals the protocol already
describes, without the learner approving each call, and the plumbing is proven by simulation.

**Proposal (for critique, not approval):**

1. **Add an MCP writer `record_teachback`** mirroring the CLI validator exactly (five ints 1–4, `review_type`
   enum, optional `angle`, `notes`, `session_id`), delegating to `history.teachback.record_teachback`. Keep the CLI.
   Rationale: CLI-only recording assumes the mentor has a shell and the learner tolerates a shell prompt mid-lesson.
2. **Grant parity for the writer set** `W = {log_topic, log_struggle, record_topic_progress, record_study_progress,
   log_review_outcome, record_teachback}` (plus `record_plan_learning`, already needed by plan close) in every
   harness definition, in that harness's own grammar: kiro `allowedTools`, claude `settings.json` permissions,
   opencode already `studyloop *`, codex/pi/grok per their mechanism (UNVERIFIED — a seat should say how).
3. **One shared "recording protocol"** (new `agents/shared/recording-protocol.md` or a section of
   `teach-back-protocol.md`) with explicit triggers, projected to all six: after a teach-back and the learner's
   agreement → `record_teachback`; 2+ rounds without breakthrough → `log_struggle`; end of session → `log_topic`
   per concept touched with status; card/quiz answered → `record_study_progress`. Retire or reconcile the
   `tutor-checkpoint` line (`persona.md:32`).
4. **Proof, three layers:**
   - CI (deterministic): a parity test asserting each of the six definitions grants `W` (the natural home is
     `test_adapter_parity.py`); a contract test on `record_teachback` (validation identical to the CLI, row lands,
     CHECK constraint honoured); a projection test that shared-protocol content is present in every projected copy
     and `agents/manifest.json` hashes match.
   - CI (replay): one recorded real mentor session's tool-call sequence replayed against the MCP layer with a
     scratch DB → `teach_back_scores`, `parking`, `study_progress` gain the expected rows. Same shape as the
     plan-agent fixture.
   - Acceptance (opt-in, maintainer-run): a `turn_script` "teach-back episode" with the **scripted** actor: mentor
     asks → learner explains (pre-written, deliberately vague/imperfect) → mentor proposes a score → learner
     agrees → assert the scratch `sessions.db` gained a `teach_back_scores` row and a `session-topics.md` line.
     Run on `kiro` (owner has it); other harnesses skip by name until their binaries are present.

**Definition of done (proposed):** parity + contract + projection + replay tests green in CI; the acceptance
episode passes on kiro locally with evidence bundle; docs (`docs/contributing.md`, mentor docs) updated;
`agents/manifest.json` and `.secrets.baseline` regenerated; full gates (ruff, format, pyright, bandit, pytest).

## 5. Item 2 — measure Jev on struggle classification: design space and proposal

**Goal.** One pre-registered measurement on the frozen ruler that answers "does a calibrated judgement model
beat what exists, without false positives" — *eval-only*, no product wiring, maintainer-run.

**Proposal (for critique):**

1. **Restore the ruler.** `eval_runner` (or a new `extractors/gold_source.py`) reads gold transcripts from
   live ∪ archive **read-only**, records a fingerprint per session (the `test_eval_receipt.py` fingerprint idea),
   and refuses to run unless 13/13 are present. Do **not** commit transcripts as fixtures (owner's personal
   history; repo is public).
2. **Pre-register** (`docs/architecture/learning-tier/receipts/preregistration-item2.md`) before any number:
   arms, metric (the runner's fixed four), decision rule, and the honesty caveat that n = 13 (5 held-out) gives
   direction, not significance — report paired cluster-bootstrap CIs from `eval.metrics` and do not claim more.
3. **Arms.** Control arms that are *valid* (F4 rules out `struggle_topics`):
   - **C0 predict-nothing** (FP = 0 by construction, recall 0) — the floor every arm must beat on recall.
   - **C1 the Bedrock extractor's recorded ledger** (`results.tsv`, recall 1/9) — historical, not re-run
     (needs AWS creds; harness rule).
   - **C2 deterministic per-session keyword arm**: learner turns FTS-matched against a bounded concept list —
     cheap, honest, and it isolates whether any lift is *judgement* or *vocabulary*.
   Candidate Jev arms — the council should pick **one** or reject all as unmeasurable on this ruler:
   - **J-a Choice over a bounded list** built from the learner's own data at the time (plan concepts, backlog,
     `study_progress`) + `none_of_these`. Precondition: measure gold-label coverage by that list on **train**
     first; if coverage < 50 % the arm cannot be scored on Jaccard and should not run.
   - **J-b two-stage**: the harness LLM (allowed by the rule) proposes ≤ 8 candidate concept slugs per session;
     Jev asks one Noul per candidate "the learner expresses difficulty with <slug>" with a confidence gate.
     Jev supplies calibration and the FP control; the generative model supplies vocabulary.
   - **J-c turn-level Noul only** ("this learner turn expresses confusion or being stuck") — measures Jev's actual
     strength but cannot produce `(topic, concept)` pairs, so it needs a namer to be scored; otherwise report it
     as a *component* result, not a ruler result.
4. **Privacy and shape.** Scrub every `state` with the repo scrubber before it leaves the machine; send learner
   turns only (drop assistant/tool echoes — `pre_filter` already keys on tool-noise), chunk under 32k tokens;
   pin `jev-1.13.0`; log `usage` to a spend ledger.
5. **Decision rule (draft, for the council to tighten):** adopt-for-product-wiring iff, on **held_out**,
   FP-on-negatives = 0 **and** confidence-recall > C1 **and** Jaccard ≥ C2; otherwise record the receipt and stop.
   Held-out is run **once**.

**Definition of done (proposed):** receipt with all arms' numbers on train, one held-out run, CIs, spend, and a
one-line verdict against the pre-registered rule — reviewed by a council seat before the owner reads it.

## 6. Proposed staging (serial, one worktree, each stage ends countable)

| Stage | Content | Finish line |
|---|---|---|
| S0 | Branch `feat/learning-tier-fed`, worktree `~/code/personal/tools/studyloop-wt/tier` off `main`; programme dir `docs/architecture/learning-tier/` (allow-listed like `plan-integration`) | branch exists, brief + arbitration committed |
| S1-RED | Parity test for `W` across six defs; `record_teachback` contract tests; projection test | N tests fail on `main` for the stated reason, 0 unrelated reds vs a clean control worktree |
| S1-GREEN | MCP writer; grants per harness; recording protocol + projection; manifest + baseline | RED→green; goldens unchanged; full gates |
| S1-SIM | Scripted-learner teach-back episode on kiro (acceptance, opt-in) → evidence bundle → fixture → CI replay test | one row in scratch `teach_back_scores`; replay test green in CI |
| S2-RULER | live ∪ archive gold source, fingerprints, 13/13 guard | eval refuses on 12/13, passes on 13/13 |
| S2-PREREG | pre-registration receipt committed **before** any Jev call on gold | receipt sha in the next commit message |
| S2-TRAIN | C0/C1/C2 + chosen J arm on train; coverage check for J-a first | receipt with numbers + spend |
| S2-HELDOUT | single held-out run; verdict against the rule | receipt; council review of the result |

Each stage: commit in coherent steps with why-bodies; full suite diffed against a clean control worktree
(the house pattern); push only after the owner says so; PR per item (two PRs) unless the council argues otherwise.

## 7. Numbered questions for the council

- **Q1.** MCP `record_teachback` writer: right call, or keep teach-back CLI-only and teach every harness to shell out?
- **Q2.** Grant parity: for codex, pi and grok, *how* are tool grants expressed (name the file and grammar, or say
  UNVERIFIED)? Is "prompt-per-call" on kiro (tool in `tools`, absent from `allowedTools`) a defect to fix or an
  intended consent step for writes?
- **Q3.** Triggers in prose vs. a machine-readable trigger table projected into each persona: which, and how does
  a CI test prove the projected copies carry it?
- **Q4.** Is the S1-SIM scripted episode a sufficient finish for "the tier is fed", or must a real (non-scripted)
  learner turn from the owner be part of the definition of done? Which harnesses must pass before merge?
- **Q5.** Ruler: live ∪ archive read-only vs. re-importing the three negatives into the live DB (the owner has
  ruled: no live-DB deletions; imports were not ruled on). Which, and what is the guard?
- **Q6.** Which Jev arm (J-a / J-b / J-c) is measurable on this ruler, and does J-b violate the spirit of
  "measure Jev" by letting the harness LLM do the naming?
- **Q7.** Is the draft decision rule (§5.5) the right shape for n = 13, or should the measurement be declared
  directional-only with no adopt/reject clause?
- **Q8.** Sequencing: is anything in item 2 a prerequisite for item 1, or vice versa, that the staging misses? Is
  one branch for both items wrong?

## 8. Required answer format — follow exactly, ≤ 2,500 words

1. `VERDICT: ACCEPT | ACCEPT-WITH-CORRECTIONS | REJECT` — for the plan as a whole, one line of reason.
2. `FINDINGS` — a table: `id | severity (BLOCKING/MAJOR/MINOR) | claim | concrete check (command or file:line or
   number to recompute)`. A finding without a check is discarded.
3. `ANSWERS` — Q1…Q8, each ≤ 120 words, each ending with a recommendation the coordinator can act on.
4. `REVISED STAGING` — only if you change §6; otherwise write `unchanged`.
5. `UNVERIFIED` — what you could not verify from this brief and would check first.
6. `ONE THING` — the single change that most improves the plan's chance of landing a true result.
