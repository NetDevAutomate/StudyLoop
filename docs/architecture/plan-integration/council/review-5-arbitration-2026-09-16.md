# Arbitration — council review 5 (Phase 6 docs/spec review: #15 reconcile and verify)

**Date:** 2026-09-16 · **Arbiter:** coordinating agent (unattended) · **Reviewed tree:** `fix/plan-integration-bugs`
@ `fd10789e` (T6.1–T6.5 landed on the accepted Phase-5 base `1e1a5680`). Seats ran against
`brief-review5-2026-09-16.md` (`review5/manifest.json`, run 08:24:03Z). **This was the docs/spec review** the plan
reserved for #15: are the public claims true and bounded, are the specs and docs synchronized, is the close-out honest,
what will the archive make stale. Code was not re-reviewed. **Fixes landed at:** `f0d01d95` (RED, eleven pins written by
the previous agent from the seats before the docs moved), `2911da1d` (RED, two more), `e151885c` (GREEN), `e67f1767`
(evidence test). Phase 5 was accepted in `review-4-arbitration-2026-09-16.md`.

**Brief size, recorded:** 215.0 KB — well over the ~120 KB target; the six delta specs (1 382 lines) were embedded in
full because the archive merges them verbatim. All three seats consumed it in one run (prompt 52.7–55.8k tokens,
`finish_reason=stop`); no re-run manifest exists. **Digest mismatch, recorded:** the manifest's `brief_sha256`
(`7ea8f0d2…`) is not the committed brief's (`c7672a6b…`, committed at `a955ff0a` twenty seconds after `run_at`); the
committed file post-dates what was sent and the difference is not recoverable here. Every sentence a seat quotes was
checked against the committed brief and the tree and matched; nothing below rests on the digest.

## Seats and verdicts

| Seat | Verdict | Receipt |
|---|---|---|
| `openai.gpt-6-astra` | **REJECT** — five 🔴 (F1 T3.4 ticked while D-16 is unscored, F2 architect section overclaims, F3 rubric "recorded", F4 MCP mission revision, F8 two specs disagree on reconnect purpose, F12 close-out schedules unconditional closure), eight 🟡, one 🔵; a full spec↔docs gap table and fourteen owner items | `review5/seat-openai.gpt-6-astra.md` (7.8k tokens) |
| `grok-4.6` | **ACCEPT-WITH-CORRECTIONS** — five 🟡 (F1 rubric sentence, F2 brief on every door, F3 "session run against", F4 T3.4 checkbox, F5 `docs/mcp.md` unexamined), three 🔵 (F6 boundary tuple mixes kinds, F7 installer clause, F8 README heading), four 💡; a gap table | `review5/seat-grok-4.6.md` (20.7k tokens) |
| `kimi-k2-thinking` | **ACCEPT-WITH-CORRECTIONS** — one correction: the D-16 human rubric must be scored by the owner before the close-out is posted | `review5/seat-kimi-k2-thinking.md` (4.5k tokens, 18.9k reasoning) |

### Method

Every 🔴/🟡 was **reproduced before acceptance** — for a docs finding the reproduction is a RED contract test that fails
on `fd10789e` against the sentence the seat quotes and passes once the sentence is true (`f0d01d95`, `2911da1d`), or a
`grep`/read of the tree for a spec finding — or rejected with the reason below. Two seats naming one defect are one
finding group. No product behaviour moved: the installer's printed text, one constant's sixth phrase, the persona's
fallback rows and the verify registry are the only non-Markdown changes, each pinned. The GREEN commit ran the docs
contract (25), the persona suite (17), the install contracts and the verify-script unit tests; `openspec validate
plan-application-seam` and `--specs --all` (25) passed on it.

### Findings and dispositions

