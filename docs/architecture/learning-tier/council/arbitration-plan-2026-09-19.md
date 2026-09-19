# Arbitration — learning-tier council, planning round (2026-09-19)

**Brief:** `brief-plan-2026-09-19.md` (21,694 bytes). **Seats:** `openai.gpt-6-astra` (ACCEPT-WITH-CORRECTIONS,
3,099 tokens, 49.7 s), `qwen3-coder` (ACCEPT-WITH-CORRECTIONS, 998 tokens, 12.6 s), `grok-4.6`
(first run INVALID — 24,000-token tool-announcement loop, `seat-grok-4.6.INVALID-tool-loop.md`; re-run with
`scripts/council/system-seat.md` valid: ACCEPT-WITH-CORRECTIONS, 16,319 tokens, 111 s,
`plan-grok-rerun/`). All three: **ACCEPT-WITH-CORRECTIONS.** Coordinator: Kiro. Every BLOCKING/MAJOR claim
below was checked against the tree at `4f8e3e0f` or the two databases (read-only) before it entered the plan.

## Facts established after the brief (seats flagged as UNVERIFIED; coordinator verified)

| # | Fact | Evidence | Consequence |
|---|---|---|---|
| E1 | **The gold labels were authored against the pre-rebuild corpus, and the live copies differ.** Labels committed 2026-05-31 (`6c7176e8`); clean-start rebuild 2026-09-12. Of the 10 gold sessions in both DBs, **9 have different transcripts** (live 81/archive 89 … `agent-a7ccf07` live 49/archive 195); 3 are archive-only. | `sessions.db` vs `archive/sessions-archived-20260912.db`, per-session sha of ordered `(role, content)` | **Ruler = archive, all 13, `mode=ro`.** Not live ∪ archive (brief §5.1 withdrawn). Astra F04 confirmed and sharpened. |
| E2 | Both databases are schema **48** with identical `messages` columns. | `PRAGMA user_version` on each | Grok B4 **falsified** as a present risk; keep a one-line schema probe as a cheap guard. |
| E3 | `STUDY_SOURCES = frozenset(SESSION_SOURCE_BY_HARNESS.values())` and `"claude": "claude_code"`. | `extractors/pipeline.py:32`, `harnesses.py:35` | Grok B3 **falsified**: the three `claude_code` negatives pass `pre_filter`. Keep the post-filter 13/13 recompute as a guard anyway. |
| E4 | `eval_runner.py:248` already opens the DB with `?mode=ro`, `uri=True`. | source | Grok B2 **partly falsified** (existing code is read-only); the constraint is carried into the new gold source. |
| E5 | Held-out = 3 positives + **2 negatives** (`agent-aa1015b3cd2de6078` archive-only, `agent-a539efd`). Train negatives = 3 (two archive-only). | `eval_split.json` ∩ gold `is_negative` | One-sided 95 % upper bound on a 0/2 FP observation is **77.6 %**. Astra F08 / Grok M2 confirmed: the FP = 0 gate is descriptive, never evidential, at this n. |
| E6 | C1 (`results.tsv`, 83 rows) is **train-only** (`f1_held_out` empty), and its train recall ranged 0.111–0.778 across hill-climb iterations (25 rows at 1/9, 5 at 7/9). | ledger columns + `awk` distribution | Astra F05 confirmed: C1 is historical, non-comparable; **dropped from any decision rule**. Also corrects the coordinator's own earlier claim that recall was "stuck at 1/9". |
| E7 | `record_study_progress` (`mcp/tools.py:114`) passes `card_hash` straight to `record_review` with no existence check at the tool layer; `log_review_outcome` validates only `card_type`. | source | Grok B1 confirmed in substance: SRS mutators can be fed invented hashes → **split `W_auto` / `W_srs`** (below). |
| E8 | codex, pi and grok adapters all write the **canonical persona into a session-dir `AGENTS.md`**; none has an in-repo per-tool grant grammar; MCP registration is harness-side (`grok mcp add`, codex config). No `agents/grok/` exists. | `adapters/{codex,pi,grok}.py:1-27,97-102`; `agents/codex/AGENTS.md:53-54` | Grok B5 confirmed; Astra Q2 answered: for these three, "grant parity" is **not expressible in-repo**. Parity = canonical persona carries the trigger table; approval policy is documented as harness-side. Do not create `agents/grok/`. |
| E9 | `log_topic` binds the session through `session_state.append_topic` (`mcp/tools.py:583-616`); `isolation.py` names `STUDYLOOP_SESSION_DIR` "the one-session authority" and gives the harness an empty scratch `HOME` in default mode (real `HOME`/`XDG_*` only under `STUDYLOOP_ACC_REAL_AUTH=1`). | source | Grok N1: `record_teachback` binds `session_id` the same way. Astra F03: isolation is designed; the **0-writes-outside-sandbox test** is still added because it is cheap and the failure is silent. |
| E10 | **All six harness binaries are installed on the owner's machine** (`kiro-cli claude codex opencode pi grok`). | `command -v` | Astra F01 is achievable locally; Grok Q4 "don't wait for six binaries" is moot. Credentials per harness remain UNVERIFIED → the acceptance tier's skip-by-name governs. |
| E11 | `tutor-checkpoint` is referenced by `agents/kiro/study-mentor/persona.md:32`, `agents/kiro/skills/study-mentor/SKILL.md`, and `agents/kiro/skills/tutor-progress-tracker/SKILL.md` (a separate, cross-agent skill). | grep | Grok M5 confirmed for the persona line; the tool itself stays (owned by another skill). Reconcile `:32`, do not delete the entry point. |

