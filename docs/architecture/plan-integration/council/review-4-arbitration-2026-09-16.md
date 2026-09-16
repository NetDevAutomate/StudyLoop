# Arbitration — council review 4 (Phase 4 code: #12 three MCP tools + fold ∥ #13b architect persona)

**Date:** 2026-09-16 · **Arbiter:** coordinating agent (unattended) · **Reviewed tree:** `fix/plan-integration-bugs`
@ `b2f37fa4` — the merge of `feat/p4-mcp12` and `feat/p4-13b` onto the accepted Phase-3 base `205819c7`. Seats ran
against `brief-review4-2026-09-16.md` (sha256 `a8014b53…`, committed `e6d3b7d7`; `review4/manifest.json`).
**Fixes landed at:** `f30ee11b..cf78be40` (findings). Phase 3 was accepted in `review-3-arbitration-2026-09-16.md`.

**Brief size, recorded:** 129.5 KB (target ~120 KB). The `.secrets.baseline` diff was described in prose rather than
embedded and the manifest's content digests carry the repo's allowlist pragma: the pre-commit detector reads a
digest as a credential otherwise, and the first commit attempt was refused on exactly that. All three seats consumed
the brief in one run (prompt 33–36k tokens, `finish_reason=stop`); no re-run manifest exists.

## Seats and verdicts

| Seat | Verdict | Receipt |
|---|---|---|
| `openai.gpt-6-astra` | **ACCEPT-WITH-CORRECTIONS** — #12 ACCEPT; #13b with corrections: one 🟡 (F1 the inherited brief budget and once-before-first-prompt test), six 🔵 (F2 `STUDY_ID`/shell assumptions, F3 install-doc parity, F4 test assertions overstate, F5 unbounded repo-root walk, F6 inventory arithmetic, F7 D-6 wording), one 💡 | `review4/seat-openai.gpt-6-astra.md` (6.8k tokens) |
| `grok-4.6` | **ACCEPT** — no 🔴/🟡; seven 🔵 (fold prefix as a consumer hazard, duplicated count constant, table signature drift, `STUDY_ID` hole, Revise row on active husks, retire `_LANDING_WITH_12`, install doc overclaims); the brief cap and the Kiro/Claude wiring named as Phase-5/6 work | `review4/seat-grok-4.6.md` (17.2k tokens) |
| `qwen3-coder` | ACCEPT — no 🔴; three 🟡 (two rest on misreadings, see rejections; the third is the `_LANDING_WITH_12` retirement), three 🔵 | `review4/seat-qwen3-coder.md` (2.1k tokens) |

### Method

Every 🔴/🟡 was **reproduced before acceptance** — a probe script on `b2f37fa4`, then a RED test seen failing and
committed before the fix — or rejected with the reason below. Two seats naming one defect are one finding group; one
RED commit + one GREEN commit per group (test-only pins are one commit). Protected files stayed byte-identical
(verified below), the golden's sha256 did not move, the architecture guard passed after every commit, and the
production inventory is still exactly 32.

### Findings and dispositions

