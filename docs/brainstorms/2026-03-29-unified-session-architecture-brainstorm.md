---
date: 2026-03-29
topic: unified-session-architecture
origin: live-testing-conversation
---

# Unified Session Architecture

## What We're Building

A unified session system where `studyctl` is the single entry point for all session types — from any terminal, any AI agent framework, any device. tmux is the session runtime; everything else (cmux, web dashboard, ttyd) is a viewport into it.

The same command works everywhere:
- Terminal: `studyctl study "Python Decorators" --energy 7`
- Claude Code: `/studyctl study "Python Decorators" --energy 7`
- Gemini: `@studyctl study "Python Decorators" --energy 7`
- Kiro: equivalent invocation

The CLI creates the tmux session, sets up the pane layout, launches the AI agent with the right persona, and starts the dashboard. The user picks up on whatever device and room is convenient.

## Problem Statement

The current Phase 1-2 implementation has fragmented entry points:
- `studyctl session start` creates infrastructure but no visual environment
- The agent protocol tells agents to write IPC files, but setup is manual
- The web dashboard is a separate `studyctl web` command
- cmux dashboard is agent-protocol-only (no CLI orchestration)
- No terminal multiplexer integration — the user has to arrange panes manually
- No way to start a study session from a phone or tablet and have it "just work"

The goal: one command creates the complete environment — agent, timer, dashboard, panes — and it's accessible from any device on the network.

## Session Types

All session types share the same pane layout. The `--mode` flag changes the agent's behaviour, not the infrastructure.

| Mode | CLI | Agent role | Timer default |
|------|-----|-----------|---------------|
| Study | `studyctl study "topic" --agent claude` | Socratic mentor, agent drives | Elapsed + thresholds |
| Co-study | `studyctl study "topic" --mode co-study` | Available, Socratic, user drives (watching videos, exercises) | Pomodoro |
| Problem-solve | `studyctl study "Fix auth bug" --mode problem-solve` | Collaborative pair | Elapsed |
| Course | `studyctl study --course "ZTM-DE" --chapter 3` | Guided by course material | Pomodoro |
| eBook | `studyctl study --ebook ~/Books/fluent-python.pdf --chapter 5` | Chapter-guided | Pomodoro |

`--agent` is optional on all modes — auto-detects if omitted (claude → gemini → kiro → opencode).

Every session has: agent pane, timer, activity tracking, parking lot, session logging.

## Architecture

### Core Insight: tmux is the Session Runtime

tmux manages the actual session — panes, layout, persistence. Everything else is a viewport:

```
tmux session "studyctl-{session_id}"
  │
  ├── Pane 0 (main): AI agent runs here
  │   (claude / gemini / kiro with study-mentor persona)
  │
  └── Pane 1 (sidebar): Timer + activity + counters
      (either TUI widget or plain formatted text)
```

Viewports read from the same source:

| Viewport | How it works | When to use |
|----------|-------------|-------------|
| tmux native | Direct terminal access | At the desk |
| cmux | Enhanced MCP-controlled panes (macOS) | Ghostty users |
| ttyd | tmux pane served over HTTP/websocket | Browser, tablet, phone |
| Web dashboard | SSE-powered ambient display | Phone on desk, ambient monitor |

### Two-Port Model

| Port | Service | Purpose | LAN exposure | Auth |
|------|---------|---------|-------------|------|
| 8567 | Web dashboard | Read-only: timer, activity, counters | Safe | Optional |
| 7681 | ttyd terminal | Interactive: full agent session | Password-protected | Required |

```
$ studyctl study "Decorators" --energy 7 --lan

Study session started: Decorators (energy: 7/10)

  Dashboard:  http://192.168.125.22:8567/session
  Terminal:   http://192.168.125.22:7681 (password required)

  ! LAN mode: terminal is accessible on your network.
  Set a password in ~/.config/studyctl/config.yaml
  or use: studyctl config set web.password <password>
```

### Always-On Server

The primary use case: Mac Mini (or any always-on machine) runs `studyctl study`. The session persists indefinitely. Access from any device:

