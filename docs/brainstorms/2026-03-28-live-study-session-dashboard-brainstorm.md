---
date: 2026-03-28
topic: live-study-session-dashboard
---

# Live Study Session Dashboard

## What We're Building

A real-time study session dashboard that provides ambient visual prompts to AuDHD learners during AI-mentored study sessions. The dashboard shows an energy-adaptive timer, color-coded topic tracking with struggle/insight indicators, a parking lot for tangential questions, and a mini-wins counter — all driven by the AI agent writing to shared files, with the user passively viewing.

Three viewports, prioritised by implementation cost:
- **cmux native** (cmux users) — agent controls panes directly via MCP tools. Zero new application code. Highest priority.
- **Web PWA** (non-technical users / mobile) — browser tab, works on phone as ambient dashboard
- **Textual TUI** (terminal users without cmux) — lowest priority, cmux covers this use case better

The file-IPC protocol remains the persistence layer for all viewports. cmux adds a direct MCP channel where the agent writes to panes without file polling.

### cmux (added 2026-03-28, post-brainstorm)

[cmux](https://github.com/manaflow-ai/cmux) is a Ghostty-based terminal with an MCP server that gives the AI agent programmatic control over panes, progress bars, status indicators, notifications, and embedded browser surfaces. Since it's already installed and running, it eliminates the three problems that led us to reject tmux/Zellij:

1. No external install needed (already running)
2. Agent has direct MCP control over panes (`new_split`, `send_input`, `set_status`, `set_progress`, `notify`)
3. User doesn't interact with the multiplexer — agent controls everything

Key MCP tools that map to our dashboard design:

| Dashboard feature | cmux MCP tool | How |
|------------------|---------------|-----|
| Timer progress bar | `set_progress` | Sidebar progress 0.0→1.0, color via energy thresholds |
| Wins/Parked/Review counters | `set_status` | Sidebar key-value pairs with hex colors and icons |
| Topic activity pane | `new_split` + `send_input` | Split pane, write formatted topic lines |
| Break reminders | `notify` | Banner notification — PDA-sensitive, information not instruction |
| Tab naming | `rename_tab` | "Study: Spark Internals" |
| Session summary | `send_input` | Write summary view to the dashboard pane |
| Embedded web dashboard | `browser_surface` | Open web PWA in a cmux browser pane |

## Why This Approach

From a 5-agent codebase review (2026-03-28), the three biggest gaps in the current system are:

1. **Parking lot has zero persistence** — documented in 4 agent framework files but no DB table, no CLI, no API. Tangential topics are lost when sessions end.
2. **No intra-session visual feedback** — `studyctl wins`, `struggles`, `resume` exist as cross-session analytics but nothing shows progress in real time during a session.
3. **The "any topic" bridge configure flow was never implemented** — architecture supports it but the interactive setup command doesn't exist.

The dashboard closes gaps 1 and 2. Gap 3 is a separate but related piece of work.

## Key Decisions

### 1. Agent-initiated sessions, no explicit start question

The agent defaults to structured study mode with the timer running. No "structured or body doubling?" question — that's a demand that creates friction for PDA-sensitive users. If the agent detects low energy or disengagement mid-session (short answers, flat affect), it shifts to body doubling mode and the dashboard adapts: timer stays (hyperfocus protection), but topic tracking dims and check-ins become minimal.

**Rationale:** The Express Start protocol already says "skip the full protocol if the learner dives in." Consistent with existing AuDHD framework. Observation > interrogation.

### 2. Combined activity pane (topics + insights + wins + parking lot)

One unified pane rather than 4-5 separate panes. Color coding does the cognitive work:

```
┌───────────────────────────────────────────────┐
│ ⏱  23:41  [████████████░░░░]  🟢              │
├───────────────────────────────────────────────┤
│ SESSION ACTIVITY                              │
│ 🟢 Figured out Spark partitioning             │  ← Win
│ 🟡 SQL window functions (re-explained twice)  │  ← Struggling (amber)
│ 🟢 Connected ECMP → partition distribution    │  ← Bridge insight
│ 🔴 Spark shuffle internals (3rd attempt)      │  ← Sustained struggle (red)
│ ⬜ Parked: GIL vs multiprocessing             │  ← Deferred tangent
├───────────────────────────────────────────────┤
│ 🏆 WINS: 3  │  📌 PARKED: 1  │  ⚠️ REVIEW: 2 │
└───────────────────────────────────────────────┘
```

**Rationale:** Multiple panes = more visual noise. AuDHD users need "not overwhelming." One stream with colors is scannable peripherally. The wins counter at the bottom is always visible — the RSD antidote.

### 3. Agent declares topic status, dashboard just renders

The agent writes structured status to `session-topics.md`:

```markdown
- [09:14] Spark partitioning | status:learning | Basic concepts clicked
- [09:31] SQL window functions | status:struggling | Re-explained PARTITION BY twice
- [09:45] ECMP → partition distribution | status:insight | Student-generated bridge
- [09:52] Spark shuffle | status:struggling | Third attempt at explanation
- [10:03] Spark shuffle | status:win | Finally grasped it after code example
```

Status values: `learning`, `struggling`, `insight`, `win`, `parked`

The dashboard parses these lines and renders with appropriate colors. No struggle-detection algorithm in the viewport — the agent has the conversational context to make this judgment. The viewport stays dumb and reliable.

**Amber/red auto-logging:** Any topic that reaches `struggling` status gets automatically written to the session DB as a struggle topic (feeds into `studyctl struggles` and spaced repetition scheduling). This happens in the agent protocol, not the dashboard.

### 4. Energy-adaptive timer thresholds

Timer color transitions match the existing break-science.md intervals:

| Energy | Green → Amber | Amber → Red | Source |
|--------|--------------|-------------|--------|
| High (7-10) | 25 min | 50 min | break-science.md micro/short intervals |
| Medium (4-6) | 20 min | 40 min | break-science.md micro/short intervals |
| Low (1-3) | 15 min | 30 min | break-science.md micro/short intervals |

Energy level comes from `session-state.json` (written by agent at session start, updated if energy shifts mid-session). Timer reads the energy value and adjusts thresholds dynamically.

Timer messaging is PDA-sensitive (information, not instruction):
- Green → Amber: no message (just the color shift)
- Amber → Red: subtle text: "Your brain's been at this for a while."
- Red sustained: "Just flagging it." (then back off)

### 5. Session end: summary view + wind-down protocol

When the agent signals session end, the dashboard transitions to a summary view:

```
┌───────────────────────────────────────────────┐
│ SESSION COMPLETE — 47 minutes                 │
├───────────────────────────────────────────────┤
│ 🏆 WINS                                      │
│ ✓ Figured out Spark partitioning              │
│ ✓ Connected ECMP → partition distribution     │
│ ✓ Spark shuffle — grasped after code example  │
├───────────────────────────────────────────────┤
│ 📚 FOR NEXT SESSION                           │
│ ⚠️ SQL window functions — needs more practice │
│ 📌 GIL vs multiprocessing — parked            │
├───────────────────────────────────────────────┤
│ 🧠 CONSOLIDATION                              │
│ Stand up. Walk to the kitchen. Put the        │
│ kettle on. Avoid your phone for 10-15 min —   │
│ your brain will replay this at 20x speed.     │
└───────────────────────────────────────────────┘
```

This reflects the wind-down protocol (already in `wind-down-protocol.md`):
- Phase 1: Session wrap — wins, struggles, parking lot
- Phase 2: Consolidation guidance — concrete first step (ADHD transition support)
- Phase 3: Next session suggestion — what to review, when

The wins section is prominent and first. The struggles are framed as "for next session" not "you failed at." The consolidation guidance uses the concrete-first-step pattern from the existing protocol.

### 6. File-IPC protocol

The agent writes to files in `~/.config/studyctl/`:

| File | Purpose | Format |
|------|---------|--------|
| `session-state.json` | Session metadata (energy, topic, mode, study_session_id) | JSON |
| `session-topics.md` | Topic tracking with status indicators | Markdown with structured `[time] topic \| status:X \| note` lines |
| `session-parking.md` | Parking lot items (agent appends, never overwrites) | Markdown bullet list |

Both viewports poll these files (2s interval for TUI via `run_worker`, polling endpoint for web PWA).

At session end:
1. `session-topics.md` → Obsidian vault as session notes (with frontmatter: date, topic, duration, wins count)
2. `session-parking.md` → parsed → inserted into `parked_topics` table (migration v14) with `status='pending'`
3. Struggle topics → written to `study_progress` with appropriate confidence level
4. Both temp files archived/deleted

### 7. Viewport parity contract

All three viewports MUST support the core dashboard features:

| Feature | cmux native | Web PWA | Textual TUI |
|---------|-------------|---------|-------------|
| Energy-adaptive timer | `set_progress` (sidebar) | Alpine.js (client) | `reactive` widget |
| Combined activity pane | `send_input` to split pane | SSE + HTMX | `RichLog` widget |
| Color-coded status | `set_status` with hex colors | CSS variables | Rich markup |
| Summary counters | `set_status` key-values | OOB swaps | Counter widget |
| Break reminders | `notify` banner | Browser notification | Terminal bell |
| Session end summary | `send_input` summary view | HTML template swap | `ContentSwitcher` |
| Wind-down protocol | Displayed in activity pane | Displayed in page | Displayed in widget |

cmux only:
- Sidebar progress bar (native, always visible)
- Sidebar status indicators (native, always visible)
- Embedded browser pane (`browser_surface` for web PWA alongside terminal)
- Spawn additional agents (`spawn_agent`)

Web PWA only:
- Mobile layout (phone as ambient dashboard)
- Dyslexic font toggle (existing)
- Touch-friendly controls
- Flashcard/quiz review (existing)

Textual TUI only (lowest priority — cmux covers terminal users):
- Keyboard shortcuts for quick actions
- Standalone terminal app (no cmux dependency)

### 8. Database changes (migration v14)

New `parked_topics` table:

```sql
CREATE TABLE IF NOT EXISTS parked_topics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    study_session_id TEXT REFERENCES study_sessions(id) ON DELETE SET NULL,
    session_id TEXT REFERENCES sessions(id) ON DELETE SET NULL,
    topic_tag TEXT,
    question TEXT NOT NULL,
    context TEXT,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK(status IN ('pending', 'scheduled', 'resolved', 'dismissed')),
    scheduled_for TEXT,
    resolved_at TEXT,
    parked_at TEXT NOT NULL DEFAULT (datetime('now')),
    created_by TEXT DEFAULT 'agent'
);
```

Status lifecycle: `pending → scheduled → resolved` or `pending → dismissed`

Six API functions in `history.py`: `park_topic()`, `get_parked_topics()`, `get_unscheduled_parked_topics()`, `schedule_parked_topic()`, `resolve_parked_topic()`, `dismiss_parked_topic()`.

## Open Questions

1. **Accessibility:** DECIDED — use shapes + colors together. Icon vocabulary:
   - `✓` Win (green) — mastered or insight moment
   - `▲` Struggling (amber/red) — needs re-explanation or repeated questions
   - `◆` Learning (neutral/blue) — normal topic progression
   - `○` Parked (grey) — tangential, deferred to future session
   - `★` Insight (green) — aha moment or bridge connection
   Information is never color-only. Shapes carry meaning independently for colorblind users.
2. **Sound:** Should the timer color transitions have an optional subtle audio cue? The TTS system already exists (`study-speak`). A soft chime at amber might help users who aren't watching the screen.
3. **Multiple viewports simultaneously:** Can a user have both the web PWA and TUI open? Since both poll the same files, this should work — but we should test for race conditions on the polling endpoint.
4. **Offline/crash recovery:** If the session crashes without running the end protocol, parked topics should already be in the DB (written immediately on `park_topic()`, not batched at session end). The temp files remain on disk for manual recovery. Need to confirm this pattern.
5. **Bridge configure flow:** Should `studyctl bridge configure` (the interactive 4-step discovery for non-networking users) be part of this work or a separate effort? It's related but not blocking.

## Implementation Approach

**Recommended: cmux native first (nearly free), then Web PWA, Textual TUI last.**

cmux requires almost zero new application code — the agent calls MCP tools directly. This validates the dashboard concept immediately with the primary user. The web PWA follows for mobile/browser users. Textual TUI drops to lowest priority since cmux covers terminal users better.

Phased:
1. **Foundation** — Migration v14, file-IPC protocol, `studyctl session start/end` CLI, agent protocol updates — **DONE** (committed `72b1ec5`)
2. **cmux native viewport** — Agent protocol additions for MCP tool calls during sessions. Dashboard pane layout, sidebar progress/status, notifications. Near-zero code — primarily agent prompt engineering.
3. **Web PWA live session mode** — SSE endpoint, session activity pane, Alpine.js energy-adaptive timer, summary view
4. **Polish** — Obsidian export, `suggest.py` backport for parking lot surfacing, bridge configure
5. **Textual TUI session view** (if needed) — Same layout, `run_worker` polling, Rich markup for colors

Base branch: `compact/core-only` with `resume` and `streaks` added back.

## Next Steps

→ `/ce:plan` for implementation details