| # | Finding (seat) | Sev | Reproduction on `b2f37fa4` | Disposition | Landed |
|---|---|---|---|---|---|
| F1 | Review 3 handed #13b "cap or summarise `### Evidence`" and "a test that the brief is sent once before the user's first prompt"; #13b shipped neither — its file set could not reach `_start.py` (GPT 🟡; Grok: do it in Phase 5) | 🟡 | **Probe:** `_render_planning_brief` is unbounded on all three axes — 300 plans alone render **40 KB**, 500 rows per key 178 KB, a 5 000-char value ×8 rows 241 KB, all three together **15.6 MB**. The real seed is bounded to 8 rows per key by the seam's `limit=8`, but the renderer took whatever it was given, and the number of existing plans and every value's length were never bounded. | **Accept, landed now.** A review-3 hazard with a named owner fell between file sets — the process gap review 3 itself recorded — so the arbiter lands it rather than re-address it to #14. `_render_planning_brief` owns a delivery budget: ≤ 10 rows per evidence key (and ≤ 10 notes), ≤ 20 existing plans, ≤ 120 chars per quoted value, an explicit `… and N more` marker wherever it cut (the plans marker names `list_study_plans`). `_quoted()` clips *after* `_one_line()`, so a value long enough to cut still cannot open a heading (F4 of review 3). Within the budget the rendering is **byte-identical** (verified against the pre-cap renderer). `_resolve_persona`'s shape is unchanged. Worst probe now 14.5 KB. "Sent once before the first prompt": pinned as far as the server can prove it — both transports ship exactly one `## Planning brief`/`### Interview` inside the persona (ACP: `persona_text`, the invisible first turn; PTY: the adapter's file), never a second copy in `topic` or as `previous_notes`; the frontend's ordering of that first turn is existing ACP behaviour under `test_web_acp_chat_ui.py`. GPT's `test_focus_launch_does_not_receive_planning_brief` already exists (`test_default_purpose_is_focus_and_unchanged`). | RED `f30ee11b` (3 failed / 3 pins), GREEN `8f9b6011` |
| F2 | The persona's `study_id=STUDY_ID` is unexplained pseudo-code — a Web PTY/ACP architect is not told where the id comes from and may pass the literal; the shell steps (`studyloop resume/review`, `studyloop session end`) are unconditional although an ACP agent has no shell (GPT 🔵; Grok 🔵; qwen ❌/🔵) | 🔵 | By reading: the Session Start section contains neither `study_session_id` nor a rule for the empty default; the wind-down names no MCP path | **Accept.** Session Start: `STUDY_ID` is the live session's `study_session_id` in the state file the persona already lists under "Session Files for This Run"; unreadable → `study_id` stays at its empty default, never the literal, never invented; steps 1 and 3 are skipped over ACP. Wind-down step 6 names `end_session` (the registered MCP tool) for an ACP architect and is honest that it takes no notes, so the summary must already be in the learning record. GPT's "make shell-only steps conditional on shell availability" is landed as those two sentences, not as a persona-wide rewrite. | RED `5ff48211`, GREEN `cf78be40` |
| F3 | `docs/agent-install.md` says an agent without MCP "can do the same work" at a shell, while the persona is honest that the CLI cannot revise fields or delete; it does not disclose that the Kiro/Claude harness-launched definitions do not attach the server (GPT 🔵; Grok "the install doc overclaims"; qwen 🔵) | 🔵 | By reading | **Accept.** "most of this work"; the two operations with no CLI command are named with their doors (Web UI or an MCP-connected session); the Kiro (`no mcpServers`) and Claude Code (`tools: Read, Write, Grep, Bash`) boundary is disclosed with **T6.1** as the owner; a Web-launched architect is described as carrying the same persona and using whichever servers its agent process is connected to (only the OpenCode adapter writes an MCP config into the session dir — `_opencode_mcp`; Kiro and Claude read their global registration). Pinned by `test_install_docs_disclose_architect_fallback_limits`. | RED `5ff48211`, GREEN `cf78be40` |
| F4a | `test_the_nine_are_the_registry_plus_exactly_what_12_lands` tolerated the three #12 names being absent (`_LANDING_WITH_12`) — right before the merge, vacuous after it (GPT 🔵; Grok 🔵; qwen 🟡 — unanimous) | 🔵 | By reading: `unregistered == ∅` after the merge, so the `<=` never bites | **Accept.** Replaced by `test_all_nine_persona_tools_are_registered_after_phase_four` (exact set); `_LANDING_WITH_12` retired. | `5e085f0a` |
| F4b | The in-process inventory pin is called the stdio pin's twin but asserts neither `CORE_TOOLS` nor uniqueness; `_registry()` is a dict, so a duplicate registration overwrites its key silently and the size alone cannot show one (GPT 🔵; Grok 🔵) | 🔵 | By reading | **Accept.** The pin asserts `CORE_TOOLS` and that every tool sits under its own name (`tool.name == key` for all 32). `PRODUCTION_TOOL_COUNT` stays duplicated in the two test files (GPT: one test module should not import another for an integer; the tests dir has no package). | `5e085f0a` |
| F4c | Byte-equal document bytes prove unchanged state, not an un-invoked writer; an empty log after a preview is weaker than existing rows surviving one; only the database sink's failure was exercised (GPT 🔵) | 🔵 | By reading | **Accept as pins** on the real seam: `test_milestone_retry_does_not_call_save_plan` (`store.save_plan` is a tripwire after the first mutation), `test_evaluate_preview_preserves_existing_checkpoint_rows`, `test_evaluate_document_failure_reports_saved_database_and_failed_document` (`save_plan` raising → `db_write: saved`, `document_write: failed`, `recording_complete: false`, the seam's document warning, row present, document byte-identical). All three pass on the tree. GPT's nested-container independence: the view contract is `to_json_dict()`'s fresh containers, pinned in review 1; not extended. | `aa463738` |
| F5 | The module-level repo-root walk (`while not marker.exists(): root = root.parent`) never terminates outside a checkout — `Path("/").parent` is `Path("/")` (GPT 🔵) | 🔵 | **Probe:** from `/tmp/…/nowhere/deeper`, 100 000 iterations at `/` without terminating | **Accept.** `_find_repo_root` walks `start.parents` (finite) and raises `FileNotFoundError` naming the marker; the same walk in `test_session_start_purpose.py` (Phase 3) is bounded the same way. Pinned by `test_find_agent_repo_root_fails_when_marker_is_absent`. | `5e085f0a` |
| F6 | Both inventory comments read "23 plus the nine less `record_plan_learning`", which is 31; `record_plan_learning` is not one of the nine being added (GPT 🔵) | 🔵 | By reading — true | **Accept.** Reworded in both test files: 23 originals (`record_plan_learning` among them) + 9 = 32. The `tools.py` comment and the mcp-server spec sentence saying "the other eight plan tools" now say the nine of design §4 (the fold's caller is the tenth). | `5e085f0a` |
| F7 | D-6's literal wording ("import only `studyloop.planning.{application,views,errors,intents}`") vs the adapters' `from studyloop.planning import …` facade imports (GPT 💡) | 💡 | By reading | **Reject as a wording artefact of the brief.** Design §6 allows "`studyloop.planning` itself only for the re-exported view/intent/error names"; the guard (30 passed) encodes exactly that. No change. | — |
| F8 | The MCP table's signatures drift from the registered schemas: `create_study_plan` omits `plan_id=None`, `get_study_plan` omits `history_limit`, `record_plan_learning` omits `status="active"` (Grok 🔵; GPT "acceptable abbreviations") | 🔵 | **Probe:** a parser over the table rows vs `mcp._tool_manager._tools[name].parameters["properties"]` — three rows differ; `set_study_plan_status(plan_id, "active")` shows a literal where a parameter goes | **Accept, with a pin that ends the drift:** `test_mcp_table_signatures_match_the_registered_schemas` compares every row (and `record_plan_learning`'s prose signature) with the registered schema — exact set, or a strict subset when the row abbreviates with `…`. `set_study_plan_status` shows `(plan_id, status)` with `status="active"` moved into the prose column; the other transitions are named. `docs/agent-install.md`'s table already carried the full signatures. | RED `5ff48211`, GREEN `cf78be40` |
| F9 | The Revise row is silent on the F1 contract: every write to an active-but-unready document is refused, so the architect would hammer `update_study_plan` on a husk (Grok 🔵) | 🔵 | By reading | **Accept.** The row says: pause first (`set_study_plan_status(plan_id, "paused")`), repair, re-activate. Pinned. | RED `5ff48211`, GREEN `cf78be40` |
| F10 | "Do not create as `active` to skip the gate; the seam refuses it" teaches a blanket ban the seam does not enforce — `_persist_new` runs identity → conflict → readiness → create, so a *ready* document may be created active (GPT §3) | 🔵 | By reading `_persist_new` | **Accept.** "Creating as `active` does not skip the gate: the same readiness check applies at creation." Also: a step whose fallback table says "no command" is said to the learner and pointed at the Web UI, not worked around (GPT §3 missing-tool routing). Pinned. | RED `5ff48211`, GREEN `cf78be40` |
| F11 | Spec/doc details: the delete-result shorthand ``{"deleted": true, "plan_id"}`` is malformed; "`__cause__` chained" is not testable over stdio; the T4.2 report says "4 scenarios" for a three-scenario delta (GPT §3; Grok) | 🔵 | By reading | **Accept.** Shorthand fixed; the spec sentence now distinguishes the in-process adapter requirement (pinned by the delegation tests) from the stdio transport, which carries the prefixed text only; tasks.md T4.2 corrected to 3 with the correction noted. | `cf78be40` |
| F12 | The fold changed `record_plan_learning`'s `PlanNotReady` message from `plan is not ready to activate: <blockers>` to the `not_ready:`-prefixed form inside the three-tools commit (Grok 🔵 "a consumer branching on the unprefixed lead-in would silently miss"; GPT: requested by arbitration, reported, pinned before GREEN — not silent; qwen 💡) | 🔵 | `rg 'not ready to activate' agents/shared/*.md docs/` → no consumer parses the old string; `test_plan_record.py::TestMcpTool` and `test_mcp_plan_record_seam.py` match by substring and pass | **Accept as recorded, no change.** The fold was ordered by review 3 in the same commit after the RED pin; the prefix was already promised by `docs/agent-install.md`. The verification receipt (#15) fails if the `not_ready:` prefix is lost (below). | — |

