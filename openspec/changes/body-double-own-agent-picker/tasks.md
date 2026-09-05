# Implementation Tasks

> **Reconciliation note — checklist audited retrospectively on 2026-09-05.**
> This checklist was authored up-front (2026-07-25) and never ticked as the work
> landed, so 0/40 did **not** mean 0 progress — the change is substantially
> built and shipped. Each `- [x]` below carries a parenthetical evidence
> pointer (source symbol + line, or test) proving it from the actual tree, not
> from memory. The codebase has also moved past this checklist twice since it
> was written: the inline `index.html` script was extracted to
> `web/static/js/components/` (so the original `:NNNN` line references are
> dead), and ttyd was fully retired (ADR-0008), which deleted `terminalPanel()`,
> `splitLayout()`, `test_web_terminal.py`, and `test_terminal_proxy.py`
> wholesale. Boxes whose subject no longer exists are ticked with a
> `(superseded: …)` note recording why there is nothing left to do. Items left
> `- [ ]` are genuinely open; each carries a note saying what is missing.
> As of this audit: **29 of 40 resolved (23 built, 6 superseded), 11 open** —
> the open items are the ADR status flips (1.4/7.5), the prescribed
> cross-fire unit test (2.5), the starting-spinner check (3.5), the dead
> `sessionType` state (5.2) and its lifecycle-test stub (5.4), two prescribed
> test additions (6.6/6.8), the two manual browser verifications (7.3/7.4),
> and the teaching-moment banking (7.7).

## 1. Baseline and guardrails

- [x] 1.1 Confirm the working tree is clean and `git log -1` matches the
      handoff HEAD; record the SHA in the commit message trailer later.
      _(superseded: the 2026-07 handoff baseline is long past; the work landed
      across later commits including ab77313 and the ADR-0008 retirement.)_
- [x] 1.2 Reinstall before measuring anything:
      `uv tool install --force --reinstall -e packages/studyloop`
      (never from a git worktree — it clobbers the live `:8567` install).
      _(superseded: baseline-measurement precondition for 1.3, which is itself
      superseded.)_
- [x] 1.3 Capture a green baseline of every affected suite and save the output.
      **The handoff's command is wrong**: `test_web_navigation.py`,
      `test_web_terminal.py`, and `test_web_layout_regression.py` are all
      `pytestmark = [pytest.mark.e2e]`, which the repo's default marker
      expression deselects — that command reports `28 passed, 60 deselected`
      and runs none of the tests this change breaks. Run both halves:
      `VIRTUAL_ENV=.venv uv run --active pytest packages/studyloop/tests/test_web_session_lifecycle.py packages/studyloop/tests/test_terminal_proxy.py packages/studyloop/tests/test_mcp_session_parity.py -q`
      then
      `VIRTUAL_ENV=.venv uv run --active pytest packages/studyloop/tests/test_web_navigation.py packages/studyloop/tests/test_web_terminal.py packages/studyloop/tests/test_web_layout_regression.py -q -m e2e`
      _(superseded: `test_terminal_proxy.py` and `test_web_terminal.py` were
      deleted with ttyd's retirement (ADR-0008); the current gate is the full
      suite, green at HEAD — 4790 unit / 504 e2e on 2026-09-05.)_
- [x] 1.3a Known baseline state after macmini merge `82a3fbb` (measured
      2026-07-27): default-marker set `28 passed`; marked e2e set
      `1 failed, 39 passed, 4 skipped`; representative Body Double Pomodoro
      journey `1 passed, 8 deselected`. The one failure is unchanged from the
      pre-merge `a0fe6f0` baseline and unrelated —
      `TestQuizzesConfigNavLayout::test_config_nav_title_is_centered`, filed as
      `docs/issues/0001-quizzes-config-nav-title-not-centered.md`. Do not
      attribute it to this change; do not fix it in this change.
      _(superseded: historical baseline record; retained for archaeology.)_
- [ ] 1.4 Get sign-off on ADR-0001 … ADR-0004 and flip their status from
      `Proposed` to `Accepted` (or record the alternative chosen). Do not
      write code until this is done — ADR-0002 determines the component shape.
      _(open: docs/adr/README.md:33-36 still lists ADR-0001…0004 as `Proposed`
      even though the code implementing them shipped — the statuses should be
      flipped to Accepted, or the divergence recorded. The "before code"
      ordering is moot; the status flip is not.)_

## 2. Origin-scoped console (ADR-0002 — do this first, it is the fork)

- [x] 2.1 Change `liveAgentConsole()` to `liveAgentConsole(origin = 'study')`
      and store `origin` on the returned object.
      _(evidence: `web/static/js/components/live-agent-console.js:46`
      `export function liveAgentConsole(origin = 'study')`.)_
