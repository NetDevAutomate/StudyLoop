## Context

Prior review work (`docs/audit/2026-07-11-comprehensive-review.md`) found
the topic→path-traversal defect and the CI e2e-coverage gap independently
of this mission; this change closes the traversal defect as a byproduct of
building a server the e2e harness can actually run against, and gets the
representative journey running locally (closing CI e2e coverage is
explicitly out of scope — tracked separately).

A previous non-Claude agent session left uncommitted WIP that partially
overlaps this change: a thread-hosted uvicorn rewrite in
`_playwright_helpers.py` (the *suspected cause* of the blocker, not a fix
for it), a no-op content-index "warm check" in `web/app.py`, and three
orphaned grok worktrees claiming (falsely, per the handoff doc) that Tasks
1–3 of the outstanding-work plan are complete. This design assumes that
WIP is reviewed and either fixed-and-kept or discarded before/alongside
this change — it is not a foundation to build on uncritically.

## Goals / Non-Goals

**Goals:**
- A locally green, real (not route-stubbed) representative user journey
  covering start → generate → study → review → end.
- A behavioral (LLM-judge) assertion that the mentor's Socratic framing
  survives in real output, not just persona-text unit tests.
- Desktop MCP clients can serve due cards and read course content without
  the browser — closing the "no card-serving tool" gap that made desktop
  MCP feel decorative.
- The shared-slug fix, since it's required to make the harness's traversal
  regression test meaningful and it's the audit's highest-priority open
  P0.

**Non-Goals:**
- CI e2e coverage (audit P0 #3) — explicitly deferred; this change gets
  the suite green locally only.
- Full settings-loader hardening beyond what blocks the journey (audit P0
  #2's remaining `resolve_study_dirs`/`study_paths` shape bugs) — tracked
  separately in the outstanding-work plan, not required for this mission.
- MCP prompts/resources (`@mcp.prompt()`, `@mcp.resource()`) — Codex
  support is unverified; building on unverified capability is explicitly
  against the audit's own recommendation (§6).
- Server-side ACP capability validation for unsupported agents — real gap,
  but orthogonal to unblocking the harness; not required to make the
  journey pass since the journey only exercises PTY-only agents today
  after the fake-PTY-binary fallback lands.

## Decisions

**Subprocess server, not thread-hosted.** The `SIGCHLD` handler
requirement is a hard constraint (`web/routes/session/_start.py:46`
already states it), not something to work around with a threading trick.
A tiny script calling `create_app()` + `uvicorn.run()` directly, launched
via `subprocess.Popen`, satisfies "main thread owns the loop" and avoids
the CLI's non-TTY watchdog exit that made a subprocess look unworkable in
the first place.

**Fake PTY agent binary over live agent CLIs in the harness.** Spawning
real Claude Code/Codex processes in a Playwright/CI environment is
fragile (auth, rate limits, install state). A small script that reads the
persona file and echoes deterministic Socratic-shaped output gives the
PTY transport something real to exec against without those dependencies,
while still exercising the actual fork/exec/SIGCHLD/WS-forwarding path.

**LLM-judge model must differ from the mentor model.** Per global
CLAUDE.md's model-diversity guidance and to avoid the judge rationalizing
its own model family's phrasing as "Socratic enough." Use the LiteLLM
gateway (`http://127.0.0.1:4000`) to pick a genuinely different model for
the judge role.

**Desktop-MCP tools are the fallback path; resources are deliberately
deferred.** The audit's build order (explorer read-parity → card-serving →
insight parity → prompts → generation → resources) is followed here
through step 2 (read-parity + card-serving) because those are the tools
that make desktop MCP usable at all; prompts/resources are higher-risk
(shape easy to get wrong, Codex support unverified) and are cut from this
change's scope rather than built speculatively.

## Risks / Trade-offs

- **Fake-agent fidelity.** A scripted fake agent cannot validate real
  agent-CLI quirks (Kiro's tool-call auto-approval behavior, Claude Code's
  actual streaming cadence). Mitigated by keeping the `live_kiro`-marked
  dogfood test (`test_web_acp_dogfood_kiro.py`) as the real-agent
  regression fence; the fake agent only unblocks the *harness*
  infrastructure test.
- **Grok worktree harvest is a judgment call per lane.** The handoff doc
  flags the lane-completion claims as unverified; harvesting the wrong
  pieces (e.g., partially-correct MCP parity work) could reintroduce bugs
  under a false "already reviewed" assumption. Each lane gets its own
  diff-and-decide task (§3) rather than a blanket merge.
- **Card-serving tool needs a shared join.** `get_due_cards` for MCP needs
  the same due-card content the web review list already serves; if that
  join isn't already extracted into `services/review.py`, this change
  does that extraction rather than duplicating query logic in
  `mcp/tools.py`.
