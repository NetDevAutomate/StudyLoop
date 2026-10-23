# Troubleshooting

## Install Checks

Run the lightweight self-test first:

```bash
studyloop self-test
studyloop self-test --json
```

Then run the deeper environment checks:

```bash
studyloop doctor
studyloop doctor --json
```

`studyloop self-test` is safe immediately after installation. It does not run
`doctor --fix`, start services, contact providers, or write agent files.

## uv Environment Drift

When a local checkout behaves differently from CI, resync the lean development
profile and rerun the core gates:

```bash
just sync-dev
just lint
just typecheck
just test
```

Use `just sync-full` only when validating optional extras. The full profile
pulls heavier optional stacks such as semantic search and TTS dependencies.

### The installer picked an unexpected Python

Python 3.12 or 3.13 (both tested in CI). The installer defaults to 3.12
through `.python-version` and downloads it with uv if needed; set
`UV_PYTHON=3.13 ./scripts/install.sh` to choose another. 3.14 installs but is
checked only by the nightly install job; the installer refuses anything else.

Diagnose which interpreter uv is actually resolving from this checkout:

```bash
uv python find
```

Note that plain `uv python find` reports the repo's `.python-version` pin
even if `UV_PYTHON` is set — unlike `uv run`/`uv sync`, it does not treat that
env var as an override once a version file exists. To check what a specific
override would actually resolve to, pass it as an argument (this is exactly
what `./scripts/install.sh` does internally):

```bash
uv python find 3.13
```

If that is not the interpreter you expected, set `UV_PYTHON` before running
the installer (or any `uv run`/`uv sync` command) to pin a specific supported
version:

```bash
UV_PYTHON=3.13 ./scripts/install.sh
```

## Optional Profiles

Use profile checks when a change touches a specific optional surface:

```bash
just test-web
just test-content
just test-semantic
```

If `test-semantic` skips because `numpy` or embedding dependencies are missing,
run:

```bash
just sync-semantic
just test-semantic
```

## Web And LAN Access

For local-only use:

```bash
studyloop web
```

Each server prints a sign-in address once, with a token that is new every start;
a browser that opens it is signed in. A tab from before a restart cannot recover
on its own: reopen it from the new address. If the tab is closed and the token
gone, `studyloop web --show-url` prints the current session dashboard's address
again (it refuses when no server is up, and when the server that recorded the
token is gone and something else now answers on its port).

