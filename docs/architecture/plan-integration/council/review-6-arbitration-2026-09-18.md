# Arbitration — council review 6 (items 1–4 of the plan-integration follow-on programme)

**Date:** 2026-09-18 · **Arbiter:** coordinating agent (owner present at the session start; the review and its
corrections ran unattended between two owner turns) · **Reviewed tree:** `feat/plan-close` @ `9d10fee6` (five
commits on `main` `46262d23`; range `1565234a..9d10fee6`, 29 commits, 73 files, +4,727/−201). Seats ran against
`brief-review6-2026-09-18.md` (`review6/manifest.json`, run 09:59:01Z; every seat `finish_reason=stop` with
content; no re-run). **This was the batch code review** the follow-on plan reserved for items 1–4: the Kiro/Claude
MCP grants (D-A), the brain dump on the Web door (D-B), husk discovery + `plan repair` (D-C) with the 3b mission
writer, and `plan close` (D-G) — plus the seven commits outside the items that rode the same branch.
**Corrections landed at:** `f937b1b5` (F1), `97efcc4a` (options-wait bound), `0887b1fb` (F4), `13b5d121` (F5),
`6d01d919` (F6), `88aa6610` (F2), `8d825a52` (F7 tests); the T6.3 verify work (`3844c3e0` RED, `b9773007` GREEN)
was written while the seats ran and is independent of them.

**Brief size, recorded:** 341.6 KB, 6,082 lines (~95k tokens): every diff in the range was embedded grouped by item,
the seven delta specs in full, design §1–§4 and the T-notes verbatim. Prompt tokens as billed: 88.6k (GPT), 95.4k
(Grok), 90.6k (qwen). **Digest, recorded:** the manifest's `brief_sha256` (`7ef91328…`) is the bytes the seats
received; the committed brief (`82cb3682…`) differs by trailing whitespace only — the pre-commit hook stripped it on
commit (`d0251fd1`); `diff` after stripping trailing whitespace from both is empty. Every sentence a seat quotes
was checked against the tree, not the digest.

## Seats and verdicts

