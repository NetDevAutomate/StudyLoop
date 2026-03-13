---
title: "Marathon Session: Artefact Store, TUI, and Cross-Machine Sync"
date: 2026-03-13
tags: [architecture, notebooklm, tui, sync, dns, lfs, pwa]
repos: [socratic-study-mentor, notebooklm-repo-artefacts, notebooklm-pdf-by-chapters, artefact-store]
---

# Marathon Session Learnings — 2026-03-13

## Problem: Binary artefacts bloating source repos (385MB clones)

### Solution: Centralised artefact-store with GitHub Pages

- Dedicated `artefact-store` repo serves all artefacts via `artefacts.netdevautomate.dev`
- Source repos get README links only — zero binary files
- `--store` flag on pipeline/publish, configurable default via `~/.config/repo-artefacts/config.toml`
- `migrate` command handles the full move: copy → push store → update README → `git rm` → push source
- `validate --all` checks every artefact link, `clean --delete` removes orphans

**Key pattern:** Store repo cloned shallowly (`--depth 1`), cached in `~/.cache/`, with push conflict retry.

### What would have saved time
- Should have created the artefact-store FIRST, then built the pipeline integration. We built them in parallel which caused the git divergence headaches.

---

## Problem: NotebookLM infographic generation failing via API

### Root cause chain (3 bugs found):
1. **`is` vs `==` for IntEnum comparison** — `_delete_failed_by_type` wasn't matching failed artefacts
2. **Only deleting FAILED, not COMPLETED artefacts** — API refuses new generation when completed one exists
3. **Missing `orientation` and `detail_level` params** — API silently fails without these for infographics

### Solution
- Changed all enum comparisons to `==`
- Renamed to `_delete_existing_by_type(failed_only=False)` for initial requests
- Added `InfographicOrientation.LANDSCAPE` + `InfographicDetail.STANDARD` to generate kwargs
- Added diagnostic logging showing full `GenerationStatus` fields on failure

**Key pattern:** When an API returns a generic error, compare your call against a known-working client (the `notebooklm` CLI in this case) to find parameter differences.

---

## Problem: Cross-machine config with separate local/remotes sections

### Solution: Unified hosts with hostname auto-detection

```yaml
hosts:
  macmini:
    hostname: study-hub     # auto-detected via socket.gethostname()
    ip_address:
      primary: 192.168.1.22   # wired
      secondary: 192.168.1.12 # wifi fallback
```

- Same config file on all machines
- `session-sync` reads from studyctl's hosts config via `get_endpoints()` translation
- rsync tries primary IP, falls back to secondary
- First-time push auto-seeds remote DB via scp

**Key pattern:** `_quote_remote_path()` converts `~/...` to `"$HOME/..."` for SSH commands — `shlex.quote` prevents tilde expansion.

---

## Problem: Flashcard/quiz review only available via CLI

### Solution: Textual TUI with spaced repetition

- Self-contained `review_loader.py` (no cross-package imports — JSON format is the contract)
- `review_db.py` with SM-2 simplified algorithm (correct → increase interval, wrong → reset)
- `tui/study_cards.py` — keyboard-driven: Space (flip), y/n (score), v (voice toggle)
- Voice runs in background thread via study-speak/kokoro (optional, graceful fallback)

**Key pattern:** When two packages need to share data, copy the loader code (~60 lines) rather than creating a cross-package import dependency. The JSON format is the contract.

---

## Problem: LFS pointer mismatch on clone

### Root cause
Files committed before `git-lfs` filters were active on the committing machine. `.gitattributes` had the rules but the smudge/clean hooks weren't registered.

### Solution
`git rm --cached` + `git add` to re-add through LFS filters. Then `git filter-repo` to clean history.

**Key pattern:** Always run `git lfs install` on a new machine before committing to a repo with `.gitattributes` LFS rules.

---

## Problem: Cloudflare proxy blocking GitHub Pages DNS verification

### Solution
Set `proxied: False` (DNS-only) for the CNAME record. GitHub needs to see its own IP in DNS responses to verify the domain and provision the SSL cert.

**Key pattern:** Cloudflare proxy hides the real DNS target. GitHub Pages requires DNS-only mode for initial domain verification. Can optionally re-enable proxy after cert is provisioned.

---

## Problem: Install script didn't include TTS dependencies

### Root cause
`uv tool install agent-session-tools` created an isolated venv without the `[tts]` optional extras. `kokoro_onnx` import failed silently, falling back to macOS `say`.

### Solution
Install with extras: `uv tool install "agent-session-tools[tts]"`. Updated `install.sh` to detect `agent-session-tools` and include `[tts]`.

**Key pattern:** `uv tool install` creates isolated venvs. Optional dependencies MUST be specified explicitly — they're not inherited from the workspace.

---

## Architectural Decisions

| Decision | Rationale |
|----------|-----------|
| TOML for repo-artefacts config | stdlib `tomllib` in Python 3.11+, zero new deps |
| YAML for studyctl config | Already a dependency, human-friendly for multi-section config |
| SQLite `card_reviews` table in sessions.db | Reuse existing DB, feeds into spaced repetition |
| SM-2 simplified (not full algorithm) | Start simple, iterate. Full SM-2 adds complexity for marginal benefit. |
| PWA before native app | Validates UX at 10% of the effort. Build native only after patterns proven. |
| FastAPI + HTMX for web app | No JS build step, server-rendered, minimal dependencies |
| No cross-package imports for review data | JSON format is the contract. Copying 60 lines beats coupling two packages. |
