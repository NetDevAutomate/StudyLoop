# Session Handoff — Post Fan-Out State + Remaining Work (2026-07-12, evening)

> **SUPERSEDED by `2026-07-12-session-handoff-closeout.md`** — the branch is
> merged to main, both user-reported defects are fixed, and the openspec
> change is archived. Read the close-out doc first; this one remains for the
> corrections list (§2) and original root-cause narratives.

**For:** the next Claude session (fresh context). This supersedes
`2026-07-12-session-handoff-e2e-harness.md` — that mission is **complete**;
read this doc first, then only dip into the old one if you need the original
root-cause narrative.

**Repo state at handoff:** branch `feat/e2e-harness-and-hardening` @ 16+
commits on top of `main` @ `61a15fc`. Local `main` is itself 15 commits ahead
of `origin/main`. **Nothing pushed anywhere; no PR.** Working tree was clean
at handoff except possibly two in-flight agent lanes (§4).

---

## 1. What landed this session (all verified, all committed)

Full narrative in the commit messages — they are deliberately detailed. Key
commits on `feat/e2e-harness-and-hardening`:

| Commit | What |
|---|---|
| `8b551e0` | Frontend: non-JSON-500 no longer masks as "Network error"; e2e markers + gitignore |
| `a5113ea` | **P0 security**: `slug_session_dir()` path-traversal fix across all 4 session-dir builders + server-side ACP guard (`ACP_CAPABLE_AGENTS = {kiro, gemini, grok}` single source of truth) + tests (held-out-gate verified) |
| `550bd37` | `ContentIndex` (SQLite mtime index) + `studyloop content index` CLI + tests; dead warm-check removed |
| `05a458e` | `GET /api/backlog` — 3-topic active/parking-lot split (learner-UX data layer) |
| `d429b73`+`d252423` | CHANGELOG.md created **and un-gitignored** (it was ignored under "agent workflow artefacts" — that's why the roadmap's `[x]` claim could never be true); 3 false roadmap claims corrected |
| `c8f2a42` | OpenSpec: 8 capability specs + change proposal, validates 9/9 |
| `e3070be` | **MCP parity**: 5 tools (`get_due_cards`, `log_review_outcome`, `get_next_action`, `get_active_topics`, `log_struggle`) — 13→18 tools |
| `4f7bf6f` | Desktop MCP: real stdio smoke test (SDK `ClientSession`), Claude Desktop + Codex config snippets (`docs/desktop-mcp/`), `docs/mcp.md` 18-tool table |
| `97be8dd` | **Full-suite fix**: asyncio loop-leak regression (118 failures → 0); agent-session-tools got its own `tests/_helpers.run_async` |
| `2c7b045` | Journey e2e **rewritten against the real UI** (old one asserted fictional selectors); `test_socratic_steering.py` LLM-judge scaffold (live_provider) |
| `a3fca0e` | Removed `tests/e2e/conftest.py` — it shadowed parent `tests/conftest.py` (`StubTransport` ImportErrors) |
| `7e45e48` | MagicMock disk-leak root-caused: `_target_index_path()` guards non-path `state_dir` |
| `e2d1ad8` | OpenSpec specs synced with landed fixes (traversal closed, 18 tools) |

**Verification state at handoff:** full default suite **2866 passed / 0
failed / 0 errors**; `ruff check .` clean; pyright clean on changed src;
`mkdocs build --strict` exit 0; `openspec validate --all` 9/9;
mission-scoped e2e green (32 passed, 2 honest live-only skips).

## 2. Hard-won corrections — do NOT re-learn these

1. **The old handoff's root cause was only half right.** The SIGCHLD
   ValueError reproduces in a thread-hosted server, but `studyloop web` as a
   plain subprocess works fine in non-TTY on this machine — the original
   `_playwright_helpers.start_web_server()` needed no change. The thread
   rewrite WIP was reverted, not fixed.
2. **The nav store ignores post-init hashchange BY DESIGN.**
   `test_web_navigation.py::test_direct_hash_change_is_ignored_by_default`
   is a committed lock. `page.goto('#view')` does NOT switch views; use
   `page.evaluate("() => window.Alpine.store('nav').go('<view>')")`. Adding
   a hashchange listener breaks the lock test (tried, reverted).
3. **The original 21KB journey test asserted a fictional UI**
   (`select[name=provider]`, `.mentor-message`, `.flashcard-deck` — none
   exist). Real picker selectors: `#target-kind-select`, `#vendor-select`,
   `#course-select`, `#lesson-select`, `#agent-select`, `#transport-select`,
   `input#topic-input`, `button.start-session-btn`. Picker hydrates async
   from `GET /api/session/options` — wait with `wait_for_function` on option
   counts.
4. **The grok worktree lanes claiming "COMPLETE" were broken as written**:
   wrong `start_session` signature, `get_parked_topics(status="active")`
   (invalid — CHECK allows pending/scheduled/resolved/dismissed only),
   duplicate `/now` route with fake data. Discarded + reimplemented; the
   worktrees are deleted.