| Seat | Verdict | Receipt |
|---|---|---|
| `openai.gpt-6-astra` | **ACCEPT-WITH-CORRECTIONS** — two 🔴 (F1 partial assessment reads as a clean close; F4 discovery text claims history the seam cannot know), five 🟡 (F2 brief containment, F3 abandonment contract + options wait, F5 permission evidence, F6 Today card grouping/label, F7 uncovered completion cases), two 🔵 (F8 table of accepted choices; F5's disclosure follow-up), one 💡 (F9 cross-item). Per item: 3b and the two outside fixes `bfe0695c`/`112c98bf` ACCEPT; the rest ACCEPT-WITH-CORRECTIONS. | `review6/seat-openai.gpt-6-astra.md` (7.8k tokens, 129.9 s) |
| `grok-4.6` | **ACCEPT** — zero 🔴/🟡; five 🔵 (Claude server declaration not in the brief; `session-db` "prompts" is an extrapolation; the abandon test is a characterisation pin; no timeout on the options wait; a partial assessment with zero counts proposes `close`) and six 💡 (items 3, 3b, cross-item, RED rewrite, report-vs-diff). | `review6/seat-grok-4.6.md` (15.9k tokens, 649.3 s) |
| `qwen3-coder` | **ACCEPT** — one 🔴 (the options wait has no timeout; empty-agent handling), one 🟡 marked by the seat itself as "already addressed" (`husk_provenance` placement), one 🔵. | `review6/seat-qwen3-coder.md` (2.3k tokens, 43.3 s) |

### Method

Every 🔴/🟡 was **reproduced before acceptance** — a RED test that fails on `9d10fee6` for the seat's stated reason and
passes after the fix, or a direct probe of the renderer/markup — or rejected with the reason below. Two or three
seats naming one defect are one finding here, credited to each. Every correction is its own commit with the RED
inside it; where a fix changed a persona or a spec, the projections, manifest, secrets baseline and spec deltas
moved in the same commit. Numbers below are from the runs, not from memory.

### Findings and dispositions

| # | Finding (seat) | Sev | Reproduction on `9d10fee6` | Disposition | Landed |
|---|---|---|---|---|---|
| F1 | A partial end assessment presents as a clean close: `_safe` turns a failed reader into a warning + empty default, so all counts read 0, `CompletionReview.from_evaluation` says `close`, the `now` sentence says "the closing review is clean", and `plan close` prints "proposes: close" with the gap in a later section (GPT F1 🔴; Grok 🔵 v) | 🔴 | RED `test_completion_partial_assessment_never_proposes_a_clean_close` (engine): due reader raises, mentions cover both concepts → `proposal='close'`. RED `test_plan_close_with_a_partial_assessment_does_not_present_a_clean_proposal` (CLI): status line "proposes: close". Both failed for exactly that reason. | **Accept.** Fixed in the one definition: `CompletionReview` keys on the evaluator's own `PARTIAL_READ_MARKER` (now a constant in `evaluation.py` used by `_safe`), keeps the counts it read, sets `partial=True`, proposes `None`, and carries each gap as a `Not read: …` evidence line, so both surfaces say what was not read. `CompletionAction.partial` added; a third sentence branch ("partial — could not propose"); `plan close`'s proposal line reads `unassessed — the review is partial` and its status line no longer says the review proposes; the separate `### Data gaps` section is gone (the gaps are the review's lines). Persona "Closing a Plan" says what an unassessed proposal means (walk what was read, prefer re-running the review, never infer a clean slate). Spec delta states the rule + scenario. | `f937b1b5` |
| F2 | The repair/closing briefs interpolate title, id, topics, created and evidence lines raw; the Web brief one-lines every value (review-3 F4). A YAML-quoted front-matter title with `\n## …` survives `parse_plan` (GPT F2 🟡) | 🟡 | Probe: `_render_plan_as_it_stands` on a summary whose title is `Innocent\n## Forged section` produced `## Forged section` as a heading of the brief; `parse_plan` confirmed such a title round-trips from disk. RED `test_repair_and_closing_briefs_contain_multiline_plan_fields` failed on the forged heading. | **Accept.** One definition on the seam, `studyloop.planning.one_line`; both CLI briefs quote every learner-authored value through it; the Web door's `_one_line` delegates to it. Blocker lines are seam-authored and untouched. Guard (D-6) passes: `one_line` is a `studyloop.planning` import. The seat's per-value/overall byte budgets for the CLI briefs are **not adopted**: the briefs quote a bounded set of scalar fields plus a capped evidence list (`COMPLETION_EVIDENCE_CAP`), unlike the Web brief's open seed. | `88aa6610` |
| F3a | The options wait added by `626ea129` has no bound: a `/api/session/options` request that never settles holds a planning click forever — no POST, no refusal (qwen 🔴; GPT F3 🟡; Grok 🔵 i) | 🔴 | RED JS `a planning click does not wait forever for options that never settle`: fetch returns a never-settling promise; the test timed out at 5 s. | **Accept.** `Promise.race` against `optionsWaitMs` (8 s, on the timer's state so tests shorten it); past the bound the launch judges the agent as it stands and gives the picker's own refusal; a later settlement launches nothing on its own. The two existing wait tests unchanged. Spec delta (web-ui) states the wait and its bound. qwen's second half — "an empty agent list still attempts a launch" — is **refuted**: `startPlanning with no agent available after the options resolve still refuses by name` pins the empty-picker refusal (Grok read it the same way). | `97efcc4a` |
| F3b | Design §2 promised "navigate away / cancel before the console attaches" as abandonment; the landed browser test proves End-after-201 and its docstring says navigation is *not* abandonment; the pre-attachment cancel contract is unsettled (GPT F3 🟡; Grok 🔵 h) | 🟡 | By reading: `test_abandoning_a_launch_mid_flight_leaves_no_session_and_no_plan` was green at RED time (`71a74894`, recorded in T2.1's own note); the web-ui delta says navigate-away is a detach, not an abandon. Reproduced as a **design gap**, not a code defect. | **Accept as an owner decision, not an agent edit.** The three alternatives GPT names (cancel invalidates a pending launch; navigation detaches an attached session for a grace period; or the narrower scope — only accepted-session End — recorded as the contract) change what a learner's action means. Recorded under "Still open for the owner"; design §2's sentence stays as written until decided. The characterisation test is kept and not claimed as a RED (Grok). | — |
| F4 | Discovery text asserts what the seam cannot know: `husk_provenance` says a pre-gate `created` "was never judged by it" (a pre-gate plan can be saved ready after the gate and hand-edited later); doctor's healthy row says "every write the gate judges will pass" (a future write can remove a field); `husks()` skips an unreadable document so doctor can report all-ready over a file no listing can read (GPT F4 🔴; Grok 💡 "slightly stronger than the seam knows") | 🔴 | RED `test_husk_provenance_states_only_what_the_creation_stamp_establishes` (parametrised; the two pre-gate cases failed on `never judged`); RED doctor: `will pass` present; RED `test_an_unreadable_plan_document_is_named_not_hidden_behind_all_ready` — first fixture was **not** unreadable (the parser is lenient with malformed front matter and yields an untitled draft), the real class is a non-UTF-8 file or a filename that is not a valid id; re-fixtured, failed as intended (`['pass'] == ['pass','warn']`). | **Accept.** Sentence: "This plan's creation stamp predates the readiness gate (…); the seam cannot tell when it became incomplete." Healthy row: "all ready as they stand." `PlanApplication.survey_husks()` returns `HuskSurvey(husks, unreadable)` in one pass; `husks()` is a view over it; doctor emits one `warn` row per unreadable id beside the readiness rows. Health and cli-surface deltas updated. | `0887b1fb` |
| F5 | Permission claims need evidence: Claude's frontmatter names tools but nothing in the brief declares the `studyloop` **server** for Claude Code, so the grant could be inert as the mentor's was; `session-db` "visible, prompts" is an extrapolation; the mentor grant activation (`f5c2057d`) is undisclosed to users; the probe is version-pinned (GPT F5 🟡; Grok 🔵 c, 🔵 a, 💡 d) | 🟡 | By reading source the brief did not carry: `installers._MCP_HARNESSES = ("claude", "kiro", "codex", "opencode", "grok")` and `_mcp_config_path("claude") == ~/.claude.json` — `studyloop install agents` merges both servers into Claude's global config. The grant is **live**; the finding was a brief gap, correctly flagged as "not established". | **Accept the disclosure, refute the defect.** `docs/agent-install.md` names the Claude registration path — the pin takes it from `installers._mcp_config_path("claude")`, not a remembered string — the mentor activation for existing installs, and the version-pinned re-probe instruction; the probe receipt's header says the same and records that the `session-db` shape is an expectation, not a measurement. No doctor spelling-linter (Grok: over-engineering; GPT: unnecessary complexity). The trusted `execute_bash`/`Bash` is the **accepted** least-privilege shape (both seats): D-A stops the *need* to fall back to `studyloop plan …`, it does not remove the built-in shell. | `13b5d121` |
| F6 | The Today card printed every completion sentence, then every evidence line flattened beneath them — two finished plans lose the association — and both the card and CLI `now` labelled the note "Plan complete" over a plan still `active` (GPT F6 🟡) | 🟡 | By reading the markup (`index.html` completion loops) and `completionEvidence()`; RED JS `completionReviews: one block per finished plan…` failed (`completionReviews is not a function`). No test had pinned either label. | **Accept.** `completionReviews()` groups sentence + own evidence per `plan_id` in the engine's order; the flat helpers derive from it; the markup renders one `.today-plan-review` block per plan (`data-plan-id`) labelled "Closing review", and CLI `now` prints the same label. A markup test pins the keyed block, the nesting, and the absence of a flat evidence loop and of "Plan complete". Recap's sentence-only presentation is accepted (both seats); the seat's remark that the clean sentence does not print three zeros is true and left as designed — "clean" is defined in the spec as the zero counts. | `6d01d919` |
| F7 | Completion tests omit: struggle-only extend; unverified-only extend; evidence-cap overflow; `plan close` on a complete plan, on zero milestones, on an unknown id (GPT F7 🟡) | 🟡 | By reading the seven REDs: none planted a struggle-only or unverified-only evaluation, none exceeded the cap, and `plan close` had two CLI tests. | **Accept.** Six tests added; the zero-milestone test also proves no assessment is read on that exit. Discrimination proved by mutation: with the proposal rule changed to read the due count alone, exactly the struggle-only and unverified-only tests fail; source restored byte-identical. The seat's other asks are **rejected or deferred**: a "conversion failure inside `from_evaluation`" test — the method has no failing path over a well-typed view; "partial-reader outcomes" — F1's tests; the struggles-count `concept: None` hazard — the evaluator's `_relevant` filter admits only rows touching the plan's topics/concepts and no synthetic struggle row exists (Grok: "not established"), so no change without evidence. | `8d825a52` |
| F8 | GPT's table of accepted choices and 🔵 asks: whitespace-only dumps (met: `trim()` and `.strip()` agree — Grok j); husk predicate copied three times (accepted: two clauses); `plan repair` exit 0 on non-active unready (accepted; `test_plan_repair_nonactive_unready_is_noop_with_pointer` **not added** — the behaviour is pinned by `test_plan_repair_on_a_ready_plan…`'s sibling path only implicitly; recorded as a cheap follow-on); `duplicate_record_only` + mission revision saves once (the branch is exercised by `_revise`'s existing tests; not separately pinned — follow-on); D-3 pin not vacuous (Grok agrees); relocation of `husk_provenance` is a real boundary (all three seats). | 🔵 | — | **Accept the table; no code change.** Two cheap pins recorded as follow-ons in tasks.md rather than folded into this review's commits. | — |
| F9 | Cross-item: the reconnect-purpose sentence in brief §9 ("a CLI-launched architect reconnects labelled `focus`") **contradicts** the web-ui delta, which infers `planning` from a persisted `mode="plan-architect"` (GPT F9); `husks()` scans `list_plan_ids()` rather than reusing `get_active_guidance()` as the T-note advertised; T4.3 still read `PENDING` after the verdicts were recorded (GPT ff) | 💡 | By reading: `_dashboard.py`'s state overlay does infer `planning` from the persisted mode (`test_session_start_purpose.py` pins it) — the **brief's §9 sentence was wrong**, the code is right; the arbiter's error, recorded here. `husks()`: the T3.2 note said "reuses `browse`'s load path" (it does, via `_load`), not `get_active_guidance()` — the seat's paraphrase; no correction. T4.3: the seat read the tasks.md **inside the brief** (frozen at `9d10fee6`); the verdicts landed in `9d10fee6` itself and T4.3 was updated there — checked, the current text says "scored by the owner on 2026-09-18". | **Accept the correction to the brief's reference fact; no code change.** | this file |
| F10 | Spec/doc nits (GPT §3): `active-learning-decisions` says "Rule 8" where code and rubric say rule 9; `web-ui` omits the options wait; `health` omits per-document parse errors; `cli-surface` omits incomplete-assessment behaviour and dynamic-field containment; `docs/agent-install.md` "no CLI command edits fields" should mean no *generic* revision command | 🔵 | By reading. | **Accept:** "Rule 9" fixed (this commit); the options wait, partial assessment, unreadable documents and honest provenance are in the deltas via F1/F3a/F4's commits. **Rejected:** rewording "no CLI command edits a plan's fields" — the sentence sits beside the `plan status` / `plan milestone` rows in the same table, so the scope is plain; the mcp stdio-transport invalid-list test — the in-process tool test exercises the same validation the transport does, and the stdio smoke pins the inventory, not every refusal. | this commit |

### Rejected, with reasons

- **qwen 🔴 second half — "the launch still proceeds with an empty agent list".** Refuted by `startPlanning with no agent
  available after the options resolve still refuses by name` (`plan-architect-launch.test.js`), which Grok also cites.
  The first half (no timeout) is F3a and was accepted.
- **GPT F2's byte budgets for the CLI briefs.** The repair/closing briefs quote a bounded set of scalar summary fields
  and a capped evidence list; the Web brief's budgets exist because its seed is open-ended. Containment (one line)
  is the defect; a budget would be defensive code for an input that cannot grow.
- **GPT F5 — a live `session-db` approval probe and `test_kiro_architect_does_not_autoapprove_session_db`.** The
  receipt now states the shape is an expectation, not a measurement; a further probe is owner-side work on the
  installed CLI (the harness prompts are not observable from a test), recorded below, not a code change.
- **GPT F7 — `test_completion_review_conversion_failure_warns_without_failing_now`.** `CompletionReview.from_evaluation`
  reads typed tuples off a frozen view; there is no failing path to exercise without inventing one.
- **GPT F7 — the `concept: None` hazard on the struggles count.** `_gather_concept_evidence._relevant` admits a struggle
  row only if it names the plan's topic or a concept; no synthetic struggle row exists (`get_struggling_topics` has no
  cold-start hint). Grok: "not established by the brief"; the arbiter checked the source and found no such row.
- **GPT 4(iii) — ten separately-registered verify checks.** Registered as two (`architect-grants`, in-process and
  inventory-derived; `repair-close-refusals`, four node ids), plus `failed_nodes` on every red pytest row — the two
  design §6 asked for. The other eight are covered by `plan-suites`, `js-unit` and `browser-journey-e2e`; ten more
  names would make the receipt longer, not more auditable.

### Verification after fixes

- Per-correction runs (each recorded in its commit): F1 66/66 across the two item-4 files, 614 across the plan
  suites + pins, JS 136/136; F3a JS 137/137, browser journey 11/11 `-m e2e`; F4 312 across the pinning files,
  guard 30/30; F5 137 across persona/install/docs/prompt-contract pins, `mkdocs --strict` clean; F6 JS 139/139,
  CLI now/guidance/seam 67/67, e2e Today/plan subset 29 passed; F2 guard + CLI seam + Web brief tests 119; F7 73
  across the two files. Golden sha `ec451ce8…` unchanged throughout. `ruff`, `ruff format`, `pyright` clean at every
  commit; `openspec validate` valid; all 15 hooks first time (the T6.1 artefact commit was rewritten once by the
  whitespace hook, recorded above).
- **Pre-correction verify (29 checks) on `9d10fee6`:** 28/29 — only `full-suite-studyloop` red with the sandbox's
  30 failed / 14 errors; a separate `-rfE` run captured the ids and they are **exactly** the 44 named in
  `receipts/full-suite-control-item4-2026-09-18.md` (∅ both ways). That reconciliation is why `failed_nodes` now
  exists on the receipt row.
- **Post-correction verify (31 checks) on the head this arbitration is committed with:** see
  `receipts/verify-<sha>.json` beside this file and T6.3's tick — the run was started on the clean tree at
  `d0251fd1` and its verdict is recorded in tasks.md, not here, because this file is written while it runs.

### Process findings

- **The owner should have decided the abandonment boundary** (GPT §5): item 2's design promised pre-attachment
  cancellation; the spec and test settled for End-after-201 and called navigation a detach; the options wait adds a
  pending state where the distinction matters. The agent recorded the narrower behaviour as if it were the design's
  intent. Carried to the owner with the three alternatives (F3b).
- **Grok's process pick** — the RED rewrite — is accepted as fine TDD (one RED still precedes GREEN; the seventh test
  pins the owner's exclusion, not a second change); the four test/CI commits belong on the PR that was red.
- **The arbiter's own error:** brief §9 stated a reconnect fact the code contradicts (F9). Reference facts are
  supposed to be verified on the tree; this one was recalled from review 4's hazard list. Corrected here.
- **What the council could not see:** the Claude server registration lives in `installers.py`, outside the diff, so all
  three seats had to mark it "not established". A brief should carry the *reachability* facts a grant depends on, not
  only the grant.

## Gate decision

Seven corrections, each RED-before-GREEN and each its own commit; every 🔴 reproduced then fixed; every 🟡 fixed,
refuted with a named test, or carried to the owner as a decision rather than invented. No finding changes the seam's
shape (no new writer; `survey_husks()` is a read). The batch is fit to merge to `main` once CI has seen it — the
fast-forward is **not** to be made on the strength of PR #20's green, which excluded the item-4 commits and every
correction here (GPT 4-i, agreed).

## Still open for the owner

1. **Abandonment contract (F3b).** Pick one: (a) a pending planning launch can be cancelled and a late settlement or
   POST completion cannot launch or retain a session; (b) an attached session detaches on navigation for a stated
   grace period and End releases it (today's behaviour, made explicit); (c) record (b) as the supported scope and
   pre-attachment cancellation as an acknowledged unmet requirement. Then design §2 and the web-ui delta say the
   same thing and the barrier-based tests GPT names are written.
2. **`plan close` on a checked `draft`/`paused`/`abandoned` plan** launches a review today (D-G did not restrict it to
   `active`). Grok would refuse `abandoned`; GPT would document and pin it. Decide; one test either way.
3. **`session-db` in Kiro's `tools` with nothing trusted** — the "visible, prompts" reading is an expectation. A probe on
   the installed CLI (invoke `session_search` from the architect and observe the prompt) turns it into a receipt.
4. **Two cheap pins deferred** (F8): `test_plan_repair_nonactive_unready_is_noop_with_pointer` and
   `test_duplicate_learning_record_with_mission_revision_still_saves_once`. Recorded in tasks.md.

GATE: ACCEPT
