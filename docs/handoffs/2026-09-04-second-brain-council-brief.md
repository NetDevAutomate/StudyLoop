# Second Brain Release and Launcher Council Brief

**Date:** 2026-09-04
**Audience:** StudyLoop maintainer and autonomous implementation agents
**Decision required:** Produce an implementation-ready plan for release cleanup and a provider-aware Second Brain launcher, including safe parallel delegation and a second council review after implementation.

## Ready means

The council output is ready when it provides:

1. A bounded cleanup plan for the already-published `v0.2.1` release story.
2. A coherent `0.3.0` architecture for launching the configured Second Brain destination.
3. Exact task boundaries and dependencies suitable for parallel subagents.
4. A deterministic validation spine that does not depend on model judgement.
5. A second-pass council review protocol comparing implementation claims with code and test evidence.
6. Explicit rejection of attractive but unsafe or misleading alternatives.

## Settled ordering

The following sequence is accepted and is not up for reordering without identifying a concrete dependency violation:

1. Clean up the `0.2.1` OpenSpec and CHANGELOG inconsistencies.
2. Confirm and document whether release artifacts should be attached.
3. Create a new `0.3.0` OpenSpec change for the provider-aware launcher.
4. Implement Obsidian exact-path launching first.
5. Add validated xTiles destination persistence.
6. Add Settings and Today UI states.
7. Add resolver, API, and browser tests throughout using test-first slices rather than as a final test-only phase.

## Hard constraints

These constraints are settled and must not be relitigated:

1. The published `v0.2.1` tag is immutable. Do not move or recreate it.
2. `0.2.1` must be described as complete Obsidian projection support plus xTiles Stage 1 assistant-mediated integration—not direct or symmetric xTiles integration.
3. The existing six-method `SecondBrain` protocol remains unchanged. Launching is a presentation/navigation concern, not a publish capability.
4. Do not add a direct xTiles API client or move xTiles credentials into StudyLoop.
5. Do not launch applications server-side through `open`, AppleScript, `xdg-open`, subprocesses, or shell commands.
6. Every launch is an explicit browser user gesture. Nothing opens automatically during publish, wind-down, setup, or page load.
7. Obsidian uses the official, percent-encoded absolute-path URI form: `obsidian://open?path=<absolute-path>`.
8. xTiles must open an exact persisted project/page/tile URL. Until a validated destination exists, the launch action is disabled; do not fall back to a generic home page while claiming an exact destination.
9. Persisted xTiles URLs are untrusted input: HTTPS only, reviewed xTiles host allowlist, no credentials, no arbitrary redirects, no sensitive URL logging.
10. Provider selection remains explicit consent. A path or URL alone must not opt the user into a provider.
11. The Today surface presents one configured-provider action, reducing decision load. Settings may show both providers, but inactive providers are visually muted and retain a Configure action.
12. Existing Obsidian filesystem containment, ownership, symlink, idempotence, and no-subprocess guarantees must remain intact.
13. Browser and API behavior must work from installed wheels, not only editable source checkouts.
14. Python uses type hints, pytest/TDD, Ruff, and `uv run` commands. JavaScript uses the repository's existing test conventions.
15. Implementation work uses coherent commits, stages specific paths, and runs the full release validation before completion.
16. This planning council makes no code changes. The same model families review the finished implementation against the final plan and commit claims.

## Codebase facts to verify before relying on them

- Provider configuration and resolution: `packages/studyloop/src/studyloop/settings.py`.
- Stable provider protocol and xTiles inert Stage 1 backend: `packages/studyloop/src/studyloop/second_brain/core.py`.
- Provider factory: `packages/studyloop/src/studyloop/second_brain/factory.py`.
- Obsidian backend and deterministic `Today.md` projection: `packages/studyloop/src/studyloop/second_brain/obsidian.py`.
- Wind-down connector truth table: `packages/studyloop/src/studyloop/second_brain/wind_down.py`.
- Brain CLI surface: `packages/studyloop/src/studyloop/cli/_brain.py`.
- Web route registration: `packages/studyloop/src/studyloop/web/app.py`.
- Today panel state and aggregation: `packages/studyloop/src/studyloop/web/static/components.js`.
- Today and Settings markup: `packages/studyloop/src/studyloop/web/templates/index.html`.
- Second Brain guide: `docs/second-brain.md`.
- Canonical requirement source: `openspec/specs/second-brain/spec.md`.
- Release narrative: `CHANGELOG.md` and `releases/v0.2.1.md`.
- Release consistency logic: `scripts/check-release-consistency.py`.
- CI/build/install gates: `.github/workflows/ci.yml`.

