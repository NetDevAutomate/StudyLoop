# Session Handoff — Close-Out (2026-07-12, night)

**For:** the next Claude session (fresh context). This supersedes
`2026-07-12-session-handoff-post-fanout.md` — everything in that doc's
"needs fixing" sections is either landed or re-listed here. Read this doc,
then `git log --oneline 61a15fc..HEAD` on `main` for the commit narrative.

**Mission for the next session:** close this work out — push/PR (needs the
user's go-ahead), the manual desktop verification, and optionally the
next-slice lanes in §4.

---

## 1. Repo state (verified at handoff)

- Branch **`main` @ `0b29496`**, working tree clean, single worktree.
- Local `main` is **42 commits ahead of `origin/main`**. **Nothing pushed;
  no PR.** The user must approve any push.
- `feat/e2e-harness-and-hardening` is fully merged into main via no-ff
  merge `f76a4fa` — the branch can be deleted after push (`git branch -d`).
- OpenSpec change `complete-e2e-harness-and-desktop-mcp` is **archived**
  (`openspec/changes/archive/2026-07-12-complete-e2e-harness-and-desktop-mcp/`).

**Verification state on merged main (all run this session):**
- Full default suite: **2875 passed / 0 failed / 0 errors** (~110s)
- `ruff check .` clean repo-wide
- `openspec validate --all` → 9/9
- `mkdocs build --strict` (via `uv run --with mkdocs --with mkdocs-material
  python -m mkdocs build --strict` — mkdocs is NOT in the project venv) → OK
- Both new fixes verified with held-out gates (test fails on reverted code)
  and against the user's real vault / a real browser run.

## 2. What landed since the post-fanout handoff

| Commit | What |
|---|---|
| `0b0d189` | Handoff: logged the two user-reported defects with root-cause analysis |
| `d7973f4` | **Fix: vendor picker** — topics no longer listed as vendors; same-name vendors dedupe by name while course discovery walks ALL same-name dirs (verified: 12 vendors / 45 courses on the real vault) |
| `453dbdf` | **Fix: un-endable session** — native `confirm()` replaced with in-page `.end-confirm-overlay` (Keep going / End session / Escape); cancel-path e2e added |
| `c88272a` | CHANGELOG (both fixes + backfilled MCP-parity/tts/validation entries), web-ui spec (2 new requirements), handoff sync |
| `c7f91bc` | Gitignore harness-dropped tavily skill dirs (`.agents/`, `.pi/`, `agent/`, `skills-lock.json`) |
| `f76a4fa` | **Merge to main** (no-ff) |
| `0b29496` | OpenSpec change archived |

## 3. Corrections — do NOT re-learn these (additions to the post-fanout list)

The 7 corrections in `2026-07-12-session-handoff-post-fanout.md` §2 all
still hold (nav-store lock, no `tests/e2e/conftest.py`, `_helpers.run_async`,
addopts flags, subprocess-hosted e2e server…). New this session:

1. **Topic dirs vs vendor dirs are indistinguishable by shape.** Both sit
   directly under study roots. The ONLY discriminator is the configured
   `settings.topics[*].obsidian_path` set — `_options.py::_topic_dir_paths()`
   is the implementation. Never re-introduce shape-based heuristics.
2. **Stub `Settings` classes MUST set `obsidian_base`.** Without it,
   `_study_roots()` raises and silently falls back to scanning the REAL
   `~/Obsidian` vault — the test then passes/fails on the user's personal
   data. (Bit us this session; fixed in the new regression test.)
3. **Native browser dialogs are banned on the session-end path** — now a
   spec requirement (`openspec/specs/web-ui/spec.md`). Chrome auto-dismisses
   them in some focus states (embedded ttyd iframe). Any new destructive
   action in the web UI should use the `.end-confirm-overlay` pattern.
4. **After editing static assets, reinstall before any browser-driven
   test**: `uv tool install --force --reinstall ./packages/studyloop` AND
   the editable venv install — the e2e server serves installed assets, not
   the repo tree. (Standing lesson, re-confirmed.)

## 4. Outstanding work

### Needs the user (blocking close-out)
- ~~Push + PR~~ — **RESOLVED 2026-07-12 (later session): the user confirmed
  this repo is local-only by design. Never push; sync to the macmini
  happens via `~/code/personal/tools/dirsync`. "Commits ahead of origin"
  is NOT loss exposure here.**
- **Manual desktop verification** (~10 min, human-only): both apps are
  ALREADY WIRED (configs merged 2026-07-12, backups alongside; install
  needed the `[mcp,web,content]` extras — see `c175900`). Follow the new
  runbook `docs/desktop-mcp/manual-test-plan.md` (per-client checklists,
  mermaid flows, prompt scripts, results tables). User plans to run it
  2026-07-13.

### Next-slice candidates (descoped from the archived change; all parallel-safe)
- ~~Fake-agent PTY binary~~ — **DONE `45b9b13`**: `studyloop-fake-agent`
  console script + `fake` adapter (gated behind `STUDYLOOP_TEST_AGENT=1`);
  journey walks spawn→201→real WS (Origin header required)→bytes both
  ways→end-while-connected→`study_sessions` row; browser test sees
  "Connected · fake" in the real UI. Held-out gate proven.
- ~~Journey phases 2–4~~ — **DONE `45b9b13`**:
  `tests/e2e/test_journey_generate_review.py` — isolated tmp world, real
  Generate panel + stub backend → deck files ON DISK; real flashcards walk
  to summary; durable `card_reviews`/`review_sessions` rows asserted.
- ~~MCP explorer read tools~~ — **DONE `e215368`**: `get_lesson_tree`,
  `read_lesson`, `search_lessons` shipped; shared `resolve_lesson_path`
  traversal guard extracted into `explorer.py`; 21 tools total.
- ~~Run the Socratic judge live once~~ — **DONE `d5eb74a`**: the gateway
  probe skipped on 401 (no auth header) — fixed; judge executed live and
  PASSED (mentor reply judged Socratic by claude-opus-4-8).
- **Full 348-test e2e suite to completion** (>25 min). CI still has no e2e
  job. ~~Known pre-existing failure~~ — **DONE `d5eb74a`**:
  `test_generate_busy_response_shows_visible_conflict_state` was a test
  bug (unscoped `.form-error` locator hit the mastery panel too →
  Playwright strict-mode violation), not a product bug. Full browser smoke
  file now 9/9.

### Known-open defects — ALL RESOLVED 2026-07-12/13
- ~~`resolve_study_dirs()` bare `review:` crash + `study_paths` scalar
  explosion~~ — **FIXED `6b52a0d`** (`or {}` guard + scalar→list coercion).
- ~~Kiro exporter / gemini FK-swallow / aider ID duplication~~ — **FIXED
  `b909b46`**: ONE root cause (scrub_log/file_references FKs lacked
  ON DELETE CASCADE → migration 25) + kiro's real list-shaped entries
  (extraction 1369→3419 msgs on the live DB) + aider delete-on-update.
- ~~Scrubber unquoted AWS secrets~~ — **FIXED `6b52a0d`** (quotes optional,
  40-char base64 anchor keeps specificity).
- ~~`get_chapter_text` negative-chapter bug~~ — **FIXED `6b52a0d`**
  (`1 <= chapter <= len` lower bound).
- ~~LAN auth divergence~~ — **FIXED `4296941`** (real security hole: ttyd
  side-channel unauthenticated when `--password` not persisted; creds now
  single-sourced from `app.state`, fail-closed).

### Roadmap (honest `[ ]`)
- Release automation (`release.yml` / `pre-release.yml` don't exist).
- ~~Learner-first UX UI slice~~ — **DONE `102e82f`**: Today landing view
  (new default), context-aware resume (+ `GET /api/session/last`),
  quick-park brain-dump (+ `POST /api/backlog/park`), park-first friction
  modal (+ `POST /api/backlog/demote`), toast primitive, courses-loading
  tri-state. Also fixed the TTS voice-ignored + overlapping-playback bugs
  (`tts-engine.js` generation counter + voice restore).
- CI e2e job (now unblocked by the fake agent — run
  `STUDYLOOP_TEST_AGENT=1` journeys in CI).
- Parked R&D threads: evaluate `coder/ghostty-web` vs ttyd (pairs with the
  wterm exploration); xTiles MCP integration (future phase — keep new
  endpoints MCP-parity-friendly).

## 5. Environment facts that save time

- Test invocation from repo root: `VIRTUAL_ENV=.venv uv run --active
  pytest -q` (default addopts deselect integration/e2e/live_*). e2e runs
  need `-m e2e` from `packages/studyloop/`. `live_provider` hits real
  Bedrock and hangs this box — keep deselected.
- mkdocs is not a project dep: `uv run --with mkdocs --with mkdocs-material
  python -m mkdocs build --strict`.
- Real-vault sanity check for the picker:
  `python -c "from studyloop.web.routes.session._options import _vendor_options; ..."`
  should show 12 vendors, none named after topics, no duplicates.
- LiteLLM gateway `http://127.0.0.1:4000`; models `claude-opus-4-8`,
  `claude-sonnet-5`, `claude-fable-5`.
- The user's config uses the flat `tts.backend: openvox` form — it WORKS
  (dotted-key expansion, `a7eabb6`); don't "fix" the config file.
