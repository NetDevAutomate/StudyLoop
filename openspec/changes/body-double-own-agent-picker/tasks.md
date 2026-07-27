## 1. Baseline and guardrails

- [ ] 1.1 Confirm the working tree is clean and `git log -1` matches the
      handoff HEAD; record the SHA in the commit message trailer later.
- [ ] 1.2 Reinstall before measuring anything:
      `uv tool install --force --reinstall -e packages/studyloop`
      (never from a git worktree — it clobbers the live `:8567` install).
- [ ] 1.3 Capture a green baseline of every affected suite and save the output.
      **The handoff's command is wrong**: `test_web_navigation.py`,
      `test_web_terminal.py`, and `test_web_layout_regression.py` are all
      `pytestmark = [pytest.mark.e2e]`, which the repo's default marker
      expression deselects — that command reports `28 passed, 60 deselected`
      and runs none of the tests this change breaks. Run both halves:
      `VIRTUAL_ENV=.venv uv run --active pytest packages/studyloop/tests/test_web_session_lifecycle.py packages/studyloop/tests/test_terminal_proxy.py packages/studyloop/tests/test_mcp_session_parity.py -q`
      then
      `VIRTUAL_ENV=.venv uv run --active pytest packages/studyloop/tests/test_web_navigation.py packages/studyloop/tests/test_web_terminal.py packages/studyloop/tests/test_web_layout_regression.py -q -m e2e`
- [ ] 1.3a Known baseline state after macmini merge `82a3fbb` (measured
      2026-07-27): default-marker set `28 passed`; marked e2e set
      `1 failed, 39 passed, 4 skipped`; representative Body Double Pomodoro
      journey `1 passed, 8 deselected`. The one failure is unchanged from the
      pre-merge `a0fe6f0` baseline and unrelated —
      `TestQuizzesConfigNavLayout::test_config_nav_title_is_centered`, filed as
      `docs/issues/0001-quizzes-config-nav-title-not-centered.md`. Do not
      attribute it to this change; do not fix it in this change.
- [ ] 1.4 Get sign-off on ADR-0001 … ADR-0004 and flip their status from
      `Proposed` to `Accepted` (or record the alternative chosen). Do not
      write code until this is done — ADR-0002 determines the component shape.

## 2. Origin-scoped console (ADR-0002 — do this first, it is the fork)

- [ ] 2.1 Change `liveAgentConsole()` to `liveAgentConsole(origin = 'study')`
      and store `origin` on the returned object.
- [ ] 2.2 In `init()`, ignore `study-session-start` / `study-session-stop`
      whose `detail.origin` (defaulting to `'study'`) differs from `this.origin`.
- [ ] 2.3 Set `origin: 'study'` in `sessionTimer().startSession()`'s
      `study-session-start` detail and in `confirmEndSession()`'s
      `study-session-stop` detail (currently dispatched with no detail).
- [ ] 2.4 Pass `'study'` explicitly at the existing mount
      (`x-data="liveAgentConsole('study')"`).
- [ ] 2.5 Add a test that mounts both consoles, stubs `window.WebSocket` to
      count constructions, dispatches each origin in turn, and asserts only
      the addressed console leaves `terminalMode: null` with exactly one
      socket. **Prove it can fail**: delete the guard from 2.2, watch the
      count assert 2, restore.

## 3. Body Double picker (`bodyDoubleSession()`)

- [ ] 3.1 Add the `bodyDoubleSession()` factory: state (`activity`, `energy`,
      `agent`, `transport`, `studyOptions`, `sessionActive`, `starting`,
      `startError`), `init()` hydrating from `GET /api/session/options` and
      pre-selecting the first available agent, `agentOptions()`,
      `selectedAgentSupportsAcp()`, `canStart()`.
- [ ] 3.2 Implement `startSession()`: POST `/api/session/start` with
      `{topic: activity.trim(), energy, agent, transport}`, defensive
      text-then-JSON parse (mirror `sessionTimer()` so a non-JSON 500 is not
      reported as a network error), surface HTTP 409 as a picker error, then
      dispatch `study-session-start` with `origin: 'body-double'`.
      **No `/api/backlog` call** (ADR-0003).
- [ ] 3.3 Implement `endSession()`: POST `/api/session/end`, dispatch
      `study-session-stop` with `origin: 'body-double'`.
- [ ] 3.4 Build the picker markup inside `.body-double-dashboard`, reusing
      `.session-start-picker` / `.picker-field` / `.picker-select` /
      `.picker-input` / `.picker-inline` / `.picker-hint` /
      `.agent-choice-grid` / `.start-session-btn` / `.picker-error`. Include
      the three transport hint paragraphs to match Study Session.
- [ ] 3.5 Add the `.session-starting` spinner block, gated on `starting`.
- [ ] 3.6 Keep `.body-double-header` (h2 + p) and `.body-double-timer` /
      `.body-double-controls` exactly as-is, with the timer outside the
      `!sessionActive` gate.

## 4. Body Double terminal (ADR-0004)