### Rejected, with reasons

- **qwen 🟡 (1)** "`evaluate_study_plan`'s docstring claims a top-level `markdown` key that is really inside
  `evaluation.markdown`": a misreading — `AssessmentResult.to_json_dict()` carries `markdown` at the top level
  (views.py) and `test_evaluate_study_plan_calls_assess_never_apply` pins the six top-level keys.
- **qwen 🟡 (2)** "`_section`'s regex is unreliable across Markdown structures": vague; GPT and Grok both verified the
  closer (next `#`–`###` heading) is right for the `### CLI fallback` → `## Session Start Protocol` layout.
- **qwen 🔵 (4)** move `_plan_tool_error` above its first use: "append only" was the constraint (D-8); GPT and Grok
  accept the late binding as legal and readable enough. A later cleanup may lift it to module scope.
- **GPT F4(3)** `test_planning_purpose_resolves_to_plan_architect`: already pinned —
  `TestResolver::test_persona_mode_for_maps_planning_to_plan_architect_and_else_to_focus`.
- **GPT F1's proposed budget (8 KiB evidence / 16 KiB brief)**: the shape was adopted (bounded rows, bounded plans,
  bounded values, a marker), the numbers were not — a byte budget on the whole brief would silently vary with the
  interview text; per-list and per-value caps are deterministic and testable, and their worst case is bounded anyway.
