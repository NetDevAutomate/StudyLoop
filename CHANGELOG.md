# Changelog

All notable public changes to StudyLoop are recorded here.

StudyLoop is preparing its first pre-release. The public API and installation
experience may change before `1.0.0`.

## [Unreleased]

### Added

- A learner-focused Web UI for starting Study Sessions, Body Double sessions,
  reviews, and study-plan work.
- First-party harness support for Kiro CLI, Codex, and Claude Code.
- Preview harness support for OpenCode and pi.
- Session-history import for each supported harness.
- Study-plan creation in the Web UI (**Study Plans → New plan**) and the CLI. The
  Web UI form is manual, with seed suggestions drawn from your own history; an
  agent-led planning interview is not integrated there yet.
- AuDHD-aware session scaffolding, spaced review, teach-back, parking-lot, and
  wind-down workflows.
- A strict public-documentation build and a separate internal audit/archive
  area.
- `SECURITY.md`: how to report a vulnerability, the supported-version policy
  (`0.1.x` only, pre-1.0), and a two-sentence summary of the LAN-password and
  encrypted-secrets-store threat model.
- `THIRD-PARTY-NOTICES.md` now credits all 26 vendored web assets under
  `web/static/vendor/` — four SIL OFL font families (Atkinson Hyperlegible,
  Inter, Lexend, OpenDyslexic) and eight JavaScript libraries (Alpine.js,
  htmx + the SSE extension, marked, DOMPurify, highlight.js, mermaid, Fuse.js,
  xterm.js + its three addons) — not just the one design-influence credit it
  previously had.
- `web/static/vendor/MANIFEST`: upstream URL, version, and sha256 for every
  vendored web asset, checked by a test that recomputes each hash and fails
  on a mismatch or an unlisted file. Every non-local URL was re-fetched and
  byte-compared while writing this — which also confirms two things a prior
  review flagged as unverified: htmx's current licence is Zero-Clause BSD
  (not BSD-2-Clause), and the vendored xterm.js "6.0.0" is a real upstream
  tag, not a typo.

### Changed

- Reworked the README and public guide around learner outcomes and approachable
  setup, with a real Kiro CLI walkthrough captured from the Web UI.
- Made the supported harness contract explicit across setup, diagnostics,
  launching, session export, and documentation.
- Made struggle extraction require an explicitly selected live model and a real
  exported harness session.
- Added source-session provenance and transaction-safe writes to struggle
  extraction.
- `practice verify --run-command` now requires `--yes` (or an interactive `y`
  at the prompt) in addition to `--run-command` before it actually executes a
  practice deck's verification command; the resolved command is always
  printed first. Without confirmation, nothing runs and the command exits 2.
