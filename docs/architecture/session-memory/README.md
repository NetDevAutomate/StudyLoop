# Session-memory & knowledge architecture — decision record

**Decided:** 2026-09-06 (PoC measurement) · **Corrected against source:** 2026-09-09 ·
**Status:** the storage decision stands; the retrieval and ontology claims are
restated below at the strength the receipts support.
**Feeds:** Phase 2 — [PR #18](https://github.com/NetDevAutomate/StudyLoop/pull/18)
`feat/sessionweaver-phase2-retrofit` (open, not on `main`).
**Companion repo:** `~/code/personal/tools/session_weaver` (PoC code, benchmark
harness, gold set, raw results).

Every claim here carries one of three labels. **SHIPPED** is on `main`.
**IN-FLIGHT** is in PR #18. **PoC** was measured once in the companion repo and has
no production surface. The 2026-09-06 version of this document did not make that
distinction, and several of its headline numbers turned out to be conflations of
separate measurements; the corrections are listed at the end so the record shows
what changed and why.

## The decision, in one paragraph

StudyLoop's session memory stays on **one SQLite file** as system of record —
`~/.config/studyloop/sessions.db`, schema v47 — holding the conversation archive,
the StudyLoop learning tier and the evidence tier as table families, not separate
databases (**SHIPPED**). No measurement justified a storage migration. On top of it
Phase 2 adds a **concept sidecar** written at wind-down as JSON into SQLite with
byte-exact quote binding enforced by a trigger (**IN-FLIGHT**), and a
**deterministic tier-1 ontology** rebuilt from the archive at $0 for diagnostics
and typed queries — deliberately *not* a recall input (**IN-FLIGHT**). The PoC's
Open Knowledge Format (OKF) Markdown store is a **frozen legacy corpus** imported
one-way for historical recall signal; nothing in the codebase writes OKF.

## Interactive diagram (archify)

- `verified-architecture.architecture.json` (**tracked**) — the architecture as
  verified on 2026-09-09: one file, three tiers, the shipped read path, and the
  in-flight boundary. Regenerate the HTML from it with the archify skill:
  `node bin/archify.mjs deliver architecture verified-architecture.architecture.json verified-architecture.html --quality showcase`.
  The 718 KB HTML is gitignored (the repo's large-file hook caps at 500 KB).
  Delivery receipt: showcase pass, 9/9 artifact checks, 0 composition errors,
  spec SHA-256 `d69def5d…` (5,904 B), artifact SHA-256 `344db3be…` (718,127 B).
  Browser `visual-check` could not run in the authoring sandbox (Chrome sandbox
  init refused); no perceptual review is claimed for this artifact.
- `final-architecture.*` and `knowledge-pipeline.*` are the 2026-09-06 PoC
  diagrams (local, untracked). They depict the *intended* Phase 2 design and
  carry the superseded numbers below; keep them as history, do not cite them as
  current.

## What is where — and what reads it

| Layer | Tables / files | Written by | Read by | Label |
|---|---|---|---|---|
| Conversation archive | `sessions`, `messages`, `messages_fts` (FTS5) | six per-harness exporters via `session-export`; launchd sweep every 4 h | `session_search`, `session_context`, struggle extraction | SHIPPED |
| Learning tier | `study_progress`, `study_sessions`, `card_reviews`, `parked_topics` (= the backlog), `teach_back_scores`, `study_plans` (cache of the plan Markdown, ADR-0010) | CLI wind-down, `log_topic`/`log_struggle`, web routes | `now` decision engine, review, mastery, backlog board, plan interview | SHIPPED |
| Evidence tier | 60 `context_*` tables; `context_evidence` sha256-bound, re-verified on every read | `capture_batch` on every export; `memory_propose`/`relate`/`review` | `memory_search`, `memory_assess`, `memory_decide`, `get_concept_context` | SHIPPED |
| Concept sidecar (v49) | `context_concepts`, `context_concept_fts`, `context_concept_events` | `memory_winddown` (JSON → SQLite); `concept import-okf` (legacy intake) | `memory_recall` | IN-FLIGHT |
| Tier-1 ontology (v48) | six `ontology_*` tables, rebuilt into `__ontology_*_next` staging and swapped atomically | post-export rebuild hook; `session-weaver ontology rebuild`; **never synced** | `ontology status` (CLI diagnostics only) | IN-FLIGHT |

Two derived caches sit beside the file and are safe to delete: `explorer_fts.db`
(lesson search) and `<content.base_path>/content_index.db` (course discovery).

**Search on `main` is FTS5 keyword only.** `hybrid_search` (RRF) exists with a
single reference — its own definition — and both embedding tables hold 0 rows.
Multi-word queries are wrapped as a *phrase*, so they get stricter, not looser.

## Why each claim is believed — restated at receipt strength

| Claim | Evidence | Label |
|---|---|---|
| SQLite suffices at this scale | Full-corpus FTS rebuild 0.7–1.0 s; queries ~15 ms; cutover+merge with zero retrieval regression (`RESULTS-final.md`) | PoC → SHIPPED |
| Cleaning beats engine choice | 86,108 noise rows removed → 100 % searchable coverage, FTS lag 0 (`RESULTS-final.md`) | PoC → SHIPPED |
| Extraction *fidelity* is the variable, not architecture | Same corpus, same 25 questions: 0.24 recall@5 under cheap truncated extraction vs 0.64 under full-text frontier extraction (`RESULTS-final.md:174-176`) | PoC |
| Concept fusion out-scores raw text — **point estimate only** | PoC: T2H 0.68 vs 0.48 via RRF over three arms incl. a vector arm (`bench-t2.py:138`). Current gate A6 on `fb606468`: **0.60 recall@5, Wilson 95 % CI [0.41, 0.77]** vs raw-text control 0.48; target 0.64 not met; verdict **INVESTIGATE**. The control lies *inside* the CI, so at n = 25 the lift is **not statistically established**. The A6 table exists only as Markdown in `~/.agents/skills/session-weaver/SKILL.md:140-158`; no machine receipt for it was found. | IN-FLIGHT |
| Paraphrase recall | 0.25 at PoC; **0 / 40** on the corpus-verified directional set | PoC / IN-FLIGHT |
| Quote binding is real, and the legacy corpus fails it | Trigger `context_concepts_bound_proof` re-checks `substr(body, start, end) == quote`. Import receipt `legacy-okf-import-report.json`: **2,035 scanned · 2,033 parsed · 0 bound · 2,033 legacy_unbound** (no_exact_match 1,559 · body_description_mismatch 764 · no_visible_evidence 429 · oversized 45; counters overlap). The PoC writer paraphrased; nothing was ever citation-bound. | IN-FLIGHT |
| Tier-1 ontology is free and deterministic | `ontology-tier1-baseline.json` (2026-09-08, 5,813 sessions): 7 classes, 6 properties, 13,528 individuals, 29,475 relations; **3.42 s cold, 3.28 s second full, 1.12 s incremental**; one identical `logical_hash` across all three runs; `domain_range_violations 0`, FK violations 0, coverage 1.0. Zero model-provider references in 1,663 lines → $0. | IN-FLIGHT |
| Tier-1 ontology does not improve recall | PoC arm **O** (graph only) 0.32 overall, 0.00 paraphrase; **OH = RRF(O, A2, B) 0.48 = H 0.48 — adding it moved recall +0.00** (`RESULTS-final.md:85-110`). Excluded from shipped recall by design in three places (`memory_recall` docstring: "No embedding or ontology store participates"; `recall.py:24-25`; `claims-audit.md:28`). On the live DB, single-path lookup via `touched` edges was slower than an FTS phrase query in 3/3 cases and found equal-or-fewer sessions. | PoC / IN-FLIGHT |
| What the ontology *does* answer that FTS cannot | Typed, relational questions at $0 on the live graph: harness mix over 5,818 sessions (claude_code 60.9 %, kiro_cli 10.6 %, …), 424 `childOf` subagent-lineage edges, per-class inventory, artifacts ranked by *distinct sessions*. A capability difference, not a measured recall gain. | IN-FLIGHT |
| Multi-machine sync is safe | Two-Mac runbook 4/4; deleted rows cannot be resurrected (`sync.py:610-625` anti-resurrection filter); divergent merge fails closed | SHIPPED |
| Multi-agent lineage survives | Fixed exporter verified at 99.8 % capture; 424 `childOf` edges on the live graph | SHIPPED / IN-FLIGHT |

Full method, scoring legend and threats to validity: `RESULTS-final.md` and
`GLOSSARY.md` in this directory. The 2026-09-09 quantification with every query
inline: `reviews/evidence/173-okf-ontology-value.md` (gitignored, local).

## How the ontology is built — and what "from the data" means

The **schema (T-Box) is hand-written**: seven classes (`Project`, `Harness`,
`Session`, `SubagentSession ⊂ Session`, `Artifact`, `Command`, `TestRun`) and six
properties (`ranIn`, `conductedBy`, `childOf`, `touched`, `executed`, `produced`)
are literal tuples, frozen, inserted verbatim on every build. Every property has
`Session` as its domain — the graph is a star, with no Project↔Artifact,
Command↔Artifact or session-to-session edge.

Only the **instances (A-Box) are derived**, by one column and four regexes over
canonicalised message *text*: `Project` from `sessions.project_path`, `Artifact`
from any absolute macOS path *mentioned*, `Command` from a `$ `-prefixed line or
fenced bash block keyed on its first token, `TestRun` from a *quoted* pytest
summary. Nothing reads tool-call metadata; the graph records what was said, not
what was done, and entity resolution is exact-string equality. "Incremental" only
skips re-running the regexes on unchanged sessions — all six tables are rebuilt
and swapped every time, and any inconsistency falls back to a full rebuild with a
named reason.

**Tier-2 concepts do not enter the ontology.** Decision, Finding, Problem,
Preference and Procedure are a string-enum `type` column in `context_concepts`;
there is no `Decision` class and no property whose range is a concept, so a
concept cannot be typed against or linked to a `Session` individual. The
concept-authoring modules contain zero references to the ontology.

## How context reaches an agent

Two MCP servers, ~26 tools. As of 2026-09-09 every harness definition, both
shared protocol docs and the `studyloop-session-memory` skill instruct the same
three calls at session start: `session_search` (where a topic was discussed),
`memory_search` (what was previously decided or disputed — quote-bound assertions
with attributed reviews and `contradicts`/`corrects` relations, plus explicit
`coverage` limits), and `get_concept_context` (the topic's prerequisite edges).
Kiro's `allowedTools` and the repo-owned MCP configs register what they instruct;
pi's MCP registration path is unverified, so pi uses the CLI fallbacks. Before
that date the `memory_*` family and `get_concept_context` were named by no agent
file at all.

The `memory_*` family separates *evidence* (immutable, hash-bound) from
*assertions* (an agent's reading, bound to 1–8 exact quotes — "a quote match
establishes binding, not entailment") from *reviews* (attributed verdicts, never
certification) from *relations* (both histories kept). Retrieval is biased toward
conflict; absence of a contrary edge in a response is never evidence of its
absence. `memory_decide` refuses branch names as identities and states in its own
payload that a matching execution record does not establish correctness or
permission to ship.

The plan interview (`GET /plans/interview`) reads only the learning tier: it
sees what the learner struggled with, not what was decided about it nor what it
depends on.

## What Phase 2 implements — and what it does not

1. **`memory_recall`** (IN-FLIGHT): authorised concepts first, then deduplicated
   raw sessions. Concatenation with dedup — **not** RRF fusion, no embeddings, no
   ontology. The 2026-09-06 record's "fusion retrieval (OKF + FTS planner +
   embeddings)" describes the PoC bench, not this code.
2. **`memory_winddown`** (IN-FLIGHT): 0–8 evidence-cited concepts per session,
   atomic, JSON → SQLite. The skill is linked into Claude and Kiro.
3. **Ontology MCP tools (`ontology_query`, `neighborhood`, `provenance`)** — **do
   not exist** in any branch. The ontology is reachable only via the
   `session-weaver ontology status` CLI. This item was a plan, recorded here as one.
4. Validity dashboard in doctor — not yet started.
5. Backlog: `reviews/sessionweaver-plans/BACKLOG-phase-2.md`.

## Open measurements

The point estimates favour the concept store; the receipts do not yet establish
it. To move any claim above from "point estimate" to "established": a gold set of
**n ≥ 100** authored without LIKE-pattern selection; re-scoring A6 on *bound*
concepts after fixing the 1,559 `no_exact_match` / 764 mismatch records; an
ontology-inclusive arm run against the live DB with `ontology_build_state`
recorded; an embedded concept store to attack the paraphrase floor; and the
measurement nobody has taken — token cost and task-completion quality for an
agent consuming these stores. Recall@5 is a proxy for that, not the thing itself.

## Corrections to the 2026-09-06 record

| It said | Verified | Source |
|---|---|---|
| Ontology "$0, 0.2 s, 13,384 individuals / 28,698 relations" | The counts and the timing come from different runs. `0.2 s` was a 357-session structural extraction or an OKF index build, never an A-Box rebuild. Authoritative: **3.42 s cold / 1.12 s incremental**, 13,528 / 29,475 at 5,813 sessions. The 13,384 / 28,698 pair is attributed to two corpora 191 sessions apart; no receipt arbitrates it. | `ontology-tier1-baseline.json`; `DAY1-cutover.md:15`; `RESULTS-final.md:88-89`; v48 receipt |
| "Agent-authored OKF knowledge store written at session wind-down" | Wind-down writes JSON to SQLite. OKF is a frozen import-only legacy format; the skill says "never hand-write OKF files". | `okf_import.py:1`; `concept_cli.py`; `SKILL.md:108` |
| "Fusion … 0.68 recall@5" | Superseded. Current gate 0.60 [0.41, 0.77], INVESTIGATE; raw control 0.48 inside the CI. The 0.68 included a vector arm the shipped path does not have. | `SKILL.md:140-162`; `bench-t2.py:138` |
| "Ontology MCP tools (`ontology_query`, `neighborhood`, `provenance`)" as an implemented item | Not present in any branch; plan item only. | grep of `packages/`, worktree `mcp_server.py` |
| Diagrams "visual-check pass" | True for the 2026-09-06 PoC diagrams. The 2026-09-09 diagram has a deliver receipt only; browser check was environmentally blocked. | this file |
| Implicit: a multi-tier ontology | Tier-2 never enters the graph; single-tier today. | `okf_import.py`, `concepts.py`, `winddown.py`: 0 references to "ontology" |
