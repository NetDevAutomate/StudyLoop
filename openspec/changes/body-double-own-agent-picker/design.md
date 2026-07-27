## Context

Two unrelated things are called "Body Double" today, and both are broken.

**The `#body-double` view** (`web/static/index.html:1142-1191`) contains a
Pomodoro timer and a terminal that can never appear. Its terminal is
`terminalPanel()` (`:2852`), gated `x-show="available"`, where `available` is
set from `state.ttyd_port`:

```js
const state = await (await fetch('/api/session/state')).json();
if (!state.ttyd_port) { this.available = false; ... return; }   // :2874
```

`ttyd_port` is written in exactly one place — `session/orchestrator.py:451`,
reached only by the deprecated `transport: "ttyd"` path. `pty` is the resolved
default, so the field is never set, the whole `.terminal-panel` div is hidden
(taking its own "unavailable" fallback message with it), and `splitLayout()`
(`:3658`) additionally force-hides the pane pending a `terminal-ready` event
that never fires. The learner gets blank space and no explanation.

**The `body_double` option in the Study Session picker** (`:1516-1519`) is a
label with no behaviour. `sessionType` occurs three times in the frontend —
the `<select>` binding (`:1516`), the initial state (`:2497`), and the
`study-session-start` event detail (`:2640`) — and is read nowhere.
`liveAgentConsole().start()` branches only on `detail.transport`.
`StartSessionRequest` (`web/routes/session/_models.py:9-24`) has only `topic`,
`energy`, `agent`, `transport`. Selecting it is a no-op that leaves the
learner on the Study Session view.

Constraints in play:

- Exactly one session may be active (`session/active.py:46`, HTTP 409 on a
  second start) — spec `session-transports`.
- `transport: "ttyd"` is still a supported, spec'd fallback, forceable via
  `STUDYLOOP_TRANSPORT`.
- Alpine initialises `x-data` under `x-show`. Hidden components are live.
- Macmini commit `f29567c` adds `min-width: 0` down the modern terminal flex
  chain (`.session-terminal-area` at `style.css:1796`,
  `.embedded-terminal-panel` at `:1814`, `.embedded-terminal-content` /
  `.xterm-content`, and `.xterm-mount` at `:2115`) plus
  `overflow: hidden` on the mount. The Body Double console MUST preserve this
  production class chain; otherwise the new xterm will reintroduce the
  grow-but-never-shrink defect. The older references remain valid after the
  merge: `.body-double-*` is still `style.css:337-365`,
  `main:has(.split-container)` is still `:1570`, and the Body Double /
  picker / console locations in `index.html` did not move.
- Seven existing test groups touch this markup; three of them
  (`.body-double-header` geometry, `.body-double-controls` e2e Pomodoro,
  `[x-show*="body-double"]` nav wiring) must keep passing unchanged.

## Goals / Non-Goals

**Goals:**

- Body Double can start an agent CLI in a working terminal, choosing agent
  and transport, describing the activity in one freeform line.
- Body Double and Study Session look like the same product — shared CSS
  classes, not a parallel design.
- Delete the dead `sessionType` path rather than leave it as a trap.
- Make the double-console hazard impossible by construction, and testable.
- Preserve every load-bearing selector the existing suites depend on.

**Non-Goals:**

- No backend change to session start (ADR-0001).
- No session-type discriminator anywhere in the stack (ADR-0001).
- No deletion of `terminalPanel()` / `splitLayout()`'s `terminal-ready`
  plumbing in this change (ADR-0004).
- No course/vendor/lesson cascade in Body Double.
- No Body-Double-specific persona. The existing Socratic persona is delivered
  as-is; the wart is recorded in ADR-0001.
- No change to the park-first rule for study sessions.

## Decisions

The four load-bearing decisions are recorded as ADRs, with alternatives
considered, and are summarised here only enough to read this document:

| ADR | Decision |
|---|---|
| [ADR-0001](../../../docs/adr/0001-body-double-reuses-session-start-endpoint.md) | Body Double reuses `POST /api/session/start`, freeform text → `topic`. No new endpoint, no session-type field. |
| [ADR-0002](../../../docs/adr/0002-origin-scoped-live-agent-console.md) | `liveAgentConsole(origin)` filters `study-session-start`/`-stop` by `detail.origin`. Two independent instances, addressed not broadcast. |
| [ADR-0003](../../../docs/adr/0003-body-double-exempt-from-park-first-friction.md) | Body Double skips the park-first 3-topic gate entirely. |
| [ADR-0004](../../../docs/adr/0004-retire-terminal-panel-from-body-double.md) | Unmount `terminalPanel()` from Body Double; delete it in a separate change. |

### Component shape

A new `bodyDoubleSession()` Alpine factory owns the Body Double picker and
session lifecycle. It is a deliberate near-sibling of `sessionTimer()`, not a
subclass and not a shared base:

```
bodyDoubleSession()
  state:   activity, energy, agent, transport, studyOptions,
           sessionActive, starting, startError
  methods: init()            → GET /api/session/options (+ preselect agent)
           agentOptions()     → studyOptions.agents
           selectedAgentSupportsAcp()
           canStart()         → activity.trim() && agent
           startSession()     → POST /api/session/start
                                → dispatch study-session-start {origin:'body-double'}
           endSession()       → POST /api/session/end
                                → dispatch study-session-stop {origin:'body-double'}
```