## Decisions

### Item 1 — feed the tier

- **D1 (Q1, unanimous).** Add MCP `record_teachback`. Shared validator with `cli/_teachback.py:16-46` (one implementation, both surfaces), delegate to `history/teachback.py:27`, bind `session_id` from session state (E9), keep the CLI. Tests: wrong cardinality, non-int, out-of-range, bad `review_type`, no row on failure, CHECK 1–4 honoured.
- **D2 (Q2, Grok B1 + Astra Q2).** Writer set splits: **`W_auto` = {`log_topic`, `log_struggle`, `record_teachback`, `record_plan_learning`}** — additive, human-agreed or human-stated signals, pre-approved on kiro (`allowedTools`) and permitted on claude (`settings.json`); **`W_srs` = {`record_study_progress`, `log_review_outcome`, `record_topic_progress`}** stays prompt-per-call until those functions reject an unknown `card_hash`/topic id (a follow-on, not this branch). Tool pre-approval never replaces the learner's score-agreement step in `teach-back-protocol.md:127-140`. opencode's `studyloop *` wildcard is recorded as **not** least-privilege; left as-is this branch (changing it is a separate decision).
- **D3 (Q3, Astra + Grok agree).** One machine-readable trigger table (fenced YAML in `agents/shared/recording-protocol.md`: trigger → writer → required ids → consent step) plus generated one-line prose per trigger. CI parses the YAML, asserts the same bytes in every projected copy, asserts every persona names every `W_auto` tool, asserts `agents/manifest.json` hashes. `persona.md:32` rewritten to name the writers (E11). Hosts: `test_adapter_parity.py`, `test_docs_harness_tier_contract.py`.
- **D4 (Q4, Astra F01 ⊕ Grok — reconciled).** Definition of done says **exactly what was observed**: (a) CI: parity + contract + projection + one replay fixture (MCP layer, scratch DB) green; (b) acceptance: the **six-harness matrix is run** (E10) with the scripted *vague* learner's teach-back episode; each harness **passes or skips by a named reason**, recorded in the evidence bundle; **no skip is counted as a pass**; the PR body lists the harnesses that passed and calls the rest open. Plus **one owner-led noticing episode** (Astra F02/Q4): the owner does not ask for logging; expected trigger/no-trigger outcomes adjudicated afterwards — recorded as an observation, not a gate. DoD wording: "pipe open on {passed harnesses}; plumbing proven for all six definitions; noticing observed once" — never "the mentor will write in the wild".
- **D5 (Astra F02).** The scripted episode asserts deltas in **all three stores** it can reach — `teach_back_scores`, parking (`log_struggle`), `study_progress`/`session-topics.md` (`log_topic`) — plus a **no-trigger case** (a turn that must not write) and a **repeated-call case** with the documented duplicate behaviour.
- **D6 (Astra F03).** Isolation test: child process with deliberately conflicting `HOME`/`XDG_*`, run every `W_auto` writer, assert **0 writes outside the sandbox** including Markdown.