5. **The asyncio loop-leak recurs whenever a test adds bare
   `asyncio.run()`** in sync test code. Signature: `RuntimeError:
   Runner.run() cannot be called from a running event loop`, green in
   isolation / red in full run. Fix: route through `_helpers.run_async`
   (each workspace package needs its OWN copy — no cross-package imports).
   Consider a lint rule banning `asyncio.run(` under `tests/`.
6. **Never add a `conftest.py` under `tests/e2e/`** — pytest imports it as
   module `conftest`, shadowing `tests/conftest.py` (breaks
   `from conftest import StubTransport` in ~5 files). Use the inline
   `sys.path.insert` shim (precedent: `test_active_session.py`).
7. Test-runner flags that matter: default `addopts` deselects
   `integration/e2e/live_kiro/live_provider`. Unit runs of unmarked files
   need `-o addopts=""`. e2e runs need `-m e2e` **from
   `packages/studyloop/`**. `live_provider` hits real Bedrock and hangs this
   box — keep deselected.

## 3. Outstanding work (verified against repo at handoff)

### Needs the user's decision first
- **Merge `feat/e2e-harness-and-hardening` → main, push, PR.** All work is
  local. After merge: `openspec archive complete-e2e-harness-and-desktop-mcp`.
- **Manual desktop verification**: register `studyloop-mcp` in Claude
  Desktop + Codex per `docs/desktop-mcp/README.md` and click through a
  review loop. Headless-impossible; ~10 min human task.

### Descoped from the mission — next natural slice (fan-out candidates)
- **Fake-agent PTY binary** (old plan task 1.4): a tiny script that reads
  the persona arg + echoes Socratic-ish lines, so CI can walk the full
  spawn→WS→terminal path. Unlocks deeper journey phases.
- **Session-end export assertion** (task 4.4): journey should assert
  progress lands in the session DB after `/api/session/end`.
- **MCP explorer read tools** (task 5.1): `get_lesson_tree`, `read_lesson`,
  `search_lessons` reusing `_safe_course_dir` + explorer internals. Highest-
  value remaining desktop-MCP gap (audit §6).
- **Run the Socratic judge live once**: `cd packages/studyloop && uv run
  pytest tests/e2e/test_socratic_steering.py -m live_provider`. Gateway
  `http://127.0.0.1:4000`, token env var name is `LITELLM_BEARER_TOKEN`
  (read from `~/code/personal/tools/litellm_proxy_docker/.env`). Judge is
  `claude-opus-4-8`, mentor `claude-sonnet-5`. The test exists but has
  NEVER been executed against the live gateway.
- **Full 348-test e2e suite**: never run to completion (>25 min; each test
  spawns a server). Known pre-existing failure:
  `test_web_smoke_browser.py::test_generate_busy_response_shows_visible_conflict_state`
  (fails on clean HEAD too — root-cause it). CI has no e2e job at all
  (audit P0 #3).

### User-reported defects (2026-07-12 evening, manual testing — NOT yet fixed)
- **Vendor picker pollution + duplicates**: the "Course Vendor" dropdown lists
  the user's configured topics of interest (Python, DevOps, LangChain,
  Software Development…) alongside real vendors, plus duplicate entries
  (ArjanCodes/SkillsBuilder/Udemy appear twice). Root cause in
  `web/routes/session/_options.py`: `_study_roots()` includes every
  `settings.topics[*].obsidian_path`, and `_courses_roots()` uses each study
  root **directly** when it has no `Courses/` child — so topic directories at
  the study-root level surface as "vendors", and each topic dir is ALSO its
  own courses root, so any vendor dir nested inside a topic dir appears a
  second time (dedup is by resolved path, not by name, so same-name vendors
  at different paths both render). Fix direction: vendors should come only
  from dedicated course roots (the ContentIndex knows the real
  provider/course/lesson tree — 12 providers), not from topic dirs; dedupe
  by value as a backstop.
- **Cannot end a Kiro (ttyd) session — confirm() flash**: clicking the stop
  icon during a Kiro CLI study session shows a popup in Chrome that vanishes
  before it can be read, and the session never ends. `endSession()` in
  `index.html` (~L2502) gates on native `confirm('End the current study
  session?')`; if `confirm` returns false (Chrome is known to auto-dismiss
  native dialogs in some focus states — the embedded ttyd iframe holding
  focus is the leading HYPOTHESIS, not yet reproduced), `endSession()`
  silently bails and the user is stuck. Whatever the trigger, a native
  `confirm()` as the only exit gate is fragile here. Fix direction: replace
  it with an in-page Alpine modal; reproduce with a live Kiro/ttyd session
  to confirm the focus theory.

