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

For LAN use:

```bash
studyloop web --lan
```

Configured LAN passwords are not printed. Generated one-time passwords are
printed once. If a phone or tablet cannot connect, check that the shown LAN URL
uses the host's real LAN address and that the device is on the same network.

## The Browser Terminal Shows "No Terminal Available"

The live console has two renderers, chosen by the session's `transport`:

| `transport` | Renders as |
| --- | --- |
| `pty` (default) | xterm.js, fed by the PTY over a WebSocket |
| `acp` | structured ACP chat events |

Anything else has **no browser renderer**. The console reports an explicit
`unavailable` state — status `No terminal available`, plus a message naming the
transport it cannot render and telling you to end the session and start it again
on the browser terminal or ACP.

The usual cause is `STUDYLOOP_TRANSPORT=ttyd` in the environment. That path is
still honoured server-side, but it is no longer a browser rendering option:

```bash
env | grep STUDYLOOP_TRANSPORT
```

Unset it and start a new session:

```bash
unset STUDYLOOP_TRANSPORT
studyloop web
```

Installing `ttyd` does **not** fix this and is not required for the terminal
panel. The ttyd browser surface was retired deliberately, because without the
binary the old iframe rendered an empty frame that was indistinguishable from a
hang. See [ADR-0005](adr/0005-retire-ttyd-browser-surface.md) for the reasoning
and for what remains on the server path.

If the transport is already `pty` and the panel still reports no terminal, the
server did not return a connection for the session. Ending and restarting the
session clears this; the message says so rather than leaving a blank pane.

## The Terminal Is Empty After A Page Refresh

This is a known limitation. What holds today:

- **The session survives the refresh.** A disconnect starts a detach grace
  window on the server (90 s by default; `STUDYLOOP_WS_GRACE_SECONDS`
  overrides it), so the agent process keeps running and
  `GET /api/session/state` still reports the session after the reload.
- **The reattach is not automatic yet.** `liveAgentConsole.init()` reads
  `GET /api/session/state` on load and *attempts* to re-adopt a live session
  it owns, but that path is not yet reliable (the end-to-end test that proves
  it is currently red) — an empty terminal after a refresh can happen even
  when nothing on your machine is misconfigured.

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

This is a target, not a filesystem quota. The Stub backend returns the exact
requested count. External providers can still under- or over-produce if they do
not follow the prompt; invalid shapes fail validation and show as task errors.
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