- **GPT F4(1) "import one constant"** (Grok) — rejected in favour of GPT's own reading: duplication of an integer beats
  a cross-module import in a package-less tests directory.
- **qwen §4** `energy: "high"`, `agent: "study-plan.architect"` in the #14 request body: invented values; the body
  carries the picker's own `energy`/`agent`/`transport` (see hazards).

### Verification after fixes (`cf78be40`)

- Full suite: `uv run --group dev pytest packages/studyloop/tests -q -p no:cacheprovider -x` → **4987 passed, 4
  skipped**, exit 0 (6m01s; 785 deselected by the project's default markers — integration/e2e/live/acceptance/uat).
  Baseline at `b2f37fa4` was #12's own gate, 4949 passed.
- `test_mcp_plan_tools.py` 121 (was 118); `test_plan_architect_persona.py` 16 (was 9); `test_session_start_purpose.py`
  22 (was 16); `test_mcp_next_action.py` 10; guard `test_architecture_plan_seam.py` 30 passed;
  `test_mcp_stdio_smoke.py -m integration` 2 passed (inventory **32**, unique, the nine + `record_plan_learning` +
  `CORE_TOOLS`); `test_install_agent_contracts.py` green (the Kiro `no mcpServers` pin stands, deliberately — below).
- JS: `node --test packages/studyloop/tests/js/*.test.js` → **115 pass, 0 fail** (unchanged; no JS moved).
- `just lint` → ruff clean, 1028 files formatted; `just typecheck` → pyright 0 errors; `openspec validate
  plan-application-seam` → valid; `openspec validate --specs --all` → 25 passed; `mkdocs build --strict` exit 0.
- Protected files: `git diff 3a4f6b01 -- test_web_plans.py test_cli_plan.py test_planning_evaluation.py` → **0
  lines**; `git diff 0a20a796 -- test_learning_decision.py test_web_now.py test_recap_mastery_voice.py
  test_web_session_start_pty.py test_web_session_start_acp.py test_web_session_ws.py test_agent_launcher.py` → **0
  lines**. Golden `now_plan_no_active.json` sha256 `ec451ce8857c8a72e398e3054e3c060cd3b5b13ecb29e29cba3822dc192503c0`
  unchanged. `rg` invariants: 0 adapter imports of `planning.store|index|authoring|evaluation`; 0
  `build_canonical_persona("focus"` literals under `web/routes/session`.
- Projections: the three architect projections equal the canonical body byte for byte
  (`test_projected_personas_match_canonical` ×3); `agents/manifest.json` hashes regenerated for the two tracked
  projections (`claude/study-plan-architect.md` `34ae569da30c7d89`, `opencode/study-plan-architect.md`
  `bfb2709de375fa11`), dates moved only where the hash moved; `.secrets.baseline` moved for those two digests only.
- `mcp/tools.py`: one comment line replaced (`5e085f0a`); `git diff b2f37fa4 -- mcp/tools.py` → that line only, no code.
  `get_next_action` untouched (D-8).
- Pre-commit on every commit: ruff, ruff-format, detect-secrets, bandit, trufflehog, pyright — passed; the brief's
  first commit attempt was refused by detect-secrets on embedded content digests and re-created with them described
  in prose (no `--amend`); no secret detector fired on any code commit.

### Phase 5/6 hazards (endorsed from the seats, with the arbiter's decisions)

**#14 — the Web "Plan with architect" journey (T5.1/T5.2).** The Plans-view control initiates the **existing**
start flow — `sessionTimer.startSession()` in `js/components/session-timer.js`, which owns the POST, the 409
handling and the `study-session-start` event `liveAgentConsole` mounts on — with `purpose: "planning"`, `topic:
<the learner's subject or "">` (never omitted; the server resolves `""` to `"Study plan"`), and the picker's own
`energy`/`agent`/`transport`. The Today panel's `today-resume` window event is the precedent for a cross-view
hand-off; the Plans view dispatches one such event and never posts, never opens a socket, never registers a
`study-session-start` listener. The console label reads `purpose` from the `201` body on first paint and from
`GET /api/session/state` on reload (`liveAgentConsole._adoptLiveSession`). **Reconnect label for a CLI-started
architect — decided:** `studyloop plan architect` writes no `purpose`, but it does persist `"mode":
"plan-architect"` (`session/start.py`, `write_session_state`); `_dashboard.py` derives the missing `purpose` from
that persisted *persona mode* through the one resolver (`persona_mode_for("planning")`), never from the topic
string — the CLI writer is not edited (outside Phase 5's file set, and the fact is already there). A `mode:
"focus"` file with topic `"Study plan"` stays `focus`. RED tests named in `tasks.md` T5.1; the Playwright fixture
(`tests/_playwright_helpers.py`, marked `e2e`, real server + `STUDYLOOP_TEST_AGENT_CMD` fake agent) proves the
click → one POST → console, the label surviving a reload, one console / one WebSocket, the manual New Plan path,
the 409 with `reattach_url`, and no plan created; the persona file the PTY adapter writes proves the brief's
*structure* (`## Planning brief`, the three `###` sections, `## Tooling`) — never wording. The `node --test` layer
counts listeners and dispatches (one `study-session-start` per click; zero from the Plans view). The brief budget
(F1) is landed, so #14 ships ACP without the token bomb.

**#15 — verification receipt (design §8, T6.2) and T6.3.** `scripts/verify/plan_integration.py` records, per
check, the command, exit status and the measured value, and **fails on a failed required check**: the real stdio
inventory (exactly 32 unique names; the nine; `record_plan_learning`; `CORE_TOOLS`; the list itself) with the
in-process twin as a supplement; `test_mcp_plan_tools.py`, `test_plan_architect_persona.py`, `test_mcp_next_action.py`,
`test_session_start_purpose.py` (the budget and the once-in-the-persona pins); the guard (30); the golden sha;
the ten protected-file diffs against their two bases (0 lines each); the two `rg` invariants (both import
spellings); the three projection equalities and the two manifest hashes; `record_plan_learning` on a `PlanNotReady`
still starting `not_ready:` (F12); the merged-tree full suite, `-m integration` stdio, an explicit `-m e2e` run of
the #14 browser module (deselected by default, so it must be named), JS, lint, typecheck, `openspec validate`,
`mkdocs --strict`. **T6.3:** one process, one isolated scope: `POST /api/session/start {purpose: "planning", topic:
""}` → `201`, `purpose == "planning"`, one `## Planning brief`, no plan on disk; then `get_planning_interview` and
`create_study_plan` through the same `FastMCP` registry, the draft visible through `GET /api/plans`, a preview
`evaluate_study_plan` with both sinks `not_requested`; reconnect keeps the label; the log holds no "event loop is
already running".

**The Kiro/Claude "architect takes the CLI fallback" owner item — decided: a documented boundary, owned by T6.1,
not a Phase-4 defect** (all three seats). `d96fb9ba` sealed `study-plan-architect.json` with `tools: ["@builtin"]`
and no `mcpServers` "by design"; `test_install_agent_contracts.py:701` pins it; Claude's frontmatter allow-list is
`Read, Write, Grep, Bash`. #13b was right not to touch either: T4.2 is the persona body, and a Web-launched
architect reads the canonical body regardless. The persona now conditions MCP use on the tool appearing in the
session's inventory and gives the fallback, and F3 discloses the boundary in the install doc. **The decision the
owner must make (T6.1):** keep the two harness-launched architects deliberately CLI-limited (then the pin stays and
the install doc's disclosure is the contract), or grant them the plan tools — Kiro: add `studyloop`
(`command: studyloop-mcp`) to `mcpServers` and the nine `mcp_studyloop_*` plan names plus
`mcp_studyloop_record_plan_learning` to `allowedTools`, mirroring `study-mentor.json`; Claude: a least-privilege
explicit MCP allow-list rather than dropping the list; flip line 701 deliberately to `assert "studyloop" in
definition["mcpServers"]`; add `test_install_kiro_architect_connects_studyloop_and_allows_plan_tools` and
`test_install_claude_architect_allows_mcp_plan_tools`. Granting authoring, lifecycle and a destructive tool to a
harness-launched agent changes its permission model, which is why this is a human decision and not an arbiter's
correction (GPT process finding). Learner confirmation for deletion stays a persona rule either way — tool
permission is not user authorisation.

### Process finding

All three seats name the same call: the persona now prefers nine MCP tools while the two harness-launched
definitions withhold them, and no human decided "persona-only this phase, headers in T6.1" before the RED commits
— it fell out of the file ownership. The arbiter upholds #13b's restraint (the headers are a permission-model
change) and records the decision as T6.1's, with the install doc now saying so. Second: for the second review in a
row a cross-cutting hazard addressed to one stream went unowned because it lived outside that stream's file set
(review 3: `CreatePlan.answers`; review 4: the brief budget). The convention review 3 wrote — a hazard is assigned
to one stream's *file set* in `tasks.md` before the streams start — was not applied to T4.2. Applied now for Phase
5: the budget is landed by the arbiter, and #14's own hazards are written into T5.1/T5.2 as file-set work.

## Gate decision

**Phase 4 (#12, #13b) with the review-4 corrections F1–F6 and F8–F11 is ACCEPTED as the base for Phase 5.** #14
may add the "Plan with architect" affordance, the purpose-aware console label (deriving a CLI-started architect's
purpose from its persisted persona mode) and the browser journey against this tree; T6.1 owns the Kiro/Claude
header decision; T6.2's receipt must include the checks listed above.

## Still open for the owner

1. **T6.1 — the Kiro/Claude architect headers:** keep the two harness-launched architects CLI-limited, or wire the
   `studyloop` server and the plan tools into their definitions (see the decision above). The install doc discloses
   the boundary until then.
2. **Score the D-16 rubric** (review 3, item 1) — T3.4 is still open.
3. **Design question from review-3 F2** (urgency classes in `now`) — unchanged.
4. **Deviation 12** (legacy active-but-unready documents) and the **parser bug** (`RANK()` concepts) — unchanged.
5. **Unrelated local branches, again not touched:** `feat/clean-start` and `feat/harness-tier-promotion` (checked
   out in the worktree `../studyloop-wt/harness-tier`) carry unmerged commits that exist nowhere else; deleting
   either destroys work, so neither was removed unattended. No Phase-4 branch or worktree remains.

GATE: ACCEPT
