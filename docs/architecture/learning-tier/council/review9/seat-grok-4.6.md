I'll inspect the tree and the cited tests before judging N1, the trigger table, and decision 2. I'll start from the commits and the files the brief names.I'll pull the GREEN tool, the ownership bind, and the RED/GREEN tests next so N1 is judged from the code, not the brief.The bind path and the four inventory pins are next — those decide whether N1 is the right fix or a workaround.I have enough of the storage layer. Next I'll check whether the protocol is actually projected, whether any RED is vacuous, and what S1-SIM still has to prove.The protocol is referenced, not inlined. I'll confirm the remaining harness files and the TDD commits before writing findings.I have the tree. Next I'll pin a few remaining claims (N1 alternatives, inventory, TDD order) and then write the findings.I have the facts. One more pass on N1 alternatives and the trigger-table consent column, then the verdict. Let me also check a few more details that might be findings.I have enough. Checking two last details that could flip a finding: whether `observation.source_session_id` is a real alternative, and whether the Kiro JSON `tools` surface still exposes writers without naming them.Last check: whether the RED commit actually failed for the stated reasons, and whether Claude's `tools:` line is instruction-only as claimed.I have the evidence. Writing the review.The RED/GREEN split and N1 correction are documented. Checking one last possible hole: whether `record_teachback` actually upserts `study_progress` (so tomorrow's recommendation can move) and whether the protocol's consent column is enforced anywhere but prose.I have the tree, the tests, and the bind layer. Writing the review.# Review 9 — `feat/learning-tier-fed` @ `3c175f78`

## Findings

### 🔴 must fix before merge

None that block the pipe-open claim on the code that is here. The two 🔴-shaped holes are S1-SIM gates, not merge gates for this tree — listed under (e).

### 🟡 should fix