### Item 2 — measure Jev on struggle classification

- **D7 (E1).** Gold source = **archive only**, `mode=ro`, all 13, per-session transcript fingerprint pinned in the pre-registration, refuse on < 13/13, schema probe (E2), no `ATTACH` to the live file, no import into live (Q5 unanimous). Learner turns only, scrubbed (D10).
- **D8 (Q6 — Astra's design, Grok's honesty clause, Qwen's appendix).** Run **J-b with a matched-candidate ablation**: the harness LLM (allowed by the rule) proposes ≤ 8 `(topic, concept)` candidates per session **without gold access**, frozen and fingerprinted before any Jev call; score the *same* candidate list (i) unfiltered, (ii) Jev-filtered (one Noul per candidate + gate). The delta is Jev's incremental contribution with vocabulary held fixed. Receipt title says "harness namer + Jev filter", never "Jev classified struggles". **J-c** (turn-level "expresses being stuck" Noul) reported as a component appendix. **J-a** only if a non-gold candidate list covers ≥ 50 % of the 23 train labels (Qwen F4 / Grok M4); coverage measured and committed first.
- **D9 (Q7 — unanimous).** **Directional only.** No adopt/reject clause, no product wiring. Report the runner's four metrics + `eval.metrics` cluster-bootstrap CIs + per-session outcomes + denominators (E5). Verdict vocabulary: *supports further evaluation* / *no observed incremental benefit* / *inconclusive*. Control arms: **C0 predict-nothing**, **C2 deterministic per-session keyword arm on the same frozen candidates**; **C1 historical, not comparable** (E6).
- **D10 (Astra F07).** Scrub **every outbound field** (state, candidate slugs, question text) and every artifact; a seeded synthetic bearer token must not survive in the serialised request, logs or receipts (test). Whole-repo `detect-secrets scan --baseline` before any receipt commit.
- **D11 (Astra F09).** Pre-registration records hashes of: gold fingerprints, split, metric code, candidate generator prompt + model, normaliser, chunk→session reduce rule (Grok M6: token-count the three archive negatives after scrub first), gate-selection procedure, retry policy. `state` per call stays under 32k; zero Jev calls on gold before the pre-reg sha.
- **D12 (N2).** No Jev import under `content/`, `mcp/` or `learning/`; eval scripts only; `jev-1.13.0` pinned; spend ledger.

### Sequencing

- **D13 (Q8 — Astra and Grok agree; deviates from the owner's ask).** **Two branches from `main`, two PRs**: `feat/learning-tier-fed` and `feat/jev-struggle-eval`. Neither is a data prerequisite for the other (item 2 scores frozen gold); one branch would let Jev spend/privacy block agent-definition landing and stack unrelated risk. The owner asked for one branch; this arbitration recommends two and flags the deviation for his decision.

## What each seat contributed that the others did not

- **Astra:** F04 (source identity — which became E1, the single largest correction), F03 isolation test, F05 C1 provenance, F07 outbound-field scrub, F09 procedure freeze, the matched-candidate ablation, and the "no skip counted as a pass" finish-line rule.
- **Grok:** B1 the `W_auto`/`W_srs` split (SRS mutators as the data-loss step), M5 `persona.md:32`, N1 session binding, M6 chunking of long negatives, and the two-branch split argued from risk isolation.
- **Qwen:** the coverage gate as the ONE THING; a clean second vote for J-c as component-only and for directional-only.
- **Falsified after checking:** Grok B2 (already `mode=ro`), B3 (`claude_code` is in `STUDY_SOURCES`), B4 (schemas equal). Kept as cheap guards, not blockers.

## Council rounds still to run

1. **Item 1 implementation review** after S1-GREEN (three seats; brief = diff + test output + evidence bundle).
2. **Item 2 pre-registration review** (one seat) before the first Jev call on gold; **result review** (three seats) before the owner reads the held-out receipt.