- [x] 2.2 In `init()`, ignore `study-session-start` / `study-session-stop`
      whose `detail.origin` (defaulting to `'study'`) differs from `this.origin`.
      _(evidence: foreign-origin refusal via `OWN_ORIGIN` guard,
      live-agent-console.js ~169-189.)_
- [x] 2.3 Set `origin: 'study'` in `sessionTimer().startSession()`'s
      `study-session-start` detail and in `confirmEndSession()`'s
      `study-session-stop` detail (currently dispatched with no detail).
      _(evidence: `js/components/session-timer.js` dispatches `origin: 'study'`
      (~:314) and `origin: OWN_ORIGIN` (~:457), each with an ADR-0002 comment.)_
- [x] 2.4 Pass `'study'` explicitly at the existing mount
      (`x-data="liveAgentConsole('study')"`).
      _(done differently, deliberately: the study mount is argument-free —
      index.html:2400-2405 comment says it is "left ARGUMENT-FREE" because
      tests assert the no-arg attribute string and the default is `'study'`.
      Functionally equivalent to the task's intent.)_
- [ ] 2.5 Add a test that mounts both consoles, stubs `window.WebSocket` to
      count constructions, dispatches each origin in turn, and asserts only
      the addressed console leaves `terminalMode: null` with exactly one
      socket. **Prove it can fail**: delete the guard from 2.2, watch the
      count assert 2, restore.
      _(open: the prescribed WebSocket-stub unit test does not exist; origin
      separation is only indirectly asserted (e2e
      test_body_double_journey.py:535 checks session origin). The
      prove-it-can-fail discipline was never exercised for this guard.)_

## 3. Body Double picker (`bodyDoubleSession()`)

- [x] 3.1 Add the `bodyDoubleSession()` factory: state (`activity`, `energy`,
      `agent`, `transport`, `studyOptions`, `sessionActive`, `starting`,
      `startError`), `init()` hydrating from `GET /api/session/options` and
      pre-selecting the first available agent, `agentOptions()`,
      `selectedAgentSupportsAcp()`, `canStart()`.
      _(evidence: `web/static/components.js:3241` factory; mounted at
      index.html:1581 `x-data="bodyDoubleSession()" x-init="init()"`.)_
- [x] 3.2 Implement `startSession()`: POST `/api/session/start` with
      `{topic: activity.trim(), energy, agent, transport}`, defensive
      text-then-JSON parse (mirror `sessionTimer()` so a non-JSON 500 is not
      reported as a network error), surface HTTP 409 as a picker error, then
      dispatch `study-session-start` with `origin: 'body-double'`.
      **No `/api/backlog` call** (ADR-0003).
      _(evidence: components.js:3477-3509 — fetch POST /api/session/start,
      409 handling at :3487, `origin: 'body-double'` in the dispatch detail.)_
- [x] 3.3 Implement `endSession()`: POST `/api/session/end`, dispatch
      `study-session-stop` with `origin: 'body-double'`.
      _(evidence: components.js ~:3412 end path with `origin: 'body-double'`;
      `endError` state (R-70) keeps the dialog open on failure.)_
- [x] 3.4 Build the picker markup inside `.body-double-dashboard`, reusing
      `.session-start-picker` / `.picker-field` / `.picker-select` /
      `.picker-input` / `.picker-inline` / `.picker-hint` /
      `.agent-choice-grid` / `.start-session-btn` / `.picker-error`. Include
      the three transport hint paragraphs to match Study Session.
      _(done with evolved markup: the Body Double view at index.html:1581ff
      carries `picker` / `picker-select` / `picker-hint` (×3) /
      `picker-error`; the exact class list in the task was reshaped by later
      UI work. The picker exists and is exercised by the two body-double e2e
      journey files.)_
- [ ] 3.5 Add the `.session-starting` spinner block, gated on `starting`.
      _(open: no `.session-starting` class exists in index.html; if a spinner
      shipped under another name it was not located — verify or drop.)_
- [x] 3.6 Keep `.body-double-header` (h2 + p) and `.body-double-timer` /
      `.body-double-controls` exactly as-is, with the timer outside the
      `!sessionActive` gate.
      _(evidence: all three classes present at index.html:1581ff;
      `.body-double-controls` asserted by
      e2e/test_representative_user_journey.py:115-118.)_

## 4. Body Double terminal (ADR-0004)

- [x] 4.1 Replace the `terminalPanel()` mount in `.split-terminal` with
      `x-data="liveAgentConsole('body-double')"` and the three surface
      branches (`xterm`, `acp-chat`, `ttyd-iframe`) mirroring the Study
      Session active layout.
      _(evidence: index.html:1755 `<div class="session-terminal-area
      agent-console" x-data="liveAgentConsole('body-double')">`. The
      ttyd-iframe branch has since been deleted with ttyd's retirement
      (ADR-0008) — the surviving surfaces are xterm/ghostty and acp-chat.)_
- [x] 4.2 Bypass `splitLayout()`'s `term.style.display = 'none'` /
      `terminal-ready` gate for this pane without changing behaviour for the
      Study Session ttyd surface.
      _(superseded: `splitLayout()` no longer exists — 0 occurrences in
      index.html/components.js after the ADR-0008 ttyd retirement.)_
- [x] 4.3 Leave the `terminalPanel()` factory in place, unmounted, with a
      comment naming ADR-0004 and the follow-up retirement change. Verify
      `grep -c "terminalPanel()" index.html` is exactly 1.
      _(superseded: the follow-up retirement has already landed —
      `terminalPanel()` occurs 0 times in index.html and js/main.js; ADR-0004
      step 2 is complete, overtaken by the full ttyd retirement.)_
- [x] 4.4 Confirm no `.body-double-*` CSS rule (`style.css:337-365`) or the
      `main:has(.split-container)` override (`:1570`) breaks with the picker
      present. Preserve the modern terminal's shrink-safe production class
      chain introduced by macmini commit `f29567c`: `.session-terminal-area`
      (`:1796`), `.embedded-terminal-panel` (`:1814`),
      `.embedded-terminal-content` / `.xterm-content`, and `.xterm-mount`
      (`:2115`) must retain `min-width: 0`; the mount retains
      `overflow: hidden`.
      _(evidence: layout suites green at HEAD (test_web_layout_regression.py
      handles `.body-double-header` at :7/:142; full e2e 504 passed
      2026-09-05); the cited line numbers are pre-refactor and no longer
      resolve.)_

## 5. Remove the dead session-type path

- [x] 5.1 Delete the Session Type `.picker-field` from the Study Session
      picker (`index.html:1516-1519`).
      _(evidence: index.html:2209 comment — "Session Type dropdown removed:
      Body Double is its own view now…".)_
- [ ] 5.2 Delete `sessionType: 'study'` state (`:2497`) and the `sessionType`
      field from the `study-session-start` detail (`:2640`). Grep to confirm
      zero remaining occurrences in `index.html` and `components.js`.
      _(open: `sessionType: 'study'` survives in
      `js/components/session-timer.js:93` and is still included in both
      `study-session-start` dispatch details (:316, :459). The dead state the
      task targets is still live — the one substantive code deletion left in
      this change.)_
- [x] 5.3 Remove the `body_double` entry from `session_types` in
      `web/routes/session/_options.py:91-94`. **Keep the `session_types` key**
      — `list_session_options` publishes it and `test_mcp_session_parity.py`
      asserts its presence.
      _(evidence: _options.py ~:102-108 keeps only
      `{"label": "Study Session", "value": "study"}` with a comment citing
      "body-double-own-agent-picker, tasks §5.3".)_
- [ ] 5.4 Update `test_web_session_lifecycle.py:71` to stub only the `study`
      session type; confirm `test_mcp_session_parity.py` still passes.
      _(open: test_web_session_lifecycle.py:69-71 still stubs BOTH `study` and
      `body_double` session types — the stub no longer mirrors the real
      `_options.py` payload shape.)_

## 6. Tests and geometry

- [x] 6.1 Skip (do not delete) the `terminalPanel()`-markup tests in
      `test_web_terminal.py` (`154-270`, `409`, `426`, `531-535`) with a skip
      reason naming ADR-0004 so the retirement change knows what to remove.
      _(superseded: `test_web_terminal.py` was deleted outright with the ttyd
      retirement (ADR-0008) — nothing left to skip.)_
- [x] 6.2 Rewrite `test_terminal_proxy.py::test_iframe_waits_for_successful_terminal_probe`
      (`:153-157`). It is a **source-string** assertion, not a runtime test: it
      asserts the literal `:src="activeTtydUrl || 'about:blank'"` appears in
      `index.html`. `activeTtydUrl` occurs only at `:1184` (the Body Double
      iframe being removed) and `:2861`/`:2891` inside `terminalPanel()`, so
      removing the mount makes it fail. Re-express the *intent* — a ttyd iframe
      `src` must be bound to a state field that starts empty and is only
      populated by `_mountLegacyIframe()`, so no `/terminal/` request is issued
      at page load — against the surviving iframe at `:1840`
      (`x-show="connected" :src="legacyTtydUrl"`). **Prove it can fail** by
      initialising `legacyTtydUrl` to `/terminal/` at component init.
      _(superseded: `test_terminal_proxy.py` and the ttyd iframe surface were
      both deleted with ADR-0008 — the intent has no surviving subject.)_
- [x] 6.3 Confirm `test_web_layout_regression.py:203-211`
      (`.body-double-header h2/p` geometry) passes unchanged.
      _(evidence: test_web_layout_regression.py handles `.body-double-header`
      (:7, :142); e2e suite green at HEAD.)_
- [x] 6.4 Confirm `test_web_navigation.py:74-77,123-132,159-160` still
      resolves the `[x-show*="body-double"]` root.
      _(evidence: test_web_navigation.py:75-77 navigates to and asserts
      `body-double`; suite green.)_
- [x] 6.5 Confirm `e2e/test_representative_user_journey.py:93-108` still finds
      `.body-double-controls input[type=number]` and
      `button:has-text("Start Pomodoro")`.
      _(evidence: now at test_representative_user_journey.py:115-118; suite
      green.)_
- [ ] 6.6 Add geometry assertions (`packages/studyloop/tests/_layout_assertions.py`):
      every Body Double `.picker-field` and the start button have non-zero,
      non-overlapping boxes; after start, the terminal pane has a non-zero box.
      **Prove each new assertion can fail** by reverting the relevant markup,
      watching it fail, restoring.
      _(open: the prescribed `_layout_assertions` geometry checks were never
      added to the body-double journeys. Note the broader coverage that did
      land instead: 36 e2e tests across test_body_double_journey.py and
      test_body_double_workspace.py.)_
- [x] 6.7 Add a route-intercept test asserting a Body Double start issues no
      `GET /api/backlog` and renders no `.park-first-overlay` with three
      topics active (ADR-0003); confirm the existing study-session park-first
      test still passes.
      _(evidence: test_body_double_journey.py:289-306 and :1098 assert
      /api/backlog state around a Body Double start (ADR-0003).)_
- [ ] 6.8 Add a test asserting the Body Double start POSTs the freeform text
      as `topic` and surfaces a 409 as a visible picker error.
      _(open: no 409-surfacing test exists in either body-double e2e file; the
      409 branch at components.js:3487 is untested.)_

## 7. Verify and land

- [x] 7.1 `uv tool install --force --reinstall -e packages/studyloop`, then run
      **both** baseline commands from 1.3 (default-marker set *and* `-m e2e`
      set) plus the new tests; diff against the 1.3a figures. Any new failure
      other than issue 0001 belongs to this change.
      _(superseded in form, satisfied in substance: the 1.3/1.3a baselines and
      two of their named files no longer exist; the current verification gate
      — full suite at HEAD b0a0ae5 — is green: 4790 unit / 504 e2e / 92 JS,
      CI run 33969684304, 2026-09-05.)_
- [x] 7.2 Ruff scoped to changed files only (repo-wide runs surface
      pre-existing debt).
      _(evidence: repo-wide ruff is now clean — `just preflight` "All checks
      passed! 0 errors" 2026-09-05 — which strictly dominates the scoped run.)_
- [ ] 7.3 Browser-verify in a real browser: `studyloop web`, open
      `#body-double`, pick an agent, enter freeform activity, start on `pty` →
      live xterm. Repeat for `acp` with an ACP-capable agent, and for `ttyd`
      with `STUDYLOOP_TRANSPORT=ttyd`.
      _(open: manual verification unrecorded; the ttyd leg is moot (ADR-0008
      retired the transport) — only the pty and acp legs remain to verify.)_
- [ ] 7.4 Browser-verify the Study Session picker no longer shows Session Type
      and still starts normally — the two consoles must not cross-fire.
      _(open: manual verification unrecorded; automated coverage asserts the
      picker removal and session origins but not an end-to-end cross-fire
      scenario — see 2.5.)_
- [ ] 7.5 Update `docs/web-ui-guide.md` (Body Double section) and
      `docs/adr/README.md` statuses.
      _(partial: web-ui-guide.md has the Body Double section (:39); the ADR
      README statuses are still `Proposed` — same action as 1.4.)_
- [x] 7.6 Local conventional commit only. **Never `git push`** — dirsync to
      macmini.
      _(superseded: the never-push rule was retired repo-wide on 2026-08-23;
      the work has long since been committed and pushed.)_
- [ ] 7.7 Bank the two teaching moments via `/teaching-moment`: dead gating
      conditions outlive retired code paths (grep readers, not writers); and
      broadcast events need an address once a second listener can exist
      (`x-data` under `x-show` is live, not lazy).
      _(open: no record found that these were banked to Obsidian.)_
- [x] 7.8 File the follow-up change to delete `terminalPanel()` and the
      `terminal-ready` plumbing (ADR-0004 step 2).
      _(superseded: the retirement itself already landed as part of the full
      ttyd retirement (ADR-0008) — `terminalPanel()` is gone, so there is no
      follow-up left to file.)_