`sessionTimer()` keeps its cascade, its park-first flow, its pause/resume, and
its end-confirm overlay. `bodyDoubleSession()` has none of those. Extracting a
shared base would couple the one component that must stay simple to the one
component that carries all the study-specific friction — the overlap is four
lines of agent-option plumbing, which is cheaper duplicated than abstracted.

**What IS shared, deliberately:** the CSS classes and the markup shape of the
agent/transport fields. If those drift, the two surfaces stop looking like one
product. A follow-up may hoist the agent+transport fields into an Alpine
`<template>` partial; not required for this change.

### Markup shape of the rebuilt view

```
#body-double
└── .split-container            x-data="splitLayout()"
    ├── .split-panel.split-dashboard
    │   └── .session-dashboard.body-double-dashboard   x-data="bodyDoubleSession()"
    │       ├── .body-double-header            (h2 + p — KEEP, geometry-tested)
    │       ├── .session-start-picker          x-show="!sessionActive && !starting"
    │       │   ├── .picker-field   activity (freeform text)
    │       │   ├── .picker-field.picker-inline   agent + transport
    │       │   ├── .picker-field   .agent-choice-grid
    │       │   ├── .picker-field   energy slider
    │       │   └── .start-session-btn + .picker-hint + .picker-error
    │       ├── .session-starting              x-show="starting"
    │       └── .body-double-timer             (always visible)
    │           └── .body-double-controls      (KEEP — e2e Pomodoro selectors)
    └── .split-panel.split-terminal
        └── .agent-console      x-data="liveAgentConsole('body-double')"
            ├── xterm mount     x-show="terminalMode === 'xterm'"
            ├── acp chat        x-show="terminalMode === 'acp-chat'"
            └── ttyd iframe     x-show="terminalMode === 'ttyd-iframe'"
```

The Pomodoro timer stays outside the `x-show="!sessionActive"` gate — body
doubling with a timer and no agent is a legitimate mode, and the e2e journey
(`test_representative_user_journey.py:93-108`) starts the Pomodoro without a
session.

`splitLayout()` is retained for the Split.js gutter, but its
`term.style.display = 'none'` / `terminal-ready` gate must be bypassed for this
view — the terminal pane is always laid out; the console decides its own
contents. Prefer a guard keyed on the pane having a `liveAgentConsole` child
over deleting the gate outright, so the Study Session ttyd surface is
untouched (ADR-0004 defers the deletion).

### Removals

| Location | Removal |
|---|---|
| `index.html:1516-1519` | Session Type `.picker-field` block |
| `index.html:2497` | `sessionType: 'study'` state |
| `index.html:2640` | `sessionType` in the event detail |
| `index.html:1142-1191` | `terminalPanel()` mount + its iframe markup |
| `_options.py:91-94` | the `body_double` entry (keep the `session_types` key) |

## Risks / Trade-offs

- **Two live `liveAgentConsole()` instances double-mount and double-connect**
  → the `origin` filter (ADR-0002), plus a test that stubs `window.WebSocket`
  and asserts exactly one construction per start. Prove-it-can-fail by
  deleting the guard.
- **Rebuilding the view breaks selectors the suites depend on** → keep
  `.body-double-header`, `.body-double-controls`, `.split-terminal`, and a
  root element matching `[x-show*="body-double"]`. Run the seven affected
  files as a green baseline *before* touching markup, and diff.
- **The `x-show`/`ttyd_port` class of bug recurs** → the new terminal pane is
  gated on `terminalMode`, a field the console itself owns and writes, not on
  remote state written by a retired code path. Add a geometry assertion that
  the terminal pane occupies a non-zero box after start, so "silently hidden"
  fails loudly.
- **`terminalPanel()` sits dead in the file for one change window** → comment
  naming ADR-0004 and the retirement change; skipped tests carry the same
  reference.
- **Body-double activity text pollutes topic-keyed analytics** → accepted and
  recorded in ADR-0001; the fix (session-type discriminator with a real
  reader) is deliberately deferred until something needs to branch on it.
- **Stale install masks the fix** → `uv tool install --force --reinstall -e
  packages/studyloop` before any browser verification, never from a worktree.

## Migration Plan

Frontend-only plus one backend list entry; no data migration, no API version
bump. Rollback is `git revert` of a single commit. Deploy is a page reload —
there is no build step (Alpine + HTMX served as static files).

Sequence: green baseline → `origin` plumbing (both dispatchers + the study
console) → Body Double rebuild → removals → tests and geometry assertions →
reinstall → browser verify all three transports → local commit. Never push.

## Open Questions

1. Should the Body Double picker carry an energy slider at all? Included for
   symmetry and because `energy` is a required-ish field on
   `/api/session/start` (defaults to 5). If body doubling never reads energy
   downstream, this is a field that costs a decision for no benefit — a
   candidate for removal after first real use.
2. Does the Socratic persona actually intrude in a body-doubling session? If
   yes, that is the trigger for the session-type discriminator deferred in
   ADR-0001.
3. Should `bodyDoubleSession()` show elapsed session time separately from the
   Pomodoro, as `sessionTimer()` does? Deferred — the Pomodoro is the clock
   the learner watches in this mode.