- `mcp[cli]` is now pinned `>=1.0.0,<2` everywhere it is declared, so an
  unlocked install (a future `pip install`/`uv tool install` outside this
  repo's lockfile) can no longer select the 2.x release that renamed
  `FastMCP` and breaks `studyloop-mcp`/`session-db-mcp` at import.
- The workspace-root `pyproject.toml` version now matches
  `packages/studyloop/pyproject.toml`'s (both `0.1.0`); the release-consistency
  check now fails if the two ever disagree again.
- Removed the `studyloop[sessions]` extra and dropped `sessions` from
  `studyloop[all]`: `agent-session-tools` is not published, so it can never
  resolve as a wheel extra outside this repo's own workspace, and the extra
  was never actually what delivered it into the CLI tool venv anyway --
  `studyloop install tools`/`./scripts/install.sh` already add it
  unconditionally, independent of any extra. `studyloop[all]` still expands to
  `content`, `bedrock`, `notebooklm`, `tui`, `web`, and `mcp`; every one of
  those (plus `all` itself) is now proven, per-extra, to install and import
  from a bare built wheel with no workspace present.

### Removed

- Product-selectable fake agent and deterministic content backends. Test
  fixtures now live only in the test suite and are excluded from distributed
  packages.
- First-party session-harness claims for Gemini CLI, Antigravity, Grok, and
  local-model launchers.
- Session exporters outside the five-harness pre-release contract.
- Public pages that exposed implementation notes, internal architecture detail,
  or release-planning material.
- `ttyd` entirely — the browser terminal fallback and the server transport
  that backed it. `studyloop study --transport`, `studyloop web --ttyd-port`,
  the `ttyd_port` config key, the `/terminal/` HTTP+WebSocket proxy, and the
  `transport: "ttyd"` / `STUDYLOOP_TRANSPORT=ttyd` request paths are all
  removed; requesting `ttyd` now fails with a clear error instead of being
  silently downgraded to another transport. `studyloop study` is unaffected —
  it never depended on ttyd to work. See
  [ADR-0008](docs/adr/0008-retire-ttyd-entirely.md).

### Fixed

- `session-query list --since 7d` on `docs/setup-guide.md` and
  `docs/cli-reference.md` raised an unhandled traceback if pasted verbatim —
  `query_utils.parse_date` only accepts `YYYY-MM-DD` or `last-N-days`. Both
  pages now show `--since last-7-days`, matching the fix already applied to
  `docs/first-week.md`.
- `docs/setup-guide.md`'s "Interactive Setup" section described
  `studyloop config init`'s three questions (knowledge bridging, a "study
  material location" question `setup` never asks, an Obsidian vault path)
  under the `studyloop setup` heading. It now describes `setup`'s real,
  shorter flow (notes folder, optional focus-topic confirmation, optional
  harness pick) and correctly separates out `config init`'s own three
  questions instead of conflating the two commands.
- Removed the dangling `GEMINI.md` symlink at the repo root (it pointed at
  `agents/gemini/GEMINI.md`, which no longer exists now that Gemini CLI is
  not a supported mentor harness). A guard test now fails the suite if any
  tracked symlink ever points at a missing target again.
- Cross-machine sync (`session-sync push`/`pull`/`sync`) no longer overwrites
  global tables (`study_progress`, `study_sessions`, `teach_back_scores`,
  `knowledge_bridges`, `concepts`, `concept_aliases`, `concept_relations`,
  `message_concepts`, `parked_topics`, `scrub_log`) unconditionally. Every row
  is now gated on `updated_at`, matching the check already applied to
  `sessions`/`messages`, so a stale machine's dump can no longer silently
  revert a newer board move, teach-back score, or progress row on the
  receiving side. `push` and the remote side of `sync` now back up the
  destination before writing to it, exactly as `pull` already backs up its
  own destination.
- Session archive/delete/prune cutoffs (`session-maint archive`/`delete-old`,
  tiering's `prune`/`refocus`) and focus suggestions computed their cutoff
  from naive local wall-clock time, then compared it against UTC-sourced
  timestamps. On a machine east of UTC this could delete sessions updated
  within the last few hours; west of UTC it could keep sessions that should
  have been caught. Cutoffs now use real UTC.
- `record_teachback`'s write to `study_progress` now runs inside an explicit
  `db.immediate()` transaction instead of relying on statement order to hold
  SQLite's write lock; a CHECK-constraint violation (an out-of-range
  teach-back score) no longer raises unhandled through `record_teachback`;
  and the `study_progress` row id derived from (topic, concept) is now
  separator-safe, so a topic and concept that together contain a `:` can no
  longer collide with a different pair.
- Roughly 30 read/write helpers across `history/{sessions,progress,bridges,
  streaks,teachback}.py` and `learning/mastery.py` caught every
  `sqlite3.OperationalError` the same way, including a genuine lock/timeout
  fault — silently returning "no wins" / "no struggling topics" / "no
  progress" instead of surfacing the failure. Narrowed to the specific "no
  such table" case (an expected, pre-migration schema gap); anything else is
  now logged and re-raised, matching the fix already applied to the explorer
  search path.
- `review_db.py`'s six public functions (`ensure_tables`,
  `record_card_review`, `record_session`, `get_due_cards`, `get_wrong_hashes`,
  `get_course_stats`) used `with conn:` for cleanup, which only commits or
  rolls back a transaction — it does not close the connection. Every
  flashcard/quiz answer (`POST /api/review`) leaked a `sqlite3.Connection`,
  relying on CPython's refcounting to eventually close the file handle. Now
  `try/finally: conn.close()`, matching the convention used everywhere else
  in the codebase (`parking.py`, `notes.py`, `history/*.py`).
- The tmux/herdr integration test harness (`tests/harness/multiplexer.py`,
  `tests/harness/study.py`, `tests/harness/terminal.py`,
  `tests/harness/agents.py`) and the test modules that drive it
  (`test_harness_matrix.py`, `test_study_integration.py`,
  `test_uat_terminal.py`, `test_study_lifecycle.py`, `test_herdr_integration.py`,
  `conftest.py`) hardcoded `~/.config/studyloop` for session-state IPC files
  and spawned the CLI without setting `STUDYLOOP_SESSION_DIR`. Running these
  suites locally read, wrote, and deleted the developer's real live session
  state. Every path now derives from `STUDYLOOP_SESSION_DIR`, redirected to a
  `tmp_path`-based directory by each fixture, and forwarded to every spawned
  `studyloop` subprocess.