To reach it from another device, prefer an `ssh -L` tunnel or a Tailscale/VPN
address (see [Remote Study](setup-guide.md#remote-study-ipad-on-the-bus)):

```bash
studyloop web --bind "$(tailscale ip -4)"      # or: studyloop study "topic" --bind …
```

`--bind` refuses an address this machine does not have and lists the ones it
found; it refuses `0.0.0.0` and `::`. The server also listens on `127.0.0.1`, so
local tools keep working. `--lan` (every interface, cleartext) is deprecated.
Configured passwords are not printed. Generated one-time passwords are printed
once. If a phone or tablet cannot connect, check that the shown address is the
one the device can route to (the VPN address on a tailnet) and that it opened the
address with the token, or pasted the token into the sign-in page.

A WebSocket connection through a tunnel or reverse proxy has a different Origin
than the LAN host expects, and is rejected by default. Set
`STUDYLOOP_ALLOWED_ORIGINS` to a comma-separated list of exact origins (scheme
+ host + port, no wildcards) to allow them explicitly — this is not a
supported quick path (see [Web UI Guide](web-ui-guide.md#use-it-from-another-device)),
just an escape hatch for a trusted setup that needs it.

## The Browser Terminal Shows "No Terminal Available"

The live console has two renderers, chosen by the session's `transport`:

| `transport` | Renders as |
| --- | --- |
| `pty` (default) | xterm.js, fed by the PTY over a WebSocket |
| `acp` | structured ACP chat events |

Anything else has **no browser renderer**. The console reports an explicit
`unavailable` state — status `No terminal available`, plus a message naming the
transport it cannot render and telling you to end the session and start it again
on the browser terminal or ACP. In practice this should not happen any more:
`ttyd` (the only other transport that ever existed) is fully retired, both the
browser surface and the server transport
([ADR-0005](adr/0005-retire-ttyd-browser-surface.md),
[ADR-0008](adr/0008-retire-ttyd-entirely.md)). `STUDYLOOP_TRANSPORT=ttyd` and
`{"transport": "ttyd"}` are both rejected outright (422/error) rather than
accepted and rendered as `unavailable` — if you see this state, it means the
server returned a transport value this console genuinely doesn't recognise,
which is worth reporting as a bug rather than working around.

If the environment sets `STUDYLOOP_TRANSPORT` to anything other than `pty`,
unset it and start a new session:

```bash
env | grep STUDYLOOP_TRANSPORT
unset STUDYLOOP_TRANSPORT
studyloop web
```

Installing `ttyd` does **nothing** — no code path spawns, proxies, or accepts
it any more. The retired design records remain in the repository for
maintainers, including the reasoning for retiring first the browser surface
and then the server transport.

If the transport is already `pty` and the panel still reports no terminal, the
server did not return a connection for the session. Ending and restarting the
session clears this; the message says so rather than leaving a blank pane.

A session whose server stopped while it ran (`studyloop web` was restarted,
crashed, or its terminal was closed) is not offered for reattach. A browser
terminal or ACP session runs inside the server that started it, so once that
process is gone `/api/session/state` reports the session ended and both views
show their picker. A tab that was open on the live session when this happened
returns to its picker by itself, with the activity still typed in and a
one-line reason above it ("Your session ended: the connection to the server
was lost (was studyloop web restarted?)"); the same happens, with the agent's
exit reason, when the agent process exits under a live tab. Start a new
session; the old one's parking-lot file is left in place.

## Kiro Reports `invalid agent config: kiro_default.json`

kiro-cli 2.24.0 reserves the agent name `kiro_default`. A file of your own at
`~/.kiro/agents/kiro_default.json` (the usual way to customise Kiro's default
agent before 2.24.0) is ignored, with this notice on every start, including the
Kiro sessions StudyLoop opens. It is kiro-cli's notice about your file:
StudyLoop neither reads nor writes it, and StudyLoop's web sessions run their
own `studyloop` agent whatever your default is.

To keep your customisation, give it a name kiro-cli has not reserved and make
it the default:

```bash
cd ~/.kiro/agents
jq '.name = "default-plus"' kiro_default.json > default-plus.json
mv kiro_default.json kiro_default.json.retired
kiro-cli agent set-default default-plus
```

If another tool manages that file, check that it will not recreate it first.

## A Kiro ACP Session Says "Could Not Start"

Yes, Kiro supports ACP: a web session started with the `acp` transport runs
`kiro-cli acp --agent studyloop` and talks JSON-RPC to it over stdio. A start
that fails there now returns a structured error — *The kiro agent did not
complete the ACP handshake: `<stage>` failed: `<reason>`* — with the agent's
own stderr (`stderr_tail`) and a `repair` hint in the body, and the
study-session record is aborted so nothing is left half-started.

Before 0.6, one cause produced a bare `Could not start (500)` with only a
server-side traceback ending in `subprocess exited before responding`:
kiro-cli 2.29.0 emits `_kiro.dev/commands/available` notifications of ~74 KB
per line during `session/new` (more agents installed, longer lines), and the
transport read stdout with asyncio's default 64 KiB line limit, which turned
one long frame into a false end-of-stream while the child was still running.
The reader now buffers up to 16 MiB per line and treats a longer frame as a
dropped frame, not a dead agent.

If the structured error names a real agent failure, run the agent's own
command by hand from a session directory to see what it says:

```bash
kiro-cli acp --agent studyloop   # then paste one line and press Enter:
{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":1,"clientCapabilities":{"fs":{"readTextFile":true,"writeTextFile":true},"terminal":false}}}
```

A JSON response on stdout means the agent is healthy and the fault is between
it and StudyLoop (check the server log); an error or exit means kiro-cli or
the `studyloop` agent definition (`studyloop doctor`, `studyloop install
agents --tool kiro`).

## The Terminal Is Empty After A Page Refresh

The panel should reattach on its own. What holds today:

- **The session survives the refresh.** A disconnect starts a detach grace
  window on the server (90 s by default; `STUDYLOOP_WS_GRACE_SECONDS`
  overrides it), so the agent process keeps running and
  `GET /api/session/state` still reports the session after the reload.
- **The reattach is automatic.** `liveAgentConsole.init()` reads
  `GET /api/session/state` on load and re-adopts a live session it owns,
  restoring the terminal and reporting *Reattached* rather than *Starting*.

An empty terminal after a refresh is therefore a real fault worth
investigating, not expected behaviour. The most likely cause is a reload that
took longer than the grace window, which genuinely ends the session.

If a refresh leaves an empty terminal:

1. Confirm a session is actually live: `GET /api/session/state` should report
   it. If the grace window has already expired, the state response says why
   the last session went away.
2. Check the browser console for a JS error during `init()` — a thrown
   initialiser stops the adopt step from even being attempted.
3. Confirm the static assets being served are current. `studyloop web` serves the
   **installed** package's assets, so a stale editable install serves stale JS:

   ```bash
   uv run studyloop install tools --skip-sync
   ```

To get back to work, end the session from the UI and start a new one — the
pane says what happened rather than staying blank. Sessions started from the
CLI in tmux (not through the web UI) have their own recovery path:
`studyloop study --resume` reattaches to the running agent, or rebuilds the
conversation from history if the tmux session is gone.

## Provider Credentials

Use the web Settings panel or environment variables for provider keys. Raw
provider keys must never appear in logs, screenshots, or issue reports.

For provider checks:

```bash
studyloop self-test
studyloop doctor --category deps
```

`studyloop self-test` only verifies that the web module imports. It does not
call OpenAI, OpenRouter, Gemini, Anthropic, Bedrock, Ollama, or other providers.

## Generation Is Busy Or Stuck

The Generate panel runs one content-generation job at a time. If another job is
active, `POST /api/content/generate` returns `409` and the browser shows a
visible busy/conflict banner.

Use this order:

1. Check the Generate panel status and progress rows.
2. Wait for the active job to finish if the panel says another job is running.
3. If the local process was killed mid-job and the UI never clears, restart
   `studyloop web`.
4. Rerun generation from the same course/scope. The default **Merge** policy
   de-duplicates existing cards/questions and is the least destructive retry.

## Generated Too Many Or Too Few Cards

The **Cards / questions per source** field is sent as `count_per_source`. It is
copied into each `GenerationTask.count` and included in the provider prompt for
every selected source and kind.

This is a target, not a filesystem quota. Live providers can under- or
over-produce if they do not follow the prompt; invalid shapes fail validation
and appear as task errors. StudyLoop does not substitute generated-looking
placeholder cards when a provider fails.
Use the Generate panel plan/progress line to confirm the requested count,
provider, and model before comparing output files.

## Course Explorer Looks Stale

The Course Explorer provider/course tree is cached by a visible tree
fingerprint, not only the top-level directory timestamp. Adding or deleting
nested source courses should refresh on the next tree request, while generated
output folders such as `flashcards/` and `quizzes/` intentionally do not
invalidate the visible tree.

If the panel looks stale:

1. Refresh the browser.
2. Confirm the source file lives under `content.base_path`.
3. Confirm the source file has an allowed suffix: `.md`, `.markdown`, or `.txt`.
4. Restart `studyloop web` if the process has been running through manual file
   moves or external sync conflicts.

Do not delete `explorer_fts.db` for a stale provider/course list. That file is
only the derived search index.

## Search Results Are Stale

Course Explorer search uses the derived SQLite FTS cache at
`<session_db_dir>/explorer_fts.db`. The cache is built lazily on first search and
refreshed from source lesson metadata on subsequent searches.

If search results are stale but the course tree is correct:

1. Search again after saving the source file.
2. Restart `studyloop web` if the process was interrupted during indexing.
3. Delete `explorer_fts.db` only for search-index issues; it will be rebuilt on
   the next search and is not part of `sessions.db` migrations.

## Progress Or Struggles Missing

Struggles and progress live in `sessions.db` and are surfaced through
`study_progress`. Course Explorer writes web-marked struggles through
`POST /api/history/struggling-topics`, including provenance columns such as
`source_course` and `source_section`.

Run:

```bash
studyloop self-test
studyloop doctor --category database
```

If the database check fails, fix that first. If it passes but the Generate
panel's **Topic I'm struggling on** list is empty, confirm that the relevant
struggle is inside the selected window and has `confidence='struggling'`.

## `session-maint sync-full` Refuses

`sync-full` keeps `database.full_db_path` as a one-way mirror of the everyday database (see
[Setup Guide](setup-guide.md#database-too-large)). When it cannot do that safely it prints `❌`, a
reason code and the fix, and copies no session into the full database. The background sync that
runs after exports prints nothing, so run it by hand to see the reason:

```bash
session-maint sync-full
```

Each reason, and what to do:

- **`unbound_full`** — the full database already holds sessions but was never bound to this
  everyday database: an older StudyLoop's `sync-full` made it, or it is a copy, or another
  machine's. Keep that file (it may hold sessions that are nowhere else), point
  `database.full_db_path` at a new file, and run `sync-full` again; the first run binds the new
  file. Adopting an existing full database is not supported yet.
- **`instance_mismatch`** — the full database is bound to a different everyday database: another
  machine's, or this machine's before it was rebuilt (`session-maint compact` gives the rebuilt
  file a new identity). Same fix: keep the old file, point `database.full_db_path` at a new one.
  Rebinding is not supported yet.
- **`peer_ledger_present`** — this everyday database has replicated with a peer through
  `session-sync`, so it is not a single-writer database and is not mirrored by SQL. There is no
  fix in this release; its sessions stay in the everyday database (`session-maint vacuum` reclaims
  space).
- **`full_store_unavailable`** — the full database could not be opened as a file: the volume was
  unmounted, or the path names something that is not a database file. Mount the volume or correct
  `database.full_db_path`, then run `sync-full` again.
- **`managed_store_busy_or_unavailable`** — another program held one of the two databases while
  deletions were being reconciled. Wait, or stop what else is using them (the web app, an MCP
  server, another sync), then run again.
- **`controls_unstable`** or **`controls_changed`** — a deletion or forget changed while
  `sync-full` was reconciling deletions or about to copy. Run again; if it repeats, stop other
  StudyLoop processes first.
- **`immutable_collision`**, naming a table and a key — the full database holds a record under the
  same key with different content. Captured memory is never overwritten, so the copy stops. Do not
  edit either database: keep both files and report the table and key. Pointing
  `database.full_db_path` at a new file starts a fresh mirror in the meantime.
- **`noncanonical_override`** — `--db` names a database other than the configured
  `database.path`; the mirror belongs to the configured everyday database only. Run without `--db`.
- **`unclassified tier table: <name>`** — the everyday database has a memory table this version of
  StudyLoop does not know how to mirror, usually because a newer StudyLoop wrote it. Run the
  current StudyLoop on this machine, then `sync-full` again. `prune` refuses the same way.
- **The two databases are on different schema versions**, or the everyday one is behind. Upgrade
  StudyLoop, run `session-export` once (it migrates the everyday database), then `sync-full`.
- **`Legacy SQL sync cannot transfer scoped or source-grounded memory`** — the configuration
  scopes memory (`memory.sync`, `memory.projects`, or a `memory.default_scope` other than
  `unclassified`). Scoped memory moves only through the structured replication protocol, so
  `sync-full` is not available with that configuration and sessions stay in the everyday database.

`session-maint prune` reporting every old session as skipped (not in the full database) means the
full database is behind: something was captured after the last `sync-full`. Run `sync-full`, fix
any refusal above, then `prune` again.