| # | Finding (seat) | Sev | Reproduction on `fd10789e` | Disposition | Landed |
|---|---|---|---|---|---|
| F1 | T3.4 is `[x]` while the D-16 rubric's owner-verdict column is PENDING — the substitution review-3 F6 already rejected (GPT F1 🔴; Grok F4 🟡; kimi's one correction) | 🔴 | `tasks.md` T3.4 `[x]` with "ticked at archive so the change can close"; `now-rubric-2026-09-16.md` has 8 `PENDING` cells | **Accept.** Split: **T3.4a** `[x]` the engineering receipt (`c27a34d5`), **T3.4b** `[ ]` the owner's five verdicts, blocking #10's D-16 DoD; the change is archived with that one task open and says so. The close-out's `Closes` line is made conditional (F12). The public status sentence and the pin move together (F2). Scoring is an owner act; no verdict was invented. | `e151885c` (tasks.md) |
| F2 | `docs/study-plans.md` "Plan-aware now" says the "would I do the primary?" judgement is "recorded per scenario in the project's rubric receipt" — the receipt holds primaries and rationales, the judgements are PENDING (GPT F3 🔴; Grok F1 🟡) | 🔴 | RED `test_study_plans_doc_uses_the_bounded_release_language` (`recorded per scenario` present, `pending` absent) | **Accept.** The sentence names the receipt path and says its owner-verdict column is still pending. The pin also fails the day the receipt is scored ("update the status sentence"), so the two cannot drift apart. D-16's bounded phrase is untouched. | RED `f0d01d95`, GREEN `e151885c` |
| F3 | Architect section: "Whichever door starts it, the architect works from a planning brief" — the brief is built only on the Web door (`purpose=planning`); "evaluates … at the start, middle, and end of every session run against it" reads as product behaviour when checkpoints never fire from session events; universal revise/delete conflicts with the CLI fallback (GPT F2 🔴; Grok F2, F3 🟡) | 🔴 | RED `test_architect_section_claims_the_brief_only_where_it_is_built`; `_dashboard.py`/`_start.py` build the brief on the Web start only; `studyloop plan interview` emits `{questions, seed}` | **Accept.** The brief is claimed on the Web door; a CLI/harness-started architect gathers the same material through `get_planning_interview` or `studyloop plan interview`; checkpoints are explicit and "StudyLoop never fires them from session events"; the two no-CLI-command operations are named with where they *can* be done. "It ships to every harness" now says the *definitions* ship and server attachment is per-harness (Grok F12). | RED `f0d01d95`, GREEN `e151885c` |
| F4 | `docs/agent-install.md` lists "revising an existing plan's **mission**, topics or milestones" among what needs the Web UI or MCP, but `update_study_plan`'s schema has no mission field (GPT F4 🔴) | 🔴 | RED `test_agent_install_doc_does_not_promise_mission_revision_over_mcp` — grounded in the live schema (`energy_floor, milestones, notes, plan_id, review_cadence_days, status, target_date, title, topics`) | **Accept, and it went further than the seat.** The row lists every schema property it revises and says the mission is not among them. **Reproducing it against the JS found a second overclaim no seat could see:** the Web UI's Study Plans view has no revise-fields control and no delete control (it creates, activates, ticks and previews/records; `PATCH`/`DELETE` exist only on the Web API). The doc had said those two operations need "the Web UI or an MCP-connected session"; it now says an MCP-connected session or the Web API, and that the mission changes only by editing the Markdown. The persona said the same wrong thing ("point at the Web UI") — F16. | RED `f0d01d95`, GREEN `e151885c` |
| F5 | "Plan-aware now" says "a plan with no other evidence still gets its next milestone suggested" — synthesis needs a READY plan whose next milestone is within the energy capability; an unready active plan is a warning and repair target; a fully checked plan is a completion action; "exactly what it was before plans existed" swallows the failed-read warning; `cli-reference.md` says `--json` "gains" fields (GPT F5 🟡) | 🟡 | RED `test_study_plans_doc_plan_aware_now_states_eligibility_and_optional_fields`; the delta requirement's rules 2, 5 and 8 | **Accept.** All four qualifications written; `--json` "adds … only when each is non-empty". | RED `f0d01d95`, GREEN `e151885c` |
| F6 | Installer says "9 plan tools" (ten are plan-named), does not say *lifecycle*, does not name `record_plan_learning`, and `_plan_capability_lines` sliced `NOT_AUTOMATIC[:-1]` so the sixth boundary was never printed and its test asserted only four (GPT F6 🟡; Grok F7 🔵, F6) | 🟡 | RED `test_installer_output_names_the_nine_tools_and_the_planning_purpose` (`lifecycle` absent), `test_installer_output_states_the_boundary_with_the_constant` over the whole tuple | **Accept.** "9 plan lifecycle tools (…) plus `record_plan_learning` … — whether a given harness definition registers that server is per-harness"; the boundary sentence is the whole tuple. Grok's "do not list `record_plan_learning` among the nine" holds — it is "plus". | RED `f0d01d95`, GREEN `e151885c` |
| F7 | The boundary tuple mixes kinds: "structure the manual form's brain dump" is an input-path fact, not an automation the product refuses; #7's "no autonomous recurring planning sessions" is missing; the single-session slot is not stated; the module docstring says the tuple proves the product "cannot claim more — or less — automation", which a tuple/prose equality does not prove (GPT F7 🟡; Grok F6 🔵) | 🟡 | RED `test_not_automatic_constant_is_well_formed` (`brain dump` in a phrase, no `schedule`), `test_study_plans_doc_states_the_brain_dump_limit_beside_the_boundary_list` | **Accept.** Sixth phrase is `schedule recurring planning sessions`; the brain dump and the Web door's subject-not-brain-dump are prose beside the list, labelled as door facts; the first bullet says a planning session takes the same single session slot; the docstring says the tuple is a shared statement and names the behavioural evidence. **Not a change to the recorded "Deliberately not automatic" decision:** the list is #7's out-of-scope automations, and it now tracks #7 more closely, not less. | RED `f0d01d95`, GREEN `e151885c` |
| F8 | Two additive specs disagree: `live-session-orchestration` "Session purpose" defaults `GET /api/session/state` to `focus` when the key is absent; `web-ui` "Plan with architect journey" requires a `mode == "plan-architect"` file with no purpose key to report `planning` (GPT F8 🔴) | 🔴 | Both sentences present in the deltas; `_dashboard.py::_purpose_of` implements the web-ui reading (explicit purpose wins → persisted planning mode → `focus`), as review 4 decided | **Accept.** The orchestration requirement now states the same precedence on both paths, "the topic string SHALL never determine the purpose", plus the CLI-started scenario. Also from GPT's spec cleanup: agent-adapters — a missing tool routes to the CLI fallback *where one exists*, the no-command steps are said to the learner; active-learning-decisions — the guidance entry's "every recorded assessment is refused" excludes database-only recording; cli-surface — "through one shared mapping and exit 1" (the `PlanNotReady` mapping prints several lines) and the negative-index message reconciled with the shared `InvalidMilestone` text. | `e151885c` |
| F9 | Learner-visible behaviours the specs bind and no public page states: partial recording on CLI/Web, `--done`/`--undone` retry-safe vs the no-flag toggle, the Web toggle request not replay-safe, active-but-unready hand edits, deletion confirmation differing per door (GPT F9 🟡) | 🟡 | RED `test_study_plans_doc_states_recording_retry_and_deletion_semantics` (no such section) | **Accept.** New "Recording, retries, and deletion" in `docs/study-plans.md`, each behaviour in the words the CLI/Web/MCP specs use — including that the Web UI has no delete control and its API's `DELETE` is the confirmation. | RED `f0d01d95`, GREEN `e151885c` |
| F10 | Verify registry: (1) the combined run is one file order, so the receipt cannot claim "both orders"; (2) two package-scoped runs are not a workspace-wide run; (3) the only real receipt was discarded, a final one is pending; release-consistency checks are not in the registry (GPT F10 🟡; Grok F9 💡 finds the registry complete) | 🟡 | `--list`: `integration-combined` = `test_mcp_stdio_smoke.py test_plan_journey_combined.py -m integration`, no reverse | **Accept (1):** `integration-combined-reverse` added TDD — RED `test_combined_run_is_verified_in_both_orders`, registry 28 → 29. **Accept (2) as wording:** the close-out says "both package suites pass independently"; owner item 12 (the order-dependent `agent-session-tools` test under the root config) stays visible. **(3):** the receipt is produced by the real run after this arbitration and committed in its own commit (Grok F12), and the two release-consistency commands are run separately and reported in the close-out. | RED `2911da1d`, GREEN `e151885c` |
| F11 | UAT `architect_launch` asserts the label before reload and `/api/session/state` after; "UAT proves the label survives reload" overstates it; the redacted summary would be less mistakable with `signoff_scope: "mechanics"` (GPT F11 🟡; Grok F10 💡) | 🟡 | `tests/acceptance/uat/test_plan_journeys.py` — the post-reload assertion is on `purpose`, the visible label is `test_console_is_labelled_planning_and_label_survives_reconnect` | **Accept the attribution, reject the field.** The close-out cites the dedicated browser test for the visible label and the UAT cell for persisted purpose after reload. The redacted JSON is a generated receipt; hand-adding a field the template does not emit would make it not a receipt (Grok: "do not invent a field the template will drop"), and its `arbitration_note` already says mechanics-only. | close-out (this commit) |
| F12 | The close-out admits incomplete acceptance (#10 D-16, #13 partly, #14 brain dump, #15 children) yet the PR body says `Closes #7…#15`; several rows overstate their evidence (GPT F12 🔴, F13 🟡, F14 🟡) | 🔴 | By reading the draft | **Accept.** `Closes` → `Related: #7–#15` with the closure keywords listed as the owner's choice per issue once items 1–2 are decided or re-scoped; rows corrected: #8 recovery now cites a test (**F15**), #9 idempotency qualified to explicit-state operations, #12 "refusal" → incomplete recording, #13 "deliberate" → interim until decided, #14 brain dump "unimplemented" and manual edit/checkpoint UI evidence narrowed, cancellation added to the parent's not-verified list, #15 rows say what is pending; branches/worktrees moved out of the cleanliness row; final `git status` recorded. | close-out (this commit) |
| F13 | Public inventory sweep omits `docs/mcp.md`, which the existing mcp-server requirement says documents the tool list (Grok F5 🟡) | 🟡 | `docs/mcp.md` exists on neither this branch nor `main` (`git cat-file -e main:docs/mcp.md` fails); the normative spec says "21 tools" and demands a Claude Desktop registration snippet the docs deliberately refuse to claim (`docs/agent-install.md` "Desktop applications") | **Accept.** Delta `mcp-server`: MODIFIED "studyloop-mcp registers a fixed set of study tools" (the 32 names: 23 + `PLAN_TOOL_NAMES`); REMOVED "docs/mcp.md documents studyloop-mcp and desktop registration"; ADDED "The studyloop-mcp inventory is published where the harness registration is" (`agents/mcp/README.md`, pinned by the contract test). The normative Purpose's stale `docs/mcp.md`/"7 tools" parenthetical was edited by hand (a path, not a merge) and is recorded here. The CLI's own `openspec archive` applies the three operations. | `e151885c` |
| F14 | README heading "studyloop-mcp (Session DB Tools)" is leftover taxonomy (GPT F15 🔵; Grok F8 🔵); normative chronology ("Phase-0", "issue #10, next requirement", "the only change in Phase 2", "the last requirement in this file", bare "design §n") will age (GPT F14) | 🔵 | `grep` over the deltas: eleven hits | **Accept.** "studyloop-mcp (Study tools)" with the legacy anchor kept; every chronology phrase rewritten as a requirement name or a qualified design reference; the T3.4 "nine scenarios" corrected to twelve; the Web journey's "8" was right. | `e151885c` |
| F15 | Close-out #8 "index refresh best-effort and recoverable" cites a module, not a test (GPT F12 row) | 🟡 | No test injected an index failure (`grep def test.*index` over the plan suites) | **Accept.** `test_failed_index_refresh_keeps_the_document_and_reindex_recovers_the_row` on the real seam: refresh raises → document saved and readable, no index row; `reindex()` writes it back, bytes untouched. Evidence for an existing behaviour, so no RED commit precedes it. | `e67f1767` |
| F16 | *Arbiter's finding while reproducing F4:* the architect persona's fallback table told the architect to "point at the Web UI" to revise fields and to delete — controls the Web UI does not have | 🟡 | RED `test_fallback_table_does_not_point_at_web_ui_controls_that_do_not_exist` fails on `fd10789e`'s persona | **Accept.** Canonical + three projections (byte-identical): "say so to the learner and stop — the Web UI has no control for those steps either"; Revise names `update_study_plan`'s fields (not the mission); Delete says no Web UI control, `confirmed=True` after the learner's yes. Manifest hashes regenerated for the two tracked projections, dates moved only where a hash moved; `.secrets.baseline` moved for those two digests only. | RED `2911da1d`, GREEN `e151885c` |

### Rejected, with reasons

- **GPT F1's pin** "a permanent public-doc test requiring a dated task checkbox": not added — `tasks.md` moves to the
  archive and a test over it would break on the move; the checkbox's honesty is this arbitration's and the close-out's.
- **GPT F11 / Grok F10** `signoff_scope` / `graded: false` in the redacted UAT JSON: rejected as above — a receipt is
  written by its runner; the prose was narrowed instead.
- **GPT F12** "A subprocess's inability to receive a monkeypatch is a test-method limitation, not proof that failure-path
  wire testing is impossible": agreed as a statement; the close-out now says "not exercised over stdio here", not
  "impossible". No fault-injecting stdio test was written — it would need a product-side fault hook, a change the docs
  review does not authorise.
- **GPT F7** "make the recurrence exclusion a contract pin": landed as the constant's sixth phrase, which the contract
  test already pins in both the doc and the installer — no separate pin.
- **GPT F10 (2)** "resolve the workspace-wide run or formally identify a package-scoped boundary": the registry keeps
  the two package runs (Grok F9: the stronger form given owner item 12); the decision is the owner's and stays listed.
- **GPT F14** "the install guide's unlinked 'open item in the … close-out' should become a stable link": the close-out
  lives under `docs/architecture/`, which `mkdocs` excludes (`exclude_docs`), so a relative link would fail
  `--strict`; the path is named in prose.
- **Grok F11** "checkpoint labels `on-track` / `at-risk` / `stalled` / `complete` are not established by the brief":
  they are the verdict vocabulary of `planning/evaluation.py` (`verdict: str = "on-track"`, `"at-risk"`, `"stalled"`);
  pre-existing behaviour outside this change, left as written.
- **Grok F12** "`visualReview: pending` is the skill's contract, not an unfinished product claim": agreed, nothing to do.
- **Grok F5's alternative** "add `docs/mcp.md` to `_PUBLIC_PLAN_PAGES`": the file does not exist; the requirement was
  retired instead of a page invented to satisfy it.
- **Nothing in this review contradicted a recorded decision.** D-16's bounded phrase stays on every page; the
  "Deliberately not automatic" list still equals `NOT_AUTOMATIC` and now matches #7's out-of-scope list more closely;
  the Kiro/Claude header decision was not taken (owner item 1); no scenario was added to a code contract.

### Verification after fixes

- `test_docs_plan_integration_contract.py` **25 passed** (was 11 failed / 14 passed on `f0d01d95`);
  `test_plan_architect_persona.py` 17; `test_verify_plan_integration_script.py` 22; `test_plan_application.py` 60;
  `test_install_agent_contracts.py`, `test_session_start_purpose.py`, `test_docs_harness_contract.py` green.
- `openspec validate plan-application-seam` → valid; `openspec validate --specs --all --no-interactive` → 25 passed.
- ruff check/format clean on every changed Python file; pyright 0 errors; pre-commit (ruff, ruff-format,
  detect-secrets, bandit, trufflehog, pyright) passed on `2911da1d`, `e151885c`, `e67f1767`. The end-of-file fixer
  rewrote the normative `mcp-server/spec.md` (a missing final newline, pre-existing) on the first GREEN attempt; the
  commit was re-created with the fixed file, not amended.
- The full-suite, integration, browser, JS, mkdocs and release-consistency results are the verify receipt's
  (`receipts/verify-<sha>.json`, run on the tree after this arbitration) and the close-out's final section.

### Process findings

1. **A docs review needs the UI in the brief, not only the docs.** Three seats and the Phase-6 agent all read "the
   Web UI" as able to revise and delete because the API can; one look at `plans-panel.js` showed neither control
   exists. Both the install doc and the *reviewed* persona carried the error since Phase 4. Future docs briefs should
   include the surface's control inventory (the `data-testid`s, or the JS `fetch` list) beside the prose.
2. **The brief digest did not match the committed brief.** Commit the brief before the run, or record the digest of
   the committed file in the manifest after; either way the receipt should be reproducible from the tree.
3. **`openspec archive` runs with one task open.** T3.4b is the owner's and the archive cannot wait for the morning
   without leaving the specs unsynchronized; the archive is done with the warning acknowledged and this file, the
   close-out and the archived `tasks.md` all say so.

### Addendum (after the receipt and the archive)

- **GPT F13 was more right than the F12 row records.** Both `world` fixtures (the #14 browser module and the UAT
  plan-journeys module) were `tempfile.mkdtemp` with no cleanup step; thirty-nine of their directories had
  accumulated in `$TMPDIR`. Both now remove their world in a `finally` (a module run leaves the count unchanged) and
  the thirty-nine were removed by hand, with the e2e server logs. Recorded in the close-out's final section.
- **The first real receipt failed for two environmental reasons and is kept** (`receipts/verify-fff69c65.json`,
  27/29; `69740be5`): the browser module lost one test to a 20 s start-POST timeout caused by the web app's
  background query-encoder warm under machine load ≈ 7.5 (A/B: 5/5 module runs fail with the warm on, 3/3 pass
  with `STUDYLOOP_RETRIEVAL_MODE=lexical` in the fixture's isolated child — now the fixture's setting), and the
  studyloop full suite was 5042 passed / 0 failed with exit 1 because the C8/R-49d guard saw another agent's
  `log_topic` write to the real `~/.config/studyloop/session-topics.md` mid-run. The re-run on the fixed tree is
  `receipts/verify-69740be5.json`, **29/29, exit 0** (`8c4ece48`). The warm's ability to stall request handling is
  listed for the owner as a product follow-on; it is not a plan-integration defect.
- **Archived at `7f836f50`:** `openspec archive plan-application-seam --yes`, +28 / ~1 / −1 requirements into the six
  normative specs; `openspec validate --specs --all` 24 passed; `just release-consistency-shipped` passes. T3.4b
  travelled into the archive open, as this arbitration said it would.

## Gate decision

**Phase 6 (#15) with the review-5 corrections F1–F16 is ACCEPTED for archive and for the owner's close-out, with one
open owner task carried into the archive (T3.4b, the D-16 verdicts) and the close-out's closure keywords made
conditional on it.** The two ACCEPT-WITH-CORRECTIONS seats' corrections are all landed; the REJECT seat's five 🔴 are
each landed (F1, F3, F4, F8, F12 above) and its remaining ask — the human verdicts — is the owner's by D-16's own
wording, which the arbiter cannot supply. Next: the verification receipt on this tree, `openspec archive
plan-application-seam`, the close-out refreshed with the resulting shas.

## Still open for the owner

1. **T3.4b — score the D-16 rubric** (`receipts/now-rubric-2026-09-16.md`): five yes/no verdicts, one line each, the
   tree sha; re-read row 3 against `64dc09f7`. A `no` on rows 1–4 is a council finding. Until then #10 is not done and
   the PR body says `Related`, not `Closes`.
2. **Kiro/Claude architect headers** (review 4): keep the two harness-launched architects CLI-limited or grant them the
   `studyloop` server and the plan tools. The install doc's disclosure is the contract meanwhile.
3. **Closure eligibility for #7/#13/#14/#15** (GPT F12): satisfy or explicitly re-scope — the brain-dump handoff (#14),
   the live-model protocol evidence, the missing cancellation browser test — before turning `Related` into `Closes`.
4. **Deviation 12**, **review-3 F2**, the **parser `)` bug**, **`_evidence_command` quoting** — unchanged, listed in the
   close-out.
5. **Unrelated local branches, again not touched:** `feat/clean-start` and `feat/harness-tier-promotion` (worktree
   `../studyloop-wt/harness-tier`, clean, 10 unmerged commits) carry commits that exist nowhere else; deleting either
   destroys work, so neither was removed unattended. No Phase-6 branch or worktree was created.

GATE: ACCEPT