- [ ] 4.1 Replace the `terminalPanel()` mount in `.split-terminal` with
      `x-data="liveAgentConsole('body-double')"` and the three surface
      branches (`xterm`, `acp-chat`, `ttyd-iframe`) mirroring the Study
      Session active layout.
- [ ] 4.2 Bypass `splitLayout()`'s `term.style.display = 'none'` /
      `terminal-ready` gate for this pane without changing behaviour for the
      Study Session ttyd surface.
- [ ] 4.3 Leave the `terminalPanel()` factory in place, unmounted, with a
      comment naming ADR-0004 and the follow-up retirement change. Verify
      `grep -c "terminalPanel()" index.html` is exactly 1.
- [ ] 4.4 Confirm no `.body-double-*` CSS rule (`style.css:337-365`) or the
      `main:has(.split-container)` override (`:1570`) breaks with the picker
      present. Preserve the modern terminal's shrink-safe production class
      chain introduced by macmini commit `f29567c`: `.session-terminal-area`
      (`:1796`), `.embedded-terminal-panel` (`:1814`),
      `.embedded-terminal-content` / `.xterm-content`, and `.xterm-mount`
      (`:2115`) must retain `min-width: 0`; the mount retains
      `overflow: hidden`.

## 5. Remove the dead session-type path

- [ ] 5.1 Delete the Session Type `.picker-field` from the Study Session
      picker (`index.html:1516-1519`).
- [ ] 5.2 Delete `sessionType: 'study'` state (`:2497`) and the `sessionType`
      field from the `study-session-start` detail (`:2640`). Grep to confirm
      zero remaining occurrences in `index.html` and `components.js`.
- [ ] 5.3 Remove the `body_double` entry from `session_types` in
      `web/routes/session/_options.py:91-94`. **Keep the `session_types` key**
      — `list_session_options` publishes it and `test_mcp_session_parity.py`
      asserts its presence.
- [ ] 5.4 Update `test_web_session_lifecycle.py:71` to stub only the `study`
      session type; confirm `test_mcp_session_parity.py` still passes.

## 6. Tests and geometry

- [ ] 6.1 Skip (do not delete) the `terminalPanel()`-markup tests in
      `test_web_terminal.py` (`154-270`, `409`, `426`, `531-535`) with a skip
      reason naming ADR-0004 so the retirement change knows what to remove.
- [ ] 6.2 Rewrite `test_terminal_proxy.py::test_iframe_waits_for_successful_terminal_probe`
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
- [ ] 6.3 Confirm `test_web_layout_regression.py:203-211`
      (`.body-double-header h2/p` geometry) passes unchanged.
- [ ] 6.4 Confirm `test_web_navigation.py:74-77,123-132,159-160` still
      resolves the `[x-show*="body-double"]` root.
- [ ] 6.5 Confirm `e2e/test_representative_user_journey.py:93-108` still finds
      `.body-double-controls input[type=number]` and
      `button:has-text("Start Pomodoro")`.
- [ ] 6.6 Add geometry assertions (`packages/studyloop/tests/_layout_assertions.py`):
      every Body Double `.picker-field` and the start button have non-zero,
      non-overlapping boxes; after start, the terminal pane has a non-zero box.
      **Prove each new assertion can fail** by reverting the relevant markup,
      watching it fail, restoring.
- [ ] 6.7 Add a route-intercept test asserting a Body Double start issues no
      `GET /api/backlog` and renders no `.park-first-overlay` with three
      topics active (ADR-0003); confirm the existing study-session park-first
      test still passes.
- [ ] 6.8 Add a test asserting the Body Double start POSTs the freeform text
      as `topic` and surfaces a 409 as a visible picker error.

## 7. Verify and land

- [ ] 7.1 `uv tool install --force --reinstall -e packages/studyloop`, then run
      **both** baseline commands from 1.3 (default-marker set *and* `-m e2e`
      set) plus the new tests; diff against the 1.3a figures. Any new failure
      other than issue 0001 belongs to this change.
- [ ] 7.2 Ruff scoped to changed files only (repo-wide runs surface
      pre-existing debt).
- [ ] 7.3 Browser-verify in a real browser: `studyloop web`, open
      `#body-double`, pick an agent, enter freeform activity, start on `pty` →
      live xterm. Repeat for `acp` with an ACP-capable agent, and for `ttyd`
      with `STUDYLOOP_TRANSPORT=ttyd`.
- [ ] 7.4 Browser-verify the Study Session picker no longer shows Session Type
      and still starts normally — the two consoles must not cross-fire.
- [ ] 7.5 Update `docs/web-ui-guide.md` (Body Double section) and
      `docs/adr/README.md` statuses.
- [ ] 7.6 Local conventional commit only. **Never `git push`** — dirsync to
      macmini.
- [ ] 7.7 Bank the two teaching moments via `/teaching-moment`: dead gating
      conditions outlive retired code paths (grep readers, not writers); and
      broadcast events need an address once a second listener can exist
      (`x-data` under `x-show` is live, not lazy).
- [ ] 7.8 File the follow-up change to delete `terminalPanel()` and the
      `terminal-ready` plumbing (ADR-0004 step 2).