- **Desk**: Mac Mini directly (tmux native)
- **Sofa**: iPad via Safari (dashboard + ttyd terminal)
- **Quiet room**: Laptop via browser or SSH + tmux attach
- **Phone**: Dashboard-only (timer visible while walking to kitchen)
- **Work**: Sync DB before leaving, full local experience on laptop, resync when home

Session state (IPC files, DB) lives on one machine. No sync needed for real-time updates — ttyd and the dashboard both read the same files. The existing cross-machine sync handles offline/remote scenarios.

### Pane Layout

One layout for all session types:

```
┌──────────────────────────────────┬──────────────┐
│                                  │ ⏱ 12:34      │
│  Agent pane                      │ ████████░░ G  │
│                                  ├──────────────┤
│  AI mentor runs here             │ ACTIVITY      │
│  (claude/gemini/kiro)            │ ✓ Spark parts │
│                                  │ ★ ECMP bridge │
│  User types questions,           │ ▲ SQL windows │
│  agent responds Socratically     │ ○ Parked: GIL │
│                                  ├──────────────┤
│                                  │ ✓3  ○1  ▲2   │
└──────────────────────────────────┴──────────────┘
```

Web dashboard with embedded terminal (ttyd):

```
┌──────────────────────────────────┬──────────────┐
│                                  │ ⏱ 12:34      │
│  ttyd iframe/embed               │ ████████░░ G  │
│  (password-protected)            │ [Pause][Reset]│
│                                  ├──────────────┤
│  Full terminal interaction       │ ACTIVITY      │
│  Same tmux pane as native        │ ✓ Spark parts │
│                                  │ ★ ECMP bridge │
│                                  │ ▲ SQL windows │
│                                  │ ○ Parked: GIL │
│                                  ├──────────────┤
│                                  │ ✓3  ○1  ▲2   │
└──────────────────────────────────┴──────────────┘
```

### Timer Modes

Two timer modes, defaulted by session type but always overridable:

| Mode | Behaviour | Default for |
|------|-----------|-------------|
| Elapsed | Counts up, colour transitions at energy thresholds (green/amber/red from break-science.md) | study, problem-solve |
| Pomodoro | Counts down (25/5 or custom), cycle tracking, break prompts | co-study, course, ebook |

Both are: pausable, resumable, resettable, colour-coded, visible in all viewports.

Override: `studyctl study "topic" --timer pomodoro` or `--timer elapsed`

### Aesthetic tmux Config

studyctl ships a tmux config that makes the session look polished. Users don't need tmux proficiency — the agent controls everything.

Based on catppuccin theme with standard plugin (not fork):
- Top status bar showing session topic, timer, energy level
- Clean pane borders with lines around each pane
- Colour scheme matching the web dashboard (Tokyo Night / catppuccin)
- Minimal keybindings (agent handles pane management)

Installed via:
- `studyctl setup` adds the tmux config
- Or TPM plugin: `set -g @plugin 'netdevautomate/studyctl-tmux'`

If user has an existing tmux config, studyctl uses a session-specific config overlay (`tmux -f`) that doesn't conflict.

### Agent Integration

From inside an agent framework (Claude Code, Gemini, Kiro):

```
/studyctl study "Decorators" --energy 7
```

This spawns a **subagent in a new tmux window** rather than reconfiguring the current session:
- Current coding session is untouched
- Study session opens in a new tmux window with the full layout
- Agent launches with study-mentor persona
- When session ends, the window closes cleanly
- User switches back to their coding session

From a bare terminal:

```
studyctl study "Decorators" --energy 7
```

This creates the tmux session and launches the agent directly. Same layout, same experience.

### Terminal Multiplexer Detection

```
studyctl study "Decorators"
  │
  ├─ Is cmux available? → Use cmux MCP for enhanced pane control
  ├─ Is tmux available? → Create tmux session with studyctl layout
  ├─ Neither? → Install tmux (prompt or auto via studyctl setup)
  └─ --web flag? → Also start ttyd + web dashboard
```

