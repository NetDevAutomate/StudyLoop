# ADR-0014: The dashboard cookie is issued only to a browser presenting the launcher's sign-in token; course artefacts and loopback origins sit inside the same boundary

**Status:** Accepted, 2026-10-22 (proposed and implemented the same day; the owner accepted the
eight pass-3 records together at 16:36 BST) · **Date:** 2026-10-22 · **Deciders:** council pass 3
of the 2026-10-21 full-repository review (five no-tool seats: kimi-k3, gpt-6-astra, grok-4.6,
deepseek-r1, mistral-large-3), arbitrated by argument by the review coordinator under the owner's
standing delegation; accepted by Andy Taylor (owner). · **Change:** 2026-10-22 council pass 3, rulings D2 (5–0), D9.1 (4–1) and D9.2 (4–1);
implemented in `96a10e10` (token), `bd0ac0f1` (artefacts), `4b4e41fa` (origins), `cd31ae2f`
(real-server test clients); merge `c10c5096` (lane E, `web-bootstrap-token`).

The council record (`reviews/2026-10-21-full-repo-review/`, gitignored, owner's machine only)
holds the seat transcripts; everything this record relies on is restated here. Symbols were read
at `309074c7`.

## Context

The 2026-10-21 review's lane 3 gave `studyloop web` its first real boundary: a per-process secret,
handed to the browser by `GET /` as an `HttpOnly; SameSite=Strict; Path=/` cookie; `/api/*`
answers 403 `server_secret_required` and both WebSockets (the agent terminal and content
generation) close 1008 without it; a Host allowlist of loopback names and IP literals; and an
Origin check that no longer trusts the request's own Host. That closed DNS rebinding and cross-site
WebSocket use, both pinned by tests including one against a real server.

Three gaps remained, each a design choice rather than a defect:

1. **Any process that could `GET /` on loopback received the cookie.** On a single-user macOS
   laptop that is the same user. On a shared Linux host or a lab VM, another OS user who can
   reach loopback could fetch `/`, take the cookie and drive the agent-terminal WebSocket, which is
   shell-equivalent. The product's stated model is single-user, so this was a threat-model
   question.
2. **Course artefacts were served outside the gate.** `web/routes/artefacts.py` serves
   `/artefacts/{course}/{type}/{filename}` (audio, video, slides), Host-checked and
   path-validated but not cookie-gated, because the gate covered `/api/*` only. Under (1) this
   would have become the only unauthenticated read of learner content.
3. **A loopback Origin was admitted on any port**, documented in `ws_origin.py` as a development
   convenience for a dev server on another port. The verified crux: `SameSite=Strict` partitions
   cookies by *site* (scheme plus registrable domain), **not by port**, so the server cookie rides
   along on a socket opened by a page served from any other loopback port. The Origin rule was
   therefore the only barrier against such a page driving the terminal socket. No dev server on
   another port exists in this repository (no `vite`/`dev` script in `package.json`, none in the
   `Justfile`), so the convenience had no in-repo user.

Two further facts were verified before ruling: `cli/_web.py` runs uvicorn at
`log_level="warning"`, so the default access logger is silent and a `?token=` URL would not be
written by it (a test now pins that a bootstrap request leaves no trace at WARNING, with a
positive control proving the capture would see an access-log line); and no template or script in
`packages/studyloop/src` builds an `/artefacts/...` URL, so gating the route breaks no in-repo
consumer while the dashboard page already holds the cookie.

## Decision

### D2: a launcher-minted sign-in token, Jupyter's model

`BootstrapTokenMiddleware` (`web/app.py`) is the only path that sets the cookie:

- `GET /` or `GET /session` with `?token=<secret>` sets the cookie and answers **303 to the same
  path without the query**, so the token does not stay in the address bar or history. Other
  query parameters survive the redirect. A wrong token is **403** with the sign-in page and no
  cookie; the presented value is never echoed. A repeated `token` parameter is refused.
- A bare `GET /` renders a small sign-in page (200) that says where the token is and what a
  restart does, with a form that posts to `POST /`, the same acceptance; the form accepts the
  token alone or the whole printed address pasted in, and is capped at 4096 bytes (413 above
  that).
- Every answer the middleware gives is `Cache-Control: no-store`.
- The launcher (`session/orchestrator.py`) mints the token, passes it to the child **by
  environment** (`STUDYLOOP_WEB_TOKEN`, as it already did for the `--lan` password, so it is never
  in the spawned process's argv) and opens `http://127.0.0.1:<port>/session?token=<secret>`
  itself. The child scrubs the variable from its own environment on start-up and refuses a
  malformed one.
- A hand-run `studyloop web` mints `secrets.token_urlsafe(32)` and prints the sign-in URL once,
  unwrapped (a URL folded across two lines cannot be copied or clicked). Each process mints its
  own token; a restart invalidates every tab, and the live console tells the learner honestly to
  reopen from the launcher or the printed address rather than pretending to recover.
- Under `--bind`/`--lan` with HTTP Basic, the password is still asked for first; the token never
  stands in for it (a token without Basic credentials is 401 and issues no cookie).
- The `practice_check` loopback hop (`modules/hop.py`) keeps its own per-session token minted into
  the owner-only session state file; it is not a browser and does not use the cookie.
- `create_app()` without a secret still serves the app, so the in-process test clients in files
  the lane did not own are unaffected; the real-server test clients (e2e, acceptance, wheel
  smoke, and the four hand-rolled `studyloop web` starts) sign in through one shared helper in
  `tests/_playwright_helpers.py`, which wraps Playwright's `Page.goto` so a browser context's
  first visit to a server the test process started goes through the real 303. The wrap fires
  only for registered servers, never when the URL already carries a token, is idempotent and
  has an explicit opt-out for tests of the sign-in itself.

Grounding adopted: Jupyter Server's token model, the canonical local-web-app precedent; OWASP
ASVS session binding (do not mint a session for an unauthenticated `GET /`).

### D9.1: course artefacts sit behind the same cookie

`requires_server_secret()` (`web/ws_origin.py`) covers `/artefacts` as well as `/api`; path
validation against the content base path is unchanged. Grounding: complete mediation, default
deny on every route that serves learner data. Option (c), gating only under `--lan`, was rejected
as a mode-dependent boundary.

### D9.2: a loopback Origin must share the server's port

`origin_allowed()` admits a loopback Origin only when its port equals the request Host's port.
The existing `STUDYLOOP_ALLOWED_ORIGINS` exact-match allowlist is the escape hatch for a dev
server on another loopback port; no new flag. Grounding: secure by default with an explicit,
already-existing hatch; the SameSite fact above is the technical reason.

## Alternatives considered

- **D2 (a): accept the single-user threat model and document it.** Rejected 5–0: the fix is
  cheap and well precedented, and the dashboard carries a shell-equivalent socket.
- **D2 (c): bind to a Unix domain socket owned by the user, reached through a tiny loopback
  proxy.** Closes the residual fully but changes the launch path on every OS and breaks the
  second-device case (ADR-0019). Rejected for now; the token model is the step that does not
  foreclose it.
- **D9.1 (b): leave `/artefacts` ungated as static, path-validated media.** Rejected: under D2 it
  would be the only unauthenticated learner-content read.
- **D9.2 (a) keep any-port / (c) keep and warn.** Rejected: the SameSite fact makes the Origin
  rule load-bearing, and no in-repo consumer loses anything.

Mistral's "paste on first launch" cost against D2 was wrong for the normal path: the launcher
opens the token URL itself; pasting is only for a hand-run server or a closed tab.

## Consequences

- **Threat model, stated plainly:** this closes "any process that can `GET /` on loopback". It
  does **not** close "a process already running as the learner": a same-UID process can read the
  child's environment or the owner-only state file, which is the same access level `--lan`'s
  password already had. Shared-host hardening beyond this is a separate design (D2 (c)).
- A tab left open across a `studyloop web` restart cannot recover on its own any more (the old
  per-process secret could be re-fetched from `/`; the token cannot). The console says so and
  points at the launcher; the e2e test of that path asserts the honest message, not a silent
  recovery.
- Every real-server test must sign in. The shared helper is the one place that knows how; a new
  test that starts its own `studyloop web` must give the child a token through it.
- The sign-in URL is the credential for that process. Printing it is deliberate (Jupyter does the
  same); the access logger is silent at WARNING and a test pins that.
- `session/start.py` still prints the LAN address without the token, and `studyloop study` does
  not yet pass `--bind` through (both ledgered in the review record for the owner).

## Verification

`packages/studyloop/tests/test_web_bootstrap_token.py` (the behaviours above, one test each, plus
the launcher's environment hand-off and the hand-run print), `test_web_security.py` (uncookied
`/artefacts` 403, cookied 200, traversal still 404; `origin_allowed` for other-port loopback,
same-port, and allowlisted exact origin), `test_playwright_helpers_cookie.py` and
`tests/js/live-agent-console-restart-cookie.test.js`. Coordinator probe against a real
`studyloop web` on the lane tree: bare `GET /` no cookie; wrong token 403; right token 303 with
the query stripped and the cookie set; `/api` and `/artefacts` 403 without the cookie and 200 with
it; foreign `Host` 400; the token appeared in the server log only as the printed sign-in URL.
`just e2e` on the merged head: 600 passed, 15 skipped, 0 failed.