- Cross-machine sync's recency gate (`excluded.updated_at > table.updated_at`)
  was NULL-falsy: a destination row with a NULL `updated_at` could never be
  overwritten by any incoming row, however new, freezing it forever. Every
  `study_sessions` row created after the R-19 migration was silently one of
  these, since that table's `updated_at` had no default and nothing wrote it.
  Now `COALESCE(destination.updated_at, '')` treats a NULL destination as
  older than anything, and a trigger stamps `updated_at` on every insert and
  update to the tables that previously had no default for it.
- Cross-machine sync used `id INTEGER PRIMARY KEY AUTOINCREMENT` as the
  conflict target for `teach_back_scores`, `knowledge_bridges`,
  `parked_topics`, and `scrub_log` -- a counter private to each machine,
  starting at 1 independently everywhere. Two machines' different row #1s
  collided as the same row, and the incoming row was silently dropped (no
  error, row count unchanged). These four now use a migration-backfilled
  `sync_key`; `concept_relations` (which already had a real natural key)
  now syncs on that instead of its own autoincrement `id`.
- Cross-machine sync's remote backup (`push`/the remote side of `sync`) and
  the local `session-maint` backup helper both copied the database file
  with a plain file copy (`cp -p` over SSH, `shutil.copy2` locally). In WAL
  mode, data committed but not yet checkpointed into the main `.db` file
  lives in the sibling `-wal` file, which a plain file copy never reads —
  the backup silently missed recently-committed rows. Both now use a
  WAL-aware backup mechanism (the sqlite3 CLI's `.backup` dot-command
  remotely, `sqlite3.Connection.backup()` locally).