tmux is the baseline. cmux is an enhancement layer. Neither requires the user to know tmux commands.

## Key Decisions

- **tmux is the runtime**: Not cmux, not a custom TUI. tmux is universal, persistent, and has the richest ecosystem. cmux enhances it but doesn't replace it.
- **One layout, all modes**: Session type changes agent behaviour, not pane structure. Keeps the code simple and the UX consistent.
- **Two ports**: Dashboard (read-only, safe) + terminal (interactive, auth'd). Clean security boundary.
- **Agent as subagent**: From within an agent framework, spawn a new window — don't hijack the current session.
- **Ship the aesthetic**: tmux config included. Users shouldn't need to configure tmux to get a good experience.
- **Sync still works**: Always-on server is primary, but cross-machine sync means offline work is fully supported.

## Speech-to-Text Recommendations

For study sessions — especially from a sofa, tablet, or quiet room — speech-to-text dramatically reduces friction. Instead of typing questions to the agent, speak them. This is particularly valuable for:
- AuDHD learners who articulate better verbally than in writing
- Socratic sessions where you're thinking out loud
- Mobile/tablet use where typing is slow

Recommended options (document in README):

| Tool | Platform | Cost | Key feature |
|------|----------|------|-------------|
| [Warp](https://warp.dev) | macOS, Linux | Free | Built-in terminal with speech-to-text (now uses Wispr Flow). Best option if users are willing to switch terminals. |
| [Handy](https://handy.computer/) | Universal (browser) | Free | Works anywhere, no install. Good fallback for any platform. |
| [Wispr Flow](https://wispr.flow) | macOS | Paid | System-wide dictation with automatic um/ah/correction removal. Works in any app including terminal emulators. Best for users who want speech-to-text everywhere, not just in the study session. |

Note: Warp now integrates Wispr Flow's engine, making it the single best option for users who want a terminal + speech-to-text in one tool. The combination of Warp terminal + ttyd web access gives speech-to-text on desktop and touch input on tablet.

## UX Enhancements

### 1. "Where was I?" Session Recovery

The hardest moment for AuDHD isn't during a session — it's coming back after a break or the next day. When the tmux session is still alive:

```
studyctl study --resume
```

Agent reads `session-topics.md`, the last few exchanges, and gives a 3-line summary: "We were working on X, you'd just got Y, we were about to tackle Z." Zero re-orientation friction. The tmux session + IPC files make this trivial — the transcript is already there.

This also works across devices: start on Mac Mini, walk away, come back on iPad, `--resume` gets you oriented instantly.

### 2. Quick Capture Hotkey

During a session, you think of something but don't want to break flow. A tmux keybinding (e.g., `prefix + p`) opens a floating popup via `tmux display-popup`:

```
┌─ Quick Park ──────────────────┐
│ > How does asyncio compare to │
│   threading?                  │
└───────────────────────────────┘
```

Hits Enter, `studyctl park` runs, popup closes, back to session. Two seconds, no context switch. Combined with speech-to-text (Warp/Wispr), you can voice-park a thought without touching the keyboard.

### 3. "I'm Stuck" Dashboard Buttons

For tablet/sofa use — prominent buttons on the web dashboard that send signals to the agent without typing:

```
[I'm stuck]  [Different angle]  [Bridge to networking]
```

Why buttons instead of typing:
- Typing "I don't understand" feels like an admission of failure (RSD)
- Tapping a button is emotionally neutral
- On a tablet, buttons are faster than a keyboard
- The "Bridge to networking" button is personalised — it tells the agent to map the concept to the user's strongest domain

The agent receives the signal via IPC (a command file or the session state) and shifts approach.

### 4. Energy Tracking Over Time

Energy is declared at session start (1-10). Track it and surface patterns:

```
studyctl streaks

  This week: 4 sessions, avg energy 6.2
  Your best sessions (most wins): energy 7-8, mornings
  Pattern: Tuesdays are consistently low energy (3-4)
```

This isn't just data — it's ammunition against the AuDHD guilt cycle. "Why can't I focus today?" Answer: because it's Tuesday and your energy is always 3 on Tuesdays. That's not a failure, that's a pattern. Reframe from personal failing to predictable rhythm.

Data needed: study_sessions table already has energy_level and started_at. Add a `studyctl insights` or extend `studyctl streaks` to compute correlations.

### 5. Break Activity Suggestions

`break-science.md` already documents good vs bad break activities. When the timer hits a break threshold, the dashboard shows a rotating suggestion:

```
  Break: Stand up, walk to the kitchen.
  (Not: phone, not: social media, not: YouTube)
```

PDA-sensitive language — information, not instruction. Rotate through the good activities list so it's not repetitive. The data is already written; this just surfaces it at the right moment.

Implementation: the SSE stream or the agent pushes a break suggestion when the timer phase transitions. The web dashboard renders it in the timer message area.

### 6. Session Warmup from Parked Topics

At session start, before diving into the main topic, the agent automatically surfaces unresolved parked topics from previous sessions:

```
  Before we start "Python Classes" — you parked 2 topics last time:
    ○ How does asyncio compare to threading?
    ○ GIL vs multiprocessing

  Want to tackle one of these first, or park them again?
```

Why this matters: unresolved questions create background cognitive load. Explicitly choosing to defer them ("park again") frees that load. Choosing to tackle one gives a quick win before the main session.

Implementation: `get_unscheduled_parked_topics()` already exists in `parking.py`. The agent protocol calls it at session start and presents the results. Re-parking updates the `parked_at` timestamp so they don't surface every single session.

## Open Questions

1. **Which agent to launch?** CLI flag, not config — keeps one config across machines while choosing agent per-session: `studyctl study "topic" --agent claude`. Auto-detect installed agents as fallback if `--agent` not specified (order: claude → gemini → kiro → opencode).
2. **ttyd as dependency**: Should ttyd be a required install or optional? It's a single binary (`brew install ttyd`) but it's another dep. Could be installed by `studyctl setup` only when `--web` is used.
3. **tmux session persistence**: Should the tmux session survive `studyctl session end`? Useful for reviewing the conversation, but clutters the session list. Probably: keep it for 10 minutes, then auto-close.
4. **Password storage**: Never plaintext. Recommended: 1Password via `op` CLI (`op read "op://Personal/studyctl-lan/password"`). Fallback: age-encrypted file (`~/.config/studyctl/lan.age`). Setup flow: `studyctl config set-password` detects `op` first, falls back to `age`, refuses to store plaintext. Even for a personal tool — passwords in config files get committed to git, copied between machines, left in backups.
5. **Course/eBook integration**: How does `--course "ZTM-DE"` map to actual files? Needs a course registry in config.yaml or a convention-based path.

## Next Steps

1. Write implementation plan (`/ce:plan`) covering:
   - New `studyctl study` command (replaces `studyctl session start`)
   - tmux session creation + layout
   - ttyd integration
   - tmux config / TPM plugin
   - Agent launcher
   - Web dashboard updates (embedded terminal)
2. Phase the work: tmux foundation first, then ttyd, then aesthetic polish
3. Existing Phase 1-2 infrastructure (IPC files, SSE, parking lot, migration v14) carries forward unchanged

## Sources

- [cmux](https://github.com/manaflow-ai/cmux) — Ghostty MCP terminal (macOS)
- [cmuxlayer](https://github.com/EtanHey/cmuxlayer) — cmux MCP server
- [tmux-mcp](https://github.com/jonrad/tmux-mcp) — tmux MCP server (proof of concept)
- [ttyd](https://github.com/tsl0922/ttyd) — Share terminal over the web (built-in basic auth)
- [omerxx/dotfiles](https://github.com/omerxx/dotfiles/tree/master/tmux) — Aesthetic tmux config reference (catppuccin, top bar, clean borders)
- [catppuccin/tmux](https://github.com/catppuccin/tmux) — Standard catppuccin tmux plugin
- Existing: `docs/brainstorms/2026-03-28-live-study-session-dashboard-brainstorm.md`
- Existing: `agents/shared/break-science.md` (timer thresholds)