## Known defects and gaps

**D1 — Canonical spec drift.** The canonical Second Brain OpenSpec still describes the older `brain status --json` wind-down behavior and lacks the shipped connector-gated xTiles offer, decline behavior, exact copy, and learning-record flow.

**D2 — CHANGELOG contradiction.** The `0.2.1` section contains contradictory statements about whether the xTiles learning record is written back into the plan.

**D3 — Post-tag documentation.** Current `main` is three documentation commits beyond `v0.2.1`. These are post-release docs and must not cause the tag to move.

**D4 — Distribution ambiguity.** The GitHub release is published without attached assets, and PyPI has no `studyloop==0.2.1` endpoint. CI builds and smoke-tests artifacts, but the intended source-only versus downloadable-artifact policy is not explicit.

**D5 — No web launch contract.** No Second Brain HTTP route or browser-facing launch state exists.

**D6 — Launchability is not availability.** Obsidian `available` currently means a writable vault, while xTiles intentionally reports unavailable and non-publishing. Neither status correctly answers whether a browser can open a provider target.

**D7 — xTiles destination is lost.** The assistant may receive a project/page URL after an MCP action, but StudyLoop neither receives nor persists it.

**D8 — Device locality.** An absolute Obsidian path only works when the browser invoking the URI runs on the same device that owns the vault.

**D9 — No launcher tests.** There are no resolver, URI validation, web API, Settings, Today, or browser tests for this feature.

**D10 — Release/version choice.** There is no repository-specific SemVer policy. The working recommendation is `0.3.0` because this adds config, API, UI, and security behavior rather than fixing an existing launcher.

## Explicitly out of scope

- Direct programmatic xTiles publishing or pulling.
- xTiles credential storage in StudyLoop.
- Automatic provider opening.
- Server-side application launching.
- Moving or recreating `v0.2.1`.
- Making host-local Obsidian paths work from a different mobile/remote device.
- Reworking the established Obsidian projection writer.
- Adding launch methods to the stable `SecondBrain` protocol.
- General redesign of the Today dashboard or LLM Provider settings.

## Questions requiring countable answers

### Q1 — Release cleanup

Name the exact files and minimum edits required to resolve D1-D4. Classify each as release-story blocker, documentation debt, or policy decision. State whether any version/tag change is required.

### Q2 — Launch architecture

Define the smallest provider-neutral launch-target type and ownership seam. Give exact fields, types, and module placement. Explain why it does not belong in `BrainDescription` or the six-method protocol.

### Q3 — Obsidian rules

Define exact target selection order, path validation, percent encoding, device-locality behavior, and disabled reasons. State whether writability should affect launchability.

### Q4 — xTiles persistence

Choose one persistence location and one controlled write path for the exact xTiles URL. Define URL validation and logging/redaction rules. Explain how the assistant hands the URL back without creating a direct xTiles client.

### Q5 — Web API and UX

Give one API response schema and a complete UI state matrix for `none`, Obsidian, xTiles-without-target, xTiles-with-target, missing Obsidian vault, and remote-device ambiguity. Identify exact files to modify.

### Q6 — Parallel execution DAG

Produce tasks with explicit dependency edges. Identify which tasks can run in parallel without editing the same files or depending on unsettled interfaces. Assign each task a best-purpose subagent role and required inputs/outputs.

### Q7 — Validation spine

List deterministic checks in execution order: targeted unit tests, API tests, JS tests, browser tests, installed-wheel checks, full tests, release consistency, and security cases. Define pass/fail evidence expected from each.

### Q8 — Commit and review boundaries

Propose coherent commits that remain bisectable. Define what the second council receives and the exact claims it must verify against code, tests, and git history.

### Q9 — Cut line

Identify the smallest useful release slice and what can move to a later follow-up without making the feature misleading or unsafe.

### Q10 — Challenge the brief

Name at least three assumptions, contradictions, or missing constraints in this brief. Predict where the other model families are most likely to be wrong.

## Required response format

1. **Verified facts and corrections to the brief**
2. **Recommended architecture**
3. **Release cleanup plan**
4. **Task DAG and parallel delegation**
5. **Validation spine**
6. **Commit sequence**
7. **Cut line**
8. **Where other council members will likely be wrong**

Stay under 2,000 words. Do not modify files. Do not hedge toward consensus; another model family is answering independently and the coordinator will arbitrate.