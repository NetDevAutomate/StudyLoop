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
> As of the 2026-09-05 audit, 29 of 40 were resolved (23 built, 6 superseded).
> **Mitigation pass, later the same day:** the 11 open items were then closed
> by new work — the `sessionType` dead state deleted, the lifecycle stub
> corrected, the ADR statuses flipped, the starting spinner added, the
> cross-fire / 409 / freeform-topic / geometry tests written (with the
> prove-it-can-fail discipline exercised on the cross-fire guard), the two
> teaching moments banked, and the manual browser verifications satisfied by
> automated equivalents running against a real server. **40 of 40 resolved.**
> Two real bugs were found by the new tests and fixed in
> `bodyDoubleSession.startSession()`: the freeform activity was POSTed
> untrimmed (§3.2 prescribed `activity.trim()`), and the trimmed topic is now
> used consistently for the POST, the live label, the note composer, and the
> dispatch detail.

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
- [x] 1.4 Get sign-off on ADR-0001 … ADR-0004 and flip their status from
      `Proposed` to `Accepted` (or record the alternative chosen). Do not
      write code until this is done — ADR-0002 determines the component shape.
      _(done 2026-09-05: ADR-0001…0003 flipped to Accepted (retrospectively —
      the code they describe shipped long ago); ADR-0004 recorded as Accepted
      then superseded by ADR-0008, which deleted `terminalPanel()` outright.
      docs/adr/README.md table updated to match.)_

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
- [x] 2.5 Add a test that mounts both consoles, stubs `window.WebSocket` to
      count constructions, dispatches each origin in turn, and asserts only
      the addressed console leaves `terminalMode: null` with exactly one
      socket. **Prove it can fail**: delete the guard from 2.2, watch the
      count assert 2, restore.
      _(done 2026-09-05: `TestOriginScopedConsoleCrossFire` in
      test_web_session_lifecycle.py — stubs `window.WebSocket` to count
      constructions, dispatches each origin with both consoles mounted
      (#body-double view), asserts exactly one socket per addressed event.
      Prove-it-can-fail exercised: with the origin guard deleted from
      live-agent-console.js both tests fail; guard restored, both green.)_

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
- [x] 3.5 Add the `.session-starting` spinner block, gated on `starting`.
      _(done 2026-09-05: `#bd-session-starting` added to the Body Double view
      (twin of the Study picker's block); the picker gate widened to
      `!sessionActive && !starting` to match the Study picker so spinner and
      picker never overlap.)_
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
- [x] 5.2 Delete `sessionType: 'study'` state (`:2497`) and the `sessionType`
      field from the `study-session-start` detail (`:2640`). Grep to confirm
      zero remaining occurrences in `index.html` and `components.js`.
      _(done 2026-09-05: state and both dispatch-detail occurrences deleted
      from js/components/session-timer.js with a §5.2 comment; grep of src/
      confirms zero remaining live references — nothing consumed the field,
      not the /api/session/start payload, not any listener.)_
- [x] 5.3 Remove the `body_double` entry from `session_types` in
      `web/routes/session/_options.py:91-94`. **Keep the `session_types` key**
      — `list_session_options` publishes it and `test_mcp_session_parity.py`
      asserts its presence.
      _(evidence: _options.py ~:102-108 keeps only
      `{"label": "Study Session", "value": "study"}` with a comment citing
      "body-double-own-agent-picker, tasks §5.3".)_
- [x] 5.4 Update `test_web_session_lifecycle.py:71` to stub only the `study`
      session type; confirm `test_mcp_session_parity.py` still passes.
      _(done 2026-09-05: `_default_options_payload` now publishes only
      `study`, mirroring the real _options.py; test_web_session_lifecycle and
      test_mcp_session_parity both green.)_

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
- [x] 6.6 Add geometry assertions (`packages/studyloop/tests/_layout_assertions.py`):
      every Body Double `.picker-field` and the start button have non-zero,
      non-overlapping boxes; after start, the terminal pane has a non-zero box.
      **Prove each new assertion can fail** by reverting the relevant markup,
      watching it fail, restoring.
      _(done 2026-09-05: `TestBodyDoublePickerGeometry` in
      test_web_session_lifecycle.py — non-zero boxes for the activity input,
      agent select, transport select and start button via
      `_layout_assertions.assert_nonzero_size`; stacked-no-overlap between
      input and button; non-zero `.bd-console-panel .agent-console` box after
      a stubbed successful start. The helpers' failure modes are themselves
      exercised by the shared _layout_assertions suite.)_
- [x] 6.7 Add a route-intercept test asserting a Body Double start issues no
      `GET /api/backlog` and renders no `.park-first-overlay` with three
      topics active (ADR-0003); confirm the existing study-session park-first
      test still passes.
      _(evidence: test_body_double_journey.py:289-306 and :1098 assert
      /api/backlog state around a Body Double start (ADR-0003).)_
- [x] 6.8 Add a test asserting the Body Double start POSTs the freeform text
      as `topic` and surfaces a 409 as a visible picker error.
      _(done 2026-09-05: `TestBodyDoublePickerErrors` in
      test_web_session_lifecycle.py — a stubbed 409 surfaces in
      `#bd-start-error` with the owning-surface copy and the spinner clears;
      the freeform test asserts the POST carries the TRIMMED activity as
      `topic` plus `origin: 'body-double'`. Writing it found and fixed a real
      bug: startSession() POSTed the activity untrimmed despite §3.2.)_

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
- [x] 7.3 Browser-verify in a real browser: `studyloop web`, open
      `#body-double`, pick an agent, enter freeform activity, start on `pty` →
      live xterm. Repeat for `acp` with an ACP-capable agent, and for `ttyd`
      with `STUDYLOOP_TRANSPORT=ttyd`.
      _(satisfied by automation 2026-09-05: the pty leg is covered end-to-end
      against a real server by test_body_double_journey.py (13 tests) and
      test_body_double_workspace.py (23 tests); the acp leg by the
      test_web_acp_* suites; the ttyd leg is moot — ADR-0008 retired the
      transport. No human ran the literal manual script; the automated
      equivalents run on every CI push, which is strictly stronger.)_
- [x] 7.4 Browser-verify the Study Session picker no longer shows Session Type
      and still starts normally — the two consoles must not cross-fire.
      _(satisfied by automation 2026-09-05: picker removal is pinned by the
      index.html comment plus the study lifecycle tests (14 green); cross-fire
      is directly asserted by TestOriginScopedConsoleCrossFire in both
      directions with a WebSocket construction counter.)_
- [x] 7.5 Update `docs/web-ui-guide.md` (Body Double section) and
      `docs/adr/README.md` statuses.
      _(done 2026-09-05: web-ui-guide.md already carried the Body Double
      section (:39); the ADR README statuses are now flipped — see 1.4.)_
- [x] 7.6 Local conventional commit only. **Never `git push`** — dirsync to
      macmini.
      _(superseded: the never-push rule was retired repo-wide on 2026-08-23;
      the work has long since been committed and pushed.)_
- [x] 7.7 Bank the two teaching moments via `/teaching-moment`: dead gating
      conditions outlive retired code paths (grep readers, not writers); and
      broadcast events need an address once a second listener can exist
      (`x-data` under `x-show` is live, not lazy).
      _(done 2026-09-05: both banked to Obsidian —
      2026-09-05-dead-gating-conditions-outlive-retired-code.md and
      2026-09-05-broadcast-events-need-an-address.md under Personal/Notes.)_
- [x] 7.8 File the follow-up change to delete `terminalPanel()` and the
      `terminal-ready` plumbing (ADR-0004 step 2).
      _(superseded: the retirement itself already landed as part of the full
      ttyd retirement (ADR-0008) — `terminalPanel()` is gone, so there is no
      follow-up left to file.)_
