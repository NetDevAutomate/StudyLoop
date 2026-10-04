# Lane W — wave 2 implementation brief (W1–W5)

Read first: `briefs/00-common.md`, `briefs/W-web-labs.md` (owned globs, forbidden list — still
binding, with the two additions below), `council/2026-10-04-m0-arbitration.md` **Q2** (the route
ruling you implement), `specs/web-ui/spec.md` and `specs/session-transports/spec.md` (this
change's deltas), `design.md` §2 and §7. Lanes S, C, R, T are **merged on `main`**: start with
`git merge main` in your worktree (`/Users/ataylor/code/personal/tools/studyloop-wt/module-web-labs`,
branch `feat/module-web-labs`, currently at the wave-0 base), prove the import path
(`studyloop.__file__` under the worktree), then work red-first exactly as the other lanes did:
failing test → `evidence/W/<name>.red.txt` (command on line 1, sha + UTC) → implementation →
`.green.txt`; pre-commit through `git commit`, never `--no-verify`/`SKIP=`; nothing pushed; nothing
written to the main checkout.

## The code you build on (all on `main`; read, do not edit)

- **Hop (lane R)** `modules/hop.py`: `ROUTE = "/api/modules/practice-check"`, `TOKEN_HEADER =
  "X-StudyLoop-Session-Token"`, state-file keys `TOKEN_KEY = "practice_check_token"`, `PORT_KEY =
  "web_port"`, `SESSION_KEY = "study_session_id"`; the body is exactly `hop.ENVELOPE_FIELDS`
  (`check_result_fields`); `_outcome_from_response` maps any non-2xx to `error "http <code>"`, so
  the server's status codes are the contract the learner sees. Read lines 85–100 and 254–300.
- **Envelope (lane T)** `session/module_delivery.py`: `validate_envelope(mapping) ->
  PracticeCheckEnvelope` (`extra=forbid`; raises `EnvelopeValidationError` naming fields, never
  values), `async deliver_to_active_session(envelope) -> DeliveryOutcome` with `status` one of
  `delivered | no_active_session | transport_closed | timed_out | unsupported_framing | error`
  and a `reason`. The server never renders text itself for the wire — T renders inside `deliver`.
- **Store / manifest (lane C)** `modules/store.py` (`load_lockfile()`, `LockEntry`,
  `snapshot_dir(entry)`), `modules/manifest.py` (`Manifest.prerequisites[].id`), decks under
  `<snapshot>/decks/*.json` (`PracticeDeck` from lane S); fixture module
  `tests/fixtures/modules/valid-scaffold` and `tests/fixtures/modules/runner-offline`.
- **Runner (lane R)** `cli/_drill.py` carries `prerequisites: tuple[str, ...] = ()` and a
  `TODO(module-contract-v1)` at ~line 239: wire `Manifest.prerequisites[].id` from the located
  module's `module.yaml` into it and delete the TODO (owned-glob addition #1: that block only).
- **Session state** `session_state.py`: `write_session_state(dict)` / `read_session_state()`;
  files are written `0o600` via `_write_file_secure`. `session/orchestrator.py:276-278` writes
  `web_pid`/`web_port` when the web process claims a session — mint the token there (owned-glob
  addition #2: those lines plus a helper beside them).
- **Seam test** `tests/test_module_lane_seams.py` shows the three lanes' real code together.

## Tasks

**W1 (red-only commit).** `tests/test_web_modules.py` (`TestClient`): session options carry no
Labs entry with an empty lockfile and a Labs entry listing deck/task ids and prompts after an
install (use `ModuleStore(tmp).add(valid-scaffold)` with `store.default_store_root` patched);
`POST /api/modules/practice-check` without the header → 401, with a wrong token → 403, from a
non-loopback client address → 403, a body with an extra field → 422 naming the field, a valid
body → 200 with `{"status": <DeliveryStatus>, "reason": ...}` (with no active session the status
is `no_active_session`), the same `(attempt_id, phase)` again → 409, a sixth envelope within a
minute for one session → 429; `tests/js/module-labs.test.js` for the component. Verify every test
red (no route, no component), keep it red.

**W2.** `web/routes/modules.py`: the route per M0 Q2 — loopback check on `request.client.host`
(not a header); token compared in constant time against `practice_check_token` in the session
state; the session named by the token is the active one or 403; replay dedup on `(attempt_id,
phase)` and the rate limit (one envelope per phase per attempt; burst 5/min per session) in
process memory keyed by session; `validate_envelope` then `await deliver_to_active_session`; the
outcome's `status`/`reason` returned as JSON with 200 — a delivery that did not land is a 200
whose status says so, because the hop already treats non-2xx as its own error. `GET
/api/modules/labs` (or the `_options.py` entry) lists installed modules' decks and tasks **by id
and prompt only — never `hint`, `solution` or `mentorNotes`** (web-ui spec scenario 3). Labs in
`index.html`/`components.js`/`style.css` + `static/js/labs.js`, hidden when the lockfile is
empty; start = `POST /api/modules/labs/start` which runs `studyloop drill setup` for the chosen
drill **inside the one claimed session** (reuse the session's existing subprocess/run machinery —
read `web/routes/session/` first; no second session, no browser-side execution) and is
cancellable. W1 tests green; `just test-web`, `just test-js` green.

**W3.** `cli/__init__.py`: add `"module": "studyloop.cli._module:module_group"` and `"drill":
"studyloop.cli._drill:drill_group"` to the LazyGroup map (Click, not Typer); `web/app.py`: one
`include_router` line. `_drill.py`: the prerequisites wiring above. Verify `studyloop module
--help`, `studyloop drill --help`, the API route table, and that `test_module_cli.py`'s
"root CLI has no `module` command" test is **updated, not deleted** (it now asserts the
registration). Add a `test_module_lane_seams.py` case: a located module's manifest prerequisites
reach `runner.resolve_prerequisites` (fake tool on a scratch PATH).

**W4.** `tests/e2e/test_module_labs_journey.py` (Playwright, existing `just e2e` tier, hermetic
world with a fake agent — read `tests/e2e/_env.py` and `test_body_double_journey.py` for the
pattern): list → start inside the claimed session → the mentor pane shows the delivered block
(`<<<studyloop:practice_check` … `<<<end studyloop:practice_check>>>`, every tail line prefixed
`| `) → cancel → reload re-attaches → keyboard (Tab/Shift-Tab/Escape) → `module remove` → Labs
gone; explicit module timeout. `just e2e` takes the machine lock: run it alone, once, and keep the
transcript; it is NOT part of `just preflight`.

**W5.** Docs lease is free (contributor guide merged at 6a3f45d2; lane S3 — `docs/module-contract.md`
— is unstarted, so you own it too: write that page from the spec deltas and `module new --help`,
with the "Adding a module" checklist, under the contributor-guide rules in
`docs/contributor-documentation.md`; the drift test `test_contributor_guide_drift.py` pins every
command and path you show — run it). `CHANGELOG.md` under `[Unreleased]` → Added, one learner-facing
bullet per user-visible change (module add/check/new, drill, Labs). `acceptance/test_module_kdrill_live.py`
gated `STUDYLOOP_ACC=1 STUDYLOOP_LIVE=1` with a sentinel-cluster assertion, skipping cleanly
without the env vars; UAT rubric for Personas A and B under `acceptance/uat/` (design.md §6).
`just docs` strict green.

## Gate before you report

`env -u VIRTUAL_ENV just test-web && just test-js`; `uv run pytest packages/studyloop/tests/test_web_modules.py
packages/studyloop/tests/test_module_cli.py packages/studyloop/tests/test_module_lane_seams.py
packages/studyloop/tests/test_contributor_guide_drift.py packages/studyloop/tests/test_docs_drift.py
-q -p no:cacheprovider`; `just lint && just typecheck`; `just docs`; `just e2e` once for W4. The
coordinator runs the full preflight at merge. Tick W1–W5 in `tasks.md` (that file only).

## Report (≤ 900 words)

Verbatim commit log; red/green transcript list; the route's status-code table as implemented;
the rendered Labs list for `valid-scaffold` (ids and prompts only); the e2e transcript summary
line; every contract gap you decided rather than guessed, as the other lanes did.