- 🟡 `packages/studyloop/src/studyloop/mcp/tools.py:910-918` — `record_teachback` swallows `records.bind` `ScopeError` / `IntegrityError` into the same `ToolError("…database is unavailable")` the no-connection path uses. A scope-misconfigured write and a missing DB are different failures; the CLI's `False` collapse is inherited, but the MCP surface is the one a stranger's mentor will see. Split the message (or let `ScopeError` through) so S1-SIM can tell "DB down" from "scope rejected the bind".
- 🟡 `packages/studyloop/tests/test_docs_harness_tier_contract.py:180-186` + `test_adapter_parity.py:111-118` — `TestRecordingProtocol.DEFINITIONS` lists five files and omits Grok; `MENTOR_DEFINITIONS` maps `"grok"` onto `agents/codex/AGENTS.md`. That is correct *today* (`adapters/grok.py` projects the Codex file) but the contract test does not pin the adapter projection. A later `agents/grok/` split would keep the five-file test green while the sixth definition silently dropped the protocol. Add an assertion that `adapters/grok.py` still writes `AGENTS.md` from the Codex source (or include Grok in `DEFINITIONS` via the adapter).
- 🟡 `agents/shared/recording-protocol.md` trigger table, `consent:` column — the four values (`learner_agreed` / `learner_stated` / `learner_confirmed`) are documentation, not a tool argument and not a test. That is the right signal (the learner's words, never a transcript inference) **and** it is unenforced. The tool will happily record scores the learner never agreed to if the model calls it. Acceptable under decision 2 (prompt-per-call, no new grants) only if S1-SIM scripts a refused-consent turn on every harness and asserts **zero** rows. Not a merge blocker; it is the claim-blocker for "pipe open".
- 🟡 `packages/studyloop/src/studyloop/mcp/tools.py:910` + `history/teachback.py:155-157` — `study_session_id` is read from session state and returned, then discarded. `record_teachback` still upserts `study_progress` (`history/teachback.py:196-204`), so tomorrow's recommendation *can* move — the MVP defect is addressed at the card level. What is *not* linked is "this teach-back happened in study session X". The observation row `record_teachback` writes (`history/teachback.py:187-194`) currently carries no `source_session_id`. If session-level provenance matters for the noticing episode (decision 3), thread `study_session_id` into `observations.record(..., source_session_id=...)` — that column is the storage layer's supported study-session link, and it does not go through `records.bind`. See N1 below.
- 🟡 `packages/studyloop/tests/test_mcp_teachback.py:102-123` — validation cases miss empty `concept` / empty `topic` (both `NOT NULL` in the schema, both accepted as `""` by the tool). CLI has the same hole. Not the defect this item exists to fix; one parametrized case would stop a silent empty-concept row from counting as a fed tier.

### 🔵 style

- 🔵 `packages/studyloop/src/studyloop/mcp/tools.py:900-902` — three imports inside the tool body. Matches neighbouring writers; fine. If anything moves, keep `coerce_scores` / `coerce_review_type` imported the same way the CLI now does (from `history.teachback`), which this already does.
- 🔵 `packages/studyloop/tests/test_mcp_plan_tools.py:937` — test renamed `thirty_two` → `thirty_three` and the three sibling pins (`test_mcp_stdio_smoke.py:48`, `scripts/verify/plan_integration.py:67`, `test_verify_plan_integration_script.py:467`) moved in the same commit (`3c175f78`). Inventory pin discipline is correct.
- 🔵 `agents/kiro/study-mentor/persona.md:32` — the old `uv run tutor-checkpoint` line is gone; the CLI block now shows `studyloop teachback` as the human path. Good. Residual `tutor-checkpoint` still appears in OpenCode's `permission:` bash allow-list (`agents/opencode/study-mentor.md`, S1-0 receipt §2) — that is the recorded wildcard, not a routing instruction. Leave it.

### 💡 learning

- 💡 Finding N1 is the interesting one. The ownership layer (`agent_session_tools.context.records.bind`) treats `session_id` as a *native harness session* that must exist in `sessions` and be visible in scope. Study sessions are a different id space; the only tables allowed to carry `study_session_id` are `parked_topics` and `study_notes`. Stuffing a study id into `teach_back_scores.session_id` cannot work without a schema/ownership change that this item is not licensed to make. Reporting-without-storing is the correct *storage* resolution. The missed opportunity is the observation: `observations.record` already has `source_session_id` and does not go through `bind`. GREEN should have passed the live study id there. That is a one-line addition plus one assert in `test_the_study_session_is_reported_not_stored_as_the_rows_session_id`. It does not change the row's `session_id` (still `NULL`, still owned by scope, still matches the CLI). Do it on this branch if the noticing episode needs "which session did this teach-back belong to"; otherwise file it as the first S1-SIM observation and do not block merge.
- 💡 `test_writer_isolation.py` passed on first run and is honestly labelled a guard. That is the right TDD call. The child-process `HOME`/`XDG_*` decoy is the test that would have caught the 2026-09-05 home-directory leak; keep it.

---

## Judgements the brief asked for

### (a) Trigger table complete? Consent column the right signal?

Complete for `W_auto`. Four triggers, four writers, bijection pinned by `test_every_trigger_names_a_w_auto_writer_and_every_writer_has_a_trigger`. No SRS mutator is named (`test_no_trigger_names_an_srs_mutator`). The `when:` lines match the standing rule (learner's agreement is the signal; low-energy blank is never scored).

Consent column is the right *vocabulary* (`learner_agreed` / `learner_stated` / `learner_confirmed` — never `model_inferred`). It is not a runtime check. That is acceptable as instruction-parity (decision 2) and insufficient as a guarantee. S1-SIM must script the refusal path.

One gap in the table itself, not a 🔴: `required_ids` for `teach_back_agreed` is `[concept, topic, scores, review_type]` and does not mention that `session_id` is bound from state, not the caller. The tool docstring says this; the table does not. Fine — the table is for the model, the docstring is for the caller.

### (b) Decision 2 honoured?

Yes, on every harness this repo can express.

| Harness | Names | Grants |
|---|---|---|
| Kiro | persona.md:32 and :79-81 name all four; JSON `allowedTools` still only `@studyloop/log_topic` | `test_kiro_gains_no_pre_approval` pins the set intersection |
| Claude | `tools:` line names the four `mcp__studyloop__*` writers plus the five readers | `test_claude_settings_grant_nothing` — no `permissions` block |
| OpenCode | protocol See-line names them | `test_opencode_permission_block_is_exactly_as_recorded` — wildcard unchanged |
| Codex / pi / Grok | shared See-line on `AGENTS.md` (Grok via projection) | no grant grammar in repo |

Claude's `tools:` addition is naming, not approval — the S1-0 receipt is explicit that an unnamed MCP tool is unreachable on that sub-agent, so naming is what makes the pipe exist at all. That is instruction, and it is required. No new pre-approval.

Kiro's existing `log_topic` pre-approval is untouched. The one recorded asymmetry stays one.

### (c) N1 — reporting-without-storing, or bind another way?

**Reporting-without-storing is the right resolution for `teach_back_scores.session_id`.**

Evidence:

- `records.bind(..., session_id=...)` requires a row in `sessions` visible in scope; otherwise `_owner()` raises `ScopeError("Source session is unavailable in the configured scope")`.
- Study-session links are permitted only for `parked_topics` and `study_notes`.
- The CLI already writes `session_id=NULL` and owns the row by scope. MCP matching the CLI is the S1-0 contract ("land through the same function").
- The RED as first written (`f439ab84` docstring still on the GREEN test) assumed the live study id would land in the column. GREEN recorded the correction in the test name and docstring (`test_the_study_session_is_reported_not_stored_as_the_rows_session_id`). That is the TDD rule honoured: a RED expectation corrected at GREEN is recorded, not erased.

**The alternative that the storage layer *does* support**, and that GREEN should have taken as a sidecar, not a replacement:

```
observations.record(..., source_session_id=study_session_id)
```

`history/teachback.py:187-194` already writes an observation on every successful teach-back. `source_session_id` is the column the ownership layer uses for study-session provenance without going through `bind`. Passing the live id there:

- does not change `teach_back_scores.session_id` (stays `NULL`, stays legal);
- does not require a schema change;
- gives the noticing episode (decision 3) a join from teach-back → study session;
- is what the brief's "e.g. the observation's `source_session_id`" is pointing at.

Do **not** invent a `teach_back_scores.study_session_id` column on this item. Do **not** pass the study id as `session_id` to `record_teachback` — that is the failure the RED discovered. Report in the reply (done) + optionally stamp the observation (not done, 🟡 above). The test as written is the correct assertion for the column it checks.

### (d) Vacuous REDs / over-claiming GREENs?

TDD order is clean:

- `f439ab84` S1-RED — 22 failed, 0 passed. Failures are the ones the plan named: tool absent, writers unnamed, protocol absent, `tutor-checkpoint` still on the Kiro persona, inventory still 32.
- `7354ea3a` S1-GREEN (tool) — N1 correction recorded in the test, not erased.
- `0a22aabe` S1-GREEN (definitions) — protocol projected, persona repointed.
- `3c175f78` inventory 32 → 33 in all four pins.

Not vacuous:

- `test_the_caller_cannot_supply_a_session_id` — inspects the signature. Real constraint.
- `test_a_valid_call_lands_exactly_one_row_through_the_real_schema` — hits the migrated CHECK, not a hand-rolled table.
- `test_a_repeated_call_is_two_rows_because_teachbacks_are_events` — pins the "events, not state" rule.
- `test_no_connection_is_a_tool_error_not_a_silent_success` — the silent-success path is the failure mode the receipt forbids.
- `test_kiro_gains_no_pre_approval` / `test_claude_settings_grant_nothing` / `test_opencode_permission_block_is_exactly_as_recorded` — these are the decision-2 pins. They fail if anyone "helpfully" pre-approves.

Slightly soft, not vacuous:

- `test_every_mentor_definition_names_each_w_auto_writer` is a `\bword\b` search. A mention in a "do not call these" sentence would pass. The companion `test_claude_mentor_tools_line_names_each_writer` is the one that actually makes Claude able to call them. Acceptable: the protocol See-line is the named instruction, and the word-search is the cheap pin that the See-line exists on every file.
- `test_writer_isolation.py` is a guard and says so. It does not over-claim RED.

GREEN does not over-claim "pipe open on six harnesses". The commits claim: tool exists, validates as CLI, lands a row, names are on every definition, no new grants, inventory is 33. That is what the tests prove. The stranger-in-hands claim is S1-SIM's job.

### (e) What S1-SIM must add before "pipe open on {passed}; plumbing proven for all six definitions"

The unit suite proves the tool and the instruction. It does not prove a mentor on a harness will fire the trigger. S1-SIM (scripted learner, owner-gated, six harnesses) must add, per harness that passes:

1. **Happy path, `teach_back_agreed`.** Script: mentor proposes five scores → learner says "yes" → exactly one `record_teachback` call → one row in `teach_back_scores` with those scores → reply contains `recorded: true` and a `study_session_id` that matches the live session (or `null` if the harness has no session state) → mentor's next line matches the "Recorded: …" shape. This is the defect. If this fails on a harness, that harness is not in `{passed}`.
2. **Refusal path.** Script: mentor proposes scores → learner says "no" / low-energy blank → **zero** `record_teachback` calls, **zero** new rows. This is the consent column made measurable. A harness that records on refusal is not in `{passed}`.
3. **The other three triggers, one each.** `stuck_two_rounds` → `log_struggle`; `session_end_concepts` → `log_topic` (one call per concept, status the learner confirmed); `plan_wind_down` → `record_plan_learning` only when a plan is active and the learner agrees. Absence of a plan must produce zero `record_plan_learning` calls.
4. **No-trigger silence.** A mid-session turn that matches nothing writes nothing. Pin the row counts before/after.
5. **Duplicate replay.** Two agreed teach-backs on the same concept → two rows. Events, not upserts.
6. **Decision-2 live check, not just file pins.** On Kiro, `record_teachback` / `log_struggle` / `record_plan_learning` must prompt (only `log_topic` is pre-approved). On Claude, the four writers must be *callable* (named on `tools:`) and must prompt (no `permissions` block). On OpenCode, the MCP call prompts at harness default; the bash wildcard is unchanged and must not be the path the mentor takes — if the scripted session shells out to `studyloop teachback` instead of calling the MCP tool, that harness fails the protocol even if a row lands. Codex / pi / Grok: harness-side approval, record whatever the harness does, do not change it.
7. **Claude reachability.** Before this tree the sub-agent could not see any `mcp__studyloop__*` tool. S1-SIM on Claude is the first time that `tools:` line is proven live. If Claude's runtime ignores a `tools:` line that long, the unit test is green and the pipe is closed. This is the highest-risk harness.
8. **Grok projection.** Confirm the session dir's `AGENTS.md` is the Codex file *and* that the running Grok mentor names the four writers. The unit suite never launches Grok.
9. **N1 live.** After a successful write, `teach_back_scores.session_id IS NULL` and the tool reply's `study_session_id` equals the live study session (or `null`). If anyone "fixes" N1 by stuffing the study id into `session_id`, the write will `ScopeError` and the tool will say "not recorded" — that is a SIM-fail, and it is how we find out someone re-broke it.
10. **Isolation under a real harness, not just the child-process guard.** One SIM run with `HOME` pointed at a decoy. If a harness adapter ignores `STUDYLOOP_*` and writes through `~`, that is the 2026-09-05 bug back.

Do **not** claim "plumbing proven for all six definitions" until (1), (2), (6) and (7) have an owner-gated pass on each of the six. (3), (4), (5), (8), (9), (10) can be a second SIM pass; they are not the MVP defect, but they are what stops the next silent failure.

UNVERIFIED (not run on this seat): the 7340-pass figure, the four inventory pins going green at `3c175f78`, and `test_concatenated_remote_dump_with_existing_archive` still failing identically to `main`. Coordinator to confirm against the tree.

---

## Verdict

**ACCEPT**

The MVP blocker is closed in code: there is an MCP `record_teachback`, it shares the CLI validator, it lands a row the same way the CLI does, every harness definition names the four writers and points at one protocol, and no harness gained a pre-approval. TDD order holds. Decision 2 holds. N1 is the correct storage resolution; the observation-`source_session_id` sidecar is a should-fix, not a must-fix.

Do not merge-gate on S1-SIM — decision 3 already scheduled the noticing episode as observation, not gate — but do not let anyone write "pipe open on six" until the SIM list above has owner ticks. The 🟡s can land as follow-up commits on this branch or the first 0.5.x patch; none of them re-closes the writer.