- `push` and the remote-writing step of `sync` discarded the result of
  backing up the remote destination — a failed backup was logged and the
  write proceeded anyway, unprotected. Both now abort the write when the
  backup fails. The remote backup also had no retention: every `push`/
  `sync` call left another `.bak-<timestamp>` copy next to the remote
  database forever. It now rotates, keeping only the newest 5 (matching
  the local backup helper's own default).
- Cross-machine sync's global-table recency gate compared `updated_at` as
  a raw string. Every current writer produces the same canonical format,
  so this was not a live bug today, but a bare string compare is silently
  wrong across formats that place a different character at the same
  position (for example, a `T`-separated timestamp sorts as "later" than
  a space-separated one at the same clock time, regardless of which is
  actually later) — exactly the kind of mismatch real elsewhere in this
  codebase's session-import exporters. The gate now compares both sides
  through SQLite's `datetime()`, so it stays correct if a future writer,
  a manual edit, or an older/foreign row ever disagrees with today's
  uniform writers.
- `record_teachback` caught every `sqlite3.DatabaseError` the same way,
  including a genuine lock/timeout `OperationalError` -- indistinguishable
  from an expected CHECK-constraint rejection (an out-of-range teach-back
  score), both silently returning "not recorded." Narrowed to
  `sqlite3.IntegrityError` for the CHECK-violation case; anything else is
  now logged and re-raised unless it is a missing-table error, matching
  the fix already applied to the read-side helpers across
  `history/*.py`.
- `history/concepts.py`'s `list_concepts` and `history/search.py`'s
  `topic_frequency`/`struggle_topics` had the same bare
  `except sqlite3.OperationalError: return []` the rest of `history/*.py`
  was already fixed for -- a lock/timeout fault read back
  indistinguishably from "no concepts"/"topic never mentioned." Narrowed
  to the missing-table case; anything else is now logged and re-raised.
- Starting a web Study Session or Body Double no longer clobbers a session
  already running in a terminal (`studyloop study`), and vice versa. The web
  UI's start path now checks the same cross-process session claim the CLI
  writes, refusing with a clear "already active" message instead of silently
  overwriting the shared session state and orphaning the CLI's running
  agent. A session left behind by a crashed process is still reclaimed
  automatically rather than blocking forever.
- `studyloop study` no longer refuses to start after a crashed session left
  a stale claim; the stale claim is reclaimed with a logged warning
  (R-01b).
- Reclaiming a crashed session's slot (web or CLI) no longer shows its
  topics-covered list and parking lot to the new session; both are cleared
  before the new session starts, not just touched (C2).
- A second web server process (a different port, or a restart racing the
  previous one before it fully exits) starting a Study Session or Body
  Double now correctly refuses with "already active" instead of treating
  the first server's still-live session as stale (C3).
- The study sidebar's IPC file poll no longer risks crashing its background
  thread if a session ends (and its state files are removed) at the exact
  moment the poll runs; it now reads first and treats a vanished file as
  "no update" instead of checking existence then reading as two separate
  steps (C7).
- A reclaimed session's log line now names the crashed session's agent
  process (if one was recorded and is still running) so it is visible
  that an orphaned agent may still be alive on the machine; StudyLoop
  still never signals it (C4).
- Closed a narrow race where a session start (CLI or web) checked whether
  a slot was free and only claimed it afterward, with real work
  (spawning the agent, creating the database record) running in between;
  a second start landing in that window could have raced the eventual
  claim. The check and the claim now happen together (C1).
- Reclaiming a crashed session's slot could leave that dead session's
  multiplexer name and other identifying details attached to the brand
  new session that reclaimed it -- in the worst case, ending the new
  session could then affect an unrelated terminal session that happened
  to still be using that name. A reclaimed slot now starts completely
  clean (C10).
- Ending a session -- from the Web UI, `studyloop study --end`, or the study
  sidebar's End Session key -- no longer terminates every other study
  session on the machine. Each end path now closes only its own terminal
  session (a web Study Session or Body Double closes none, since it owns no
  terminal). `studyloop clean --all` is the one place left to deliberately
  sweep every `study-*` session at once, for the rare case that's actually
  wanted.
- The live session dashboard's activity stream (SSE) could very rarely drop
  its connection with no explanation if a session ended at the exact moment
  the stream polled for changes. It now tolerates that race the same way the
  rest of the session-state readers already did.
- When a Kiro (ACP) session fails to start, the server log now includes
  whatever the agent printed before it crashed, instead of only a generic
  handshake-timeout message.

### Security

- Closed a gap where a `.env` file planted in or above the directory
  `studyloop` is run from could set the test-only `STUDYLOOP_TEST_AGENT_CMD`
  / `STUDYLOOP_TEST_ACP_CMD` hatch and get an attacker-chosen shell command
  executed on the next session start. The hatch is now honoured only when
  exported in the real process environment (as the e2e harness already
  does); a value that arrives via the `.env` auto-loader is deleted and
  logged.
- Closed a second, independent gap that bypassed the fix above: a `.env` at
  `~/.config/studyloop/.env` reintroduced the same test hatch at every
  web-server startup, via a second dotenv loader in `agent-session-tools`
  that ran after the first fix's scrub. Same rule, same guard, now applied
  in both loaders.
- Hardened the fix above further: every production site that reads the test
  hatch now consults a value captured once, at import time, before any
  `.env` file is loaded, rather than re-reading the environment on every
  session start. A `.env` loaded by something other than this package,
  later in the process's life, can no longer set the hatch either.
- `practice verify --run-command` now runs the EXACT command string a human
  confirmed, and refuses if the practice deck's command changed between
  being shown for confirmation and being executed, closing a time-of-check-
  to-time-of-use window in the R-15 fix above.
- Closed a gap in the agent-child credential scrub where two credential-
  shaped words joined with no separator (`SERVICE_APIKEY`, `SESSIONCOOKIE`)
  escaped every existing pattern, which is underscore-anchored throughout.
- Closed a gap in the agent-child credential scrub: a bare `_KEY` suffix
  (`ENCRYPTION_KEY`, `SIGNING_KEY`, `MASTER_KEY`, ...) and bare
  `AUTHORIZATION`/`JWT`/`COOKIE`-shaped variables now get stripped from an
  agent child's environment, matching the compounds (`api_key`,
  `secret_key`, ...) already covered.
- `config.yaml` (which can hold `lan_password` in plaintext) is now written
  0600 on every save, repairing a pre-existing 0644 file on its next save;
  a newly created config directory is created 0700.
- Disabled the last piece of the Web UI's auto-docs surface: `/openapi.json`
  now 404s, matching the already-disabled `/docs` and `/redoc`.
- `practice verify --run-command` no longer runs a practice deck's
  verification command blind: it is shown before it runs and requires
  explicit human confirmation (see `### Changed`). The three local
  card-generation prompts (flashcard, quiz, practice) now instruct the model
  to treat the source material it is given as data, not as instructions to
  follow, and the practice prompt additionally warns against copying a
  command straight out of the source into a task's verification metadata.

### Known pre-release boundaries

- Kiro CLI is the documented demonstration harness.
- OpenCode and pi are preview integrations while their release evidence is
  completed on supported local installations.
- Grok may be used as an independent review model through the development
  gateway; that does not make Grok a StudyLoop code harness.
- Live extraction does not silently fall back to sample output. If a model,
  credentials, session, or harness binary is unavailable, the command stops
  with an actionable error.

See [the `0.1.0` release note](releases/v0.1.0.md) for the current acceptance
boundary. Earlier private development history remains available in Git rather
than being presented as shipped product history.