### Known-open defects (documented in openspec/specs/, re-verified at handoff)
- `resolve_study_dirs()` bare `review:` crash + `study_paths` scalar
  explosion — the settings shape-hardening P0 remainder (plan Task 1).
- ~~`tts.backend` flat-key bug~~ **FIXED (`a7eabb6`)**: a top-level YAML key
  literally named `tts.backend` was ignored by every consumer (they read the
  nested `raw.get("tts")` shape) — and the doctor's own repair hint ("Set
  tts.backend: openvox") taught users to write exactly that broken flat form.
  Root-cause fix: `_expand_dotted_keys()` in `settings.load_raw_config()`
  normalises ANY top-level dotted key into the nested tree (explicit nested
  values win on conflict), fixing all 6 consumers at once; doctor hints now
  phrase the repair as nested YAML. Verified live against the user's real
  config: `studyloop doctor` reports "OpenVox API reachable". Held-out gate
  passed; suite 2872/0. The user's config file itself was deliberately left
  untouched — the flat form now WORKS, though the canonical form is:

  ```yaml
  tts:
    backend: openvox
  ```
- Kiro exporter drops string-shaped history entries; gemini FK-swallow;
  aider ID duplication (session-export spec).
- Scrubber misses unquoted AWS secrets (`['\"]...` regex requires quotes).
- `get_chapter_text` negative-chapter Python-index bug (mcp-server audit).
- LAN auth divergence: `create_app` never stores CLI-passed
  username/password on app.state (audit verified-high).

### Roadmap (now honestly `[ ]` after reconciliation)
- Release automation: `release.yml` / `pre-release.yml` do not exist.
- Learner-first UX **UI slice**: `/api/backlog` data layer exists, but the
  "Today's one next action" landing view, park-first friction modal, and
  recovery shortcuts are unbuilt in `index.html` (plan Task 2).

## 4. In-flight agent lanes at handoff time

1. **`doctor-tts-fix`** — ~~in flight~~ **LANDED as `a7eabb6`** (the agent
   stalled; the main session implemented it directly — see §3's fixed
   tts.backend entry for the full shape: `_expand_dotted_keys()` in
   `load_raw_config()`, doctor hints rephrased, 6 new tests, held-out gate,
   suite 2872/0).
2. **`openspec-sync`** — updating `openspec/changes/complete-e2e-harness-
   and-desktop-mcp/tasks.md` checkboxes to verified reality (with
   done-differently notes), appending Outcome-notes to design.md, and adding
   the tts.backend defect (now FIXED in `a7eabb6` — it should describe the
   fixed behaviour, citing that commit) to `openspec/specs/voice-tts/spec.md`.

If openspec-sync's work is on disk but uncommitted: review the diff, run
`openspec validate --all` (must stay 9/9), commit. If absent: re-run that
lane from the spec above.

## 5. Suggested fan-out for the next session

Parallel-safe lanes (the strategy that worked: main thread owns critical
path + commits; agents get verified contracts, explicit "do NOT commit",
and a proof protocol; review every diff before committing — two of three
"COMPLETE" claims last time were broken):

- **Lane A (needs user)**: merge/push/PR + archive the openspec change +
  desktop click-through.
- **Lane B**: settings shape-hardening P0 (finish `load_settings()` +
  `resolve_study_dirs()` guards; the tts dotted-key fix is the same class —
  build on it).
- **Lane C**: fake-agent PTY binary + extend journey phases (session-end
  export assertion, generation walk with Stub provider).
- **Lane D**: MCP explorer read tools + stdio smoke extension.
- **Lane E**: exporter defects (kiro string-entries, scrubber unquoted
  secrets) with real-session fixtures — run `export_all` against live
  `~/.kiro` etc. and assert non-zero imports (codex-exporter lesson).
- **Lane F (bigger)**: learner-first UX UI slice in `index.html` — respect
  the nav-store lock; hydration pattern per §2.3.

## 6. Environment facts that save time

- LiteLLM gateway: `http://127.0.0.1:4000`; the env file's variable is
  `LITELLM_BEARER_TOKEN` (NOT `LITELLM_MASTER_KEY` as older docs claim);
  models include `claude-opus-4-8`, `claude-sonnet-5`, `claude-fable-5`.
- Playwright chromium installed and working; e2e server helper spawns
  `python -m studyloop.cli web` subprocess (keep it a subprocess).
- `studyloop content index --force` → 12 providers / 39 courses / 417
  lessons from the user's real study dirs; `GET /api/session/options`
  returns 15 vendors / 45 courses / 6 agents.
- MagicMock/ dirs appearing at repo root = a test mocked a path-typed
  setting; the `_options.py` guard covers the known case; `MagicMock/` is
  gitignored as defense-in-depth.
- `git worktree list` should show ONE entry. The 3 grok worktrees are gone;
  do not resurrect their patches (saved in /tmp/grok-harvest/ if morbidly
  curious — 2 of 3 were broken).
