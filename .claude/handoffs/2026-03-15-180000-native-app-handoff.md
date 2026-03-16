# Handoff: Native macOS/iOS App — Socratic Study Mentor

## Session Metadata
- Created: 2026-03-15 18:00:00
- Project: /Users/user/code/personal/tools/Socratic-Study-Mentor
- Branch: feat/phase9-tui-polish (pushed to origin)
- Session duration: ~4 hours (Phase 9 implementation + PWA web app)

## Current State Summary

Phase 9 TUI Polish is complete with 23 commits on `feat/phase9-tui-polish`. Beyond the original plan, a full PWA web app was built (`studyctl web`) with flashcard/quiz review, voice output, Pomodoro timer, and accessibility features. The branch is pushed and ready for PR/merge. The next task is building native macOS and iOS apps in `/Users/user/code/personal/tools/apps/`.

## What Was Built

### Phase 9 (original plan — all complete)
- A5: `get_due_cards()` ROW_NUMBER() window function fix
- A1: Export progress bar per-source stats fix
- A2: `list_concepts()` + TUI Concepts tab
- A6: Narrow `suppress(Exception)` at 3 call sites
- A3: Course picker ModalScreen for multiple directories
- A4: Retry wrong answers mode (r key, in-memory, no SM-2 during retry)
- B1-B4: Documentation + SVG screenshot

### Beyond plan — TUI enhancements
- `tui.theme` config option (dracula, nord, etc.)
- Voice toggle focus fix (`can_focus = True`)
- Dyslexic-friendly mode (`o` key toggle, CSS class)

### Beyond plan — PWA Web App (`studyctl web`)
- Zero-dependency web server (stdlib `http.server`)
- Tokyo Night dark theme, responsive for mobile/tablet
- Flashcard mode with tap-to-flip
- Quiz mode with A-D options and rationale display
- SM-2 spaced repetition recording (skipped during retry)
- Source/chapter filter — study specific chapters
- Card count limiter (10/20/50/100/All)
- Due cards badge on course picker
- Session history with recent scores
- 90-day study activity heatmap
- Pomodoro timer (25min study / 5min break, audio chime, browser notifications)
- Voice via Web Speech API — read-once button (T key) + auto-voice toggle (V key)
- OpenDyslexic font toggle (Aa button)
- Dark/light theme toggle (sun icon)
- PWA installable (manifest + service worker)
- LAN accessible by default (0.0.0.0:8567)
- Smart course naming (parent dir name when basename is "downloads")

## Native App Task

### Target Directory
```
/Users/user/code/personal/tools/apps/
├── iOS/
│   └── SocraticMentor/
└── macOS/
    ├── OutlookRAG/
    └── SocraticMentor/
```

### What the Native App Should Do

Build a native macOS app first (then iOS) that provides the same study experience as the PWA but as a native app. Two approaches:

**Option A: WebView wrapper (fastest)**
- SwiftUI app with WKWebView pointing at `studyctl web` server
- Native menu bar integration
- System notifications (instead of browser notifications)
- Launch `studyctl web` as a background process on app start
- macOS menu bar icon to start/stop server

**Option B: Native SwiftUI (best UX)**
- Read the same flashcard/quiz JSON files directly
- Implement card flip UI natively
- Use AVSpeechSynthesizer for voice (Siri voices, much better quality)
- Native spaced repetition with SM-2 (talk to same SQLite DB)
- Native Pomodoro timer with system notifications
- OpenDyslexic font support via bundled font
- Sync with the same `~/.config/studyctl/sessions.db`

### Key Architecture Decisions

1. **Shared data**: Both apps should read/write the same SQLite DB at `~/.config/studyctl/sessions.db` and the same flashcard JSON files configured in `~/.config/studyctl/config.yaml`
2. **Schema**: `card_reviews` and `review_sessions` tables (see `packages/studyctl/src/studyctl/review_db.py`)
3. **SM-2 algorithm**: Simplified — correct doubles interval, incorrect resets to 1. Retry sessions skip SM-2.
4. **JSON format**: Flashcards `{"cards": [{"front": "...", "back": "..."}]}`, Quiz `{"questions": [{"question": "...", "answerOptions": [...]}]}`
5. **Config**: YAML at `~/.config/studyctl/config.yaml` with `review.directories` and `tui` sections

### Critical Files to Reference

| File | Purpose |
|------|---------|
| `packages/studyctl/src/studyctl/review_db.py` | SM-2 algorithm, DB schema, record functions |
| `packages/studyctl/src/studyctl/review_loader.py` | JSON flashcard/quiz loading, directory discovery |
| `packages/studyctl/src/studyctl/web/server.py` | API endpoints (courses, cards, review, history) |
| `packages/studyctl/src/studyctl/web/static/app.js` | Full UI logic, voice, pomodoro, all features |
| `packages/studyctl/src/studyctl/web/static/style.css` | Tokyo Night theme, all component styles |
| `~/.config/studyctl/config.yaml` | User config (directories, theme, TTS settings) |

### User Preferences (from CLAUDE.md)

- AuDHD learner — needs dopamine-friendly UI, clear visual feedback
- OpenDyslexic font support is important
- Voice output valued (Siri voices preferred)
- Dark theme preferred
- Concrete examples over abstract docs
- Senior professional — don't over-explain basics

## Environment

- macOS (Apple Silicon)
- Xcode installed
- Swift/SwiftUI for native apps
- Python 3.12 with uv for the backend
- GitHub repo: NetDevAutomate/Socratic-Study-Mentor
