"""FastAPI application factory for the study PWA.

Replaces the stdlib http.server with FastAPI + uvicorn.
Serves JSON API endpoints and static PWA files.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.datastructures import MutableHeaders
from starlette.responses import RedirectResponse, Response

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

STATIC_DIR = Path(__file__).parent / "static"


class RevalidatedStaticFiles(StaticFiles):
    """Static files the browser must revalidate before reusing.

    ``/`` is served ``no-store``, but without a Cache-Control of their own the
    CSS and JS it loads were subject to heuristic freshness -- commonly a tenth
    of the file's age -- so a stylesheet unchanged for weeks was reused for days
    without asking. After an update the learner got the new page beside the old
    CSS and JS. ``no-cache`` keeps the copy and asks first; an unchanged file
    costs a 304 against the ETag Starlette already sends.
    """

    def file_response(self, *args: Any, **kwargs: Any) -> Response:
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "no-cache"
        return response


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Prepare the database, then run the session-slot reaper for the app's life.

    The reaper is the backstop for every way the single-session slot can be
    pinned that the WebSocket grace timer cannot see — a session whose socket
    never attached, or one ended/cleaned from another process. Without it those
    slots stay occupied until the server restarts and every ``/session/start``
    409s. Started on app startup and torn down on shutdown so a stop cannot
    leave an orphaned agent child owned by a timer that will never fire.

    Schema preparation runs FIRST. It is not that the reaper does DDL — its first
    tick sleeps before doing anything and reads only session state — but a slow
    first ``init_db`` should not overlap a tick against a half-built database.

    The query-encoder warm (lane A1, council D-3) starts here too: a
    background thread, so a cold or disabled warm never delays serving the
    first request. It reports through
    ``agent_session_tools.retrieval.encoder_warm_status()`` — a disabled or
    failed warm is a status to render (lane A4), never a reason this
    coroutine should raise.
    """
    from agent_session_tools import retrieval
    from studyloop.web._schema_init import prepare_schema
    from studyloop.web.routes.session import _grace

    prepare_schema()
    retrieval.warm_query_encoder(surface=retrieval.SURFACE_WEB)
    _grace.start_reaper()
    try:
        yield
    finally:
        await _grace.shutdown()


# CSP for a fully same-origin, no-build static app: every script and vendored
# library loads from this origin (verified in ttyd retirement stage 4 — no
# CDN <script src>, no data: script, and the two former inline <script>
# blocks in index.html were moved to files in the same stage). Three
# documented, load-bearing exceptions on top of that, each found by
# reproduction (loading every page with console-error capture), not
# guessed in advance:
#
# - script-src 'unsafe-eval': Alpine.js evaluates every `x-data`/`x-text`/
#   `x-show`/`@click`/etc. expression string via `new Function(...)`
#   internally (this is Alpine's own documented CSP constraint, not
#   specific to this app). Without it, `script-src 'self'` alone still
#   loads Alpine correctly but every directive throws a CSP `pageerror` the
#   instant it tries to evaluate an expression — the whole app's
#   interactivity goes dark (bindings render empty, `@click` handlers never
#   fire) while the page still "loads". `'self'`-only script SOURCES still
#   hold: no CDN, no inline block, no data: URI.
# - style-src 'unsafe-inline': Alpine's `:style` bindings and `x-transition`
#   set inline `style` ATTRIBUTES at runtime (there is no way to nonce an
#   attribute, only a <style> element or <link>), and xterm.js's own DOM
#   rendering does the same for cursor/viewport positioning.
# - connect-src data: (dev_mode ONLY, see _build_csp below): `--dev
#   --dev-engine ghostty` (opt-in developer renderer,
#   vendor/dev/js/ghostty-web-0.4.0.js) bootstraps its WASM VT100 parser via
#   `fetch("data:application/wasm;base64,...")` rather than
#   `WebAssembly.instantiateStreaming` against a same-origin URL. Without
#   this, `default-src 'self'` (connect-src's fallback) blocks that fetch
#   and every `--dev` session fails to render with a CSP-caused 404. Scoped
#   to `connect-src` only — script-src stays `'self' 'unsafe-eval'`, no
#   `data:` script source. Scoped to dev_mode only — a learner who never
#   passes `--dev` gets no `data:` relaxation at all, since ghostty-web is
#   the sole consumer (found in the M1 council, A2: the first cut sent this
#   unconditionally, in every mode, for a --dev-only need).
# - media-src 'self' blob:: the server voice tier plays the host's WAV
#   through `new Audio(URL.createObjectURL(blob))` (tts-engine.js
#   `_speakServer`), and `'self'` does not match a blob: URL. With no
#   media-src, media fell back to `default-src 'self'` and the browser
#   refused every utterance -- /api/tts/speak answered 200 audio/wav, play()
#   rejected, the badge said "Kokoro (server)" and nothing was heard, from
#   2 Sep (when default-src arrived) until 29 Sep. Reproduced in Chromium
#   against the real host engine; the same page with the policy bypassed
#   played. A blob: URL can only be minted by this origin's own script, and
#   the exception is media-only: script-src stays `'self' 'unsafe-eval'`.
#
# R-13c adds the four directives a CSP audit checks for by name rather than
# trusting default-src to cover them, each verified free of cost here:
# - object-src 'none': no <object>/<embed>/<applet> anywhere in static/.
# - base-uri 'self': no <base> tag anywhere in index.html (verified —
#   zero matches), so nothing currently relies on the default (document
#   URL); pinning it just forecloses a future injected <base> from
#   silently retargeting every relative URL on the page.
# - form-action 'self': every <form> in index.html uses `@submit.prevent`
#   (Alpine intercepts the submit event) with no `action=` attribute at
#   all (verified — zero matches), so no browser-native form POST target
#   exists to restrict; this only forecloses one from appearing later.
# - frame-ancestors 'none': the CSP-native form of the `X-Frame-Options:
#   DENY` already sent below. Kept alongside it, not instead of it — CSP
#   frame-ancestors is unsupported in a few embedded/legacy contexts that
#   still honour X-Frame-Options, and the reverse is true for modern ones
#   that prioritise CSP; sending both is the documented belt-and-braces.
def _build_csp(dev_mode: bool) -> str:
    """Build the CSP, adding the dev_mode-only connect-src exception only
    when --dev is actually active — see the module comment above."""
    connect_src = "connect-src 'self' data:" if dev_mode else "connect-src 'self'"
    return (
        "default-src 'self'; script-src 'self' 'unsafe-eval'; "
        f"style-src 'self' 'unsafe-inline'; {connect_src}; "
        "media-src 'self' blob:; "
        "object-src 'none'; base-uri 'self'; frame-ancestors 'none'; "
        "form-action 'self'"
    )


class SecurityHeadersMiddleware:
    """Add security headers to every HTTP response — including one built
    from an unhandled exception.

    R-13d: this used to be a Starlette ``BaseHTTPMiddleware`` subclass.
    ``BaseHTTPMiddleware``'s ``dispatch()`` only runs its post-``call_next``
    code on the SUCCESS path — when a route raises, Starlette's own
    ``ExceptionMiddleware``/``ServerErrorMiddleware`` builds the 404/500
    response directly against the raw ASGI ``send`` callable, downstream of
    where ``dispatch()`` would have added headers. The result: a 500 (or a
    404 from routing) shipped with NONE of these headers, and the only
    test this middleware had exercised the all-success `GET /` path.

    A pure ASGI middleware wrapping ``send`` fixes this structurally: it
    intercepts every ``http.response.start`` message regardless of which
    layer emitted it, success or error alike. It is also naturally inert
    for the ``websocket`` scope — a WS upgrade has no ``http.response.
    start`` message to intercept (it sends ``websocket.accept``/``.close``
    instead), so these headers correctly never reach the upgrade response.
    That is not a gap: a 101 Switching Protocols response has no document
    to render, so a content policy has nothing to police there.
    """

    def __init__(self, app) -> None:  # type: ignore[no-untyped-def]
        self.app = app

    def __getattr__(self, name: str):  # type: ignore[no-untyped-def]
        # This now wraps the fully-built FastAPI app (see create_app()'s
        # return statement) rather than being registered via
        # app.add_middleware(), so callers that hold onto create_app()'s
        # return value and reach for .state/.routes/etc. (several tests do)
        # need those to keep working transparently.
        return getattr(self.app, name)

    async def __call__(self, scope, receive, send) -> None:  # type: ignore[no-untyped-def]
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # self.app IS the wrapped FastAPI instance directly (this class
        # wraps the finished app object rather than being registered via
        # add_middleware() -- see create_app()'s return statement), so its
        # .state is reached straight off that reference. scope["app"] is
        # NOT usable here: Starlette only sets it once the inner app's own
        # __call__ runs, which is after this line, not before it.
        app_state = getattr(self.app, "state", None)
        dev_mode = bool(getattr(app_state, "dev_mode", False)) if app_state is not None else False
        csp = _build_csp(dev_mode)

        async def send_wrapper(message):  # type: ignore[no-untyped-def]
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers["X-Content-Type-Options"] = "nosniff"
                # DENY: no iframe surface exists anywhere in static/ (the
                # ttyd iframe fallback this used to justify SAMEORIGIN for
                # was retired — see ADR-0005 and the ttyd retirement, stage 4).
                headers["X-Frame-Options"] = "DENY"
                headers["Content-Security-Policy"] = csp
                headers["Referrer-Policy"] = "same-origin"
                headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
                # X-XSS-Protection is deliberately NOT set: deprecated, a
                # no-op (or an XSS vector via its filter) in every modern
                # browser, superseded by the CSP above.
            await send(message)

        await self.app(scope, receive, send_wrapper)


class RequestBoundaryMiddleware:
    """Refuse a request before routing when its ``Host`` is not one this server
    answers to (``ws_origin.host_allowed``), or, when a per-process server
    secret is configured, when an ``/api/*`` request or WebSocket lacks it.

    DNS rebinding (F-WEB-03, 2026-10-21 review): a page on attacker.example
    re-resolves its own name to 127.0.0.1 and becomes same-origin with the
    dashboard, every ``/api/*`` route and the terminal WebSocket. The browser
    still sends ``Host: attacker.example``, so checking Host here, ahead of every
    route, middleware and Basic-auth check, is what closes it. HTTP gets 400;
    a WebSocket is closed with 1008 before accept, which the client sees as a
    refused upgrade.

    Server secret (F-WEB-20): ``studyloop web`` mints one per process. ``/api/*``
    (HTTP 403) and both WebSockets (1008) require it as the HttpOnly,
    SameSite=Strict ``studyloop_auth`` cookie. SameSite=Strict keeps the browser
    from attaching it to any cross-site request, which closes cross-site form
    posts and socket opens. The cookie is handed out only by
    ``BootstrapTokenMiddleware``, to a browser that presents the secret itself
    (D2, council pass 3): before that, any local process that loaded ``/`` was
    given it. Empty secret, the ``create_app`` default, turns this half off.

    Wraps the finished FastAPI app (inside ``SecurityHeadersMiddleware``, so a
    refusal still carries the security headers) and forwards attribute access
    to it the same way, so ``create_app().state`` and friends keep working.
    """

    def __init__(self, app, *, server_secret: str = "") -> None:  # type: ignore[no-untyped-def]
        self.app = app
        self._server_secret = server_secret

    def __getattr__(self, name: str):  # type: ignore[no-untyped-def]
        return getattr(self.app, name)

    async def __call__(self, scope, receive, send) -> None:  # type: ignore[no-untyped-def]
        if scope["type"] not in {"http", "websocket"}:
            await self.app(scope, receive, send)
            return

        from starlette.datastructures import Headers

        from studyloop.web.ws_origin import (
            host_allowed,
            is_in_process_test_scope,
            requires_server_secret,
            server_secret_presented,
        )

        headers = Headers(scope=scope)
        if not host_allowed(
            headers.get("host", ""), in_process_test=is_in_process_test_scope(scope)
        ):
            await _refuse(scope, receive, send, status=400, detail="Invalid host header")
            return

        secret = self._server_secret
        if (
            secret
            and requires_server_secret(scope.get("path", ""))
            and not server_secret_presented(headers.get("cookie", ""), secret)
        ):
            await _refuse(
                scope,
                receive,
                send,
                status=403,
                detail="This request lacks the StudyLoop server cookie. Reload the page.",
                code="server_secret_required",
            )
            return

        await self.app(scope, receive, send)


#: The pages a browser opens to sign in: ``/`` (the printed URL) and ``/session``
#: (the URL the launcher opens).
_FRONT_DOOR_PATHS = frozenset({"/", "/session"})

#: The sign-in form carries one token; anything far larger is not a sign-in.
_MAX_SIGN_IN_FORM_BYTES = 4096

_SIGN_IN_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>StudyLoop - sign in with the access token</title>
<style>
  body {{ font-family: system-ui, sans-serif; max-width: 34rem; margin: 3rem auto;
         padding: 0 1rem; line-height: 1.5; color: #1f2933; background: #fbfbf8; }}
  h1 {{ font-size: 1.4rem; }}
  label {{ display: block; font-weight: 600; margin-top: 1.25rem; }}
  input {{ width: 100%; box-sizing: border-box; font-size: 1rem; padding: 0.5rem;
          margin-top: 0.25rem; }}
  button {{ margin-top: 0.75rem; font-size: 1rem; padding: 0.5rem 1rem; }}
  .error {{ border-left: 4px solid #b42318; padding: 0.25rem 0.75rem; background: #fdecea; }}
</style>
</head>
<body>
<main>
<h1>StudyLoop needs its access token</h1>
{error}
<p>Open StudyLoop from the terminal or launcher that started it: the address it printed or
opened carries the token. If <code>studyloop web</code> was restarted, a tab opened before the
restart has lost its access; reopen it from the new address.</p>
<form method="post" action="/">
<label for="token">Access token (or the whole address)</label>
<input id="token" name="token" type="password" autocomplete="off" autocapitalize="off"
       spellcheck="false" required>
<button type="submit">Open StudyLoop</button>
</form>
</main>
</body>
</html>
"""


def _sign_in_page(*, status: int, error: str = "") -> Response:
    """The page asking for the token. Never echoes what the client presented."""
    error_html = f'<p class="error" role="alert">{error}</p>' if error else ""
    return HTMLResponse(
        _SIGN_IN_PAGE.format(error=error_html),
        status_code=status,
        headers={"Cache-Control": "no-store"},
    )


def _token_from_paste(value: str) -> str:
    """The token in what a learner pasted: the token alone, or the printed address."""
    from urllib.parse import parse_qsl

    from studyloop.web.ws_origin import BOOTSTRAP_QUERY

    value = value.strip().split("#", 1)[0]
    query = value.split("?", 1)[1] if "?" in value else value
    tokens = [v for k, v in parse_qsl(query) if k == BOOTSTRAP_QUERY]
    return tokens[0] if len(tokens) == 1 else value


class BootstrapTokenMiddleware:
    """Hand the server cookie only to a browser that presents the server secret
    (D2, council pass 3, Jupyter's token model).

    ``GET /`` and ``GET /session`` with ``?token=<secret>`` set the HttpOnly,
    SameSite=Strict cookie and answer 303 to the same path without the token, so
    it does not stay in the address bar; a wrong token is 403 with no cookie.
    ``GET /`` from a browser without the cookie gets a small page asking for the
    token, whose form posts it to ``POST /``, the same acceptance. Every answer
    here is ``Cache-Control: no-store``. Everything else passes through: the
    cookie gate on ``/api/*`` and the WebSockets is ``RequestBoundaryMiddleware``'s.

    Registered inside Basic auth, so on a ``--lan``/``--bind`` server the
    password is still asked for first and the token never stands in for it.
    Empty secret (in-process ``create_app``) makes this a pass-through.
    """

    def __init__(self, app, *, server_secret: str = "") -> None:  # type: ignore[no-untyped-def]
        self.app = app
        self._server_secret = server_secret

    async def __call__(self, scope, receive, send) -> None:  # type: ignore[no-untyped-def]
        path = scope.get("path", "")
        if not self._server_secret or scope["type"] != "http" or path not in _FRONT_DOOR_PATHS:
            await self.app(scope, receive, send)
            return

        from urllib.parse import parse_qsl, urlencode

        from starlette.datastructures import Headers

        from studyloop.web.ws_origin import BOOTSTRAP_QUERY, server_secret_presented

        method = scope.get("method", "")
        if method == "POST" and path == "/":
            await self._accept_form(scope, receive, send)
            return
        if method not in {"GET", "HEAD"}:
            await self.app(scope, receive, send)
            return

        pairs = parse_qsl(scope.get("query_string", b"").decode("latin-1"), keep_blank_values=True)
        tokens = [value for key, value in pairs if key == BOOTSTRAP_QUERY]
        if tokens:
            rest = urlencode([(key, value) for key, value in pairs if key != BOOTSTRAP_QUERY])
            presented = tokens[0] if len(tokens) == 1 else ""
            response = self._accept(presented, location=f"{path}?{rest}" if rest else path)
            await response(scope, receive, send)
            return

        cookie = Headers(scope=scope).get("cookie", "")
        if path == "/" and not server_secret_presented(cookie, self._server_secret):
            await _sign_in_page(status=200)(scope, receive, send)
            return

        await self.app(scope, receive, send)

    def _accept(self, presented: str, *, location: str) -> Response:
        """303 + cookie for the right token; the sign-in page and 403 for anything else."""
        from studyloop.web.ws_origin import AUTH_COOKIE, secret_matches

        if not secret_matches(presented, self._server_secret):
            return _sign_in_page(
                status=403,
                error="That token is not this server's. Copy it again from the terminal.",
            )
        response = RedirectResponse(url=location, status_code=303)
        response.headers["Cache-Control"] = "no-store"
        response.headers.append(
            "set-cookie",
            f"{AUTH_COOKIE}={self._server_secret}; HttpOnly; SameSite=Strict; Path=/",
        )
        return response

    async def _accept_form(self, scope, receive, send) -> None:  # type: ignore[no-untyped-def]
        from urllib.parse import parse_qsl

        from starlette.datastructures import Headers

        from studyloop.web.ws_origin import BOOTSTRAP_QUERY

        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body += message.get("body", b"")
            if len(body) > _MAX_SIGN_IN_FORM_BYTES:
                too_large = _sign_in_page(status=413, error="That is far too long to be a token.")
                await too_large(scope, receive, send)
                return
            if not message.get("more_body", False):
                break

        presented = ""
        content_type = Headers(scope=scope).get("content-type", "")
        if content_type.split(";", 1)[0].strip().lower() == "application/x-www-form-urlencoded":
            fields = parse_qsl(body.decode("latin-1"), keep_blank_values=True)
            tokens = [value for key, value in fields if key == BOOTSTRAP_QUERY]
            if len(tokens) == 1:
                presented = _token_from_paste(tokens[0])
        await self._accept(presented, location="/")(scope, receive, send)


async def _refuse(  # type: ignore[no-untyped-def]
    scope, receive, send, *, status: int, detail: str, code: str = ""
) -> None:
    """Answer a refused request: an HTTP status, or a pre-accept 1008 close."""
    if scope["type"] == "websocket":
        await send({"type": "websocket.close", "code": 1008})
        return
    content = {"code": code, "detail": detail} if code else {"detail": detail}
    await JSONResponse(status_code=status, content=content)(scope, receive, send)


def create_app(
    study_dirs: list[str] | None = None,
    username: str = "study",
    password: str = "",
    dev_mode: bool = False,
    dev_engine: str | None = None,
    server_secret: str = "",
) -> FastAPI:
    """Create and configure the FastAPI application.

    Args:
        study_dirs: List of directory paths containing flashcard/quiz content.
        username: Username for HTTP Basic Auth (LAN protection). Default: "study".
        password: Optional password for HTTP Basic Auth (LAN protection).
                  If empty, no authentication is applied.
        dev_mode: When True, the UI loads an alternative renderer instead of
                  xterm.js. Default (False) preserves existing behaviour exactly.
        dev_engine: Which registered dev engine (``studyloop.web.dev_engines
                    .DEV_ENGINES``) to use in dev mode. Defaults to
                    ``DEFAULT_DEV_ENGINE`` ("ghostty") when dev_mode=True and
                    this is not set. Ignored (and left unvalidated) when
                    dev_mode=False. Raises ValueError at startup for an unknown
                    engine name.
        server_secret: Per-process secret ``/api/*`` plus both WebSockets require
                    as a cookie (``RequestBoundaryMiddleware``), handed out only to
                    a browser that presents it as ``?token=`` or through the
                    sign-in form (``BootstrapTokenMiddleware``). ``studyloop web``
                    mints one at start; empty (the default for in-process
                    callers) leaves both off. The Host check applies either way.
    """
    from studyloop.web.dev_engines import resolve_dev_engine

    app = FastAPI(
        title="StudyLoop",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=_lifespan,
    )
    from agent_session_tools.context.scope import ScopeError

    @app.exception_handler(ScopeError)
    async def context_scope_error(_request: Request, exc: ScopeError) -> JSONResponse:
        return JSONResponse(
            status_code=409,
            content={"code": "context_scope_unavailable", "detail": str(exc)},
        )

    from studyloop.web.context_response import ContextResponseMiddleware

    app.add_middleware(ContextResponseMiddleware)

    # Store config on app state for route access
    app.state.study_dirs = study_dirs or []
    app.state.dev_mode = dev_mode
    # None unless dev_mode is on — `--dev-engine` is inert without `--dev`.
    # Resolved (and validated) up front so a bad --dev-engine fails at startup,
    # not on first page load.
    app.state.dev_engine = resolve_dev_engine(dev_engine) if dev_mode else None
    app.state.explorer_tree_cache = None
    app.state.explorer_tree_fingerprint = None
    app.state.session_options_targets_cache = None
    app.state.session_options_targets_fingerprint = None

    # The sign-in front door (D2): registered BEFORE Basic auth, which makes it
    # the inner of the two, so a LAN password is still asked for first.
    if server_secret:
        app.add_middleware(BootstrapTokenMiddleware, server_secret=server_secret)

    # Optional password protection (LAN mode)
    if password:
        from studyloop.web.auth import BasicAuthMiddleware

        app.add_middleware(BasicAuthMiddleware, username=username, password=password)

    # Register API routes
    from studyloop.web.routes import (
        artefacts,
        backlog,
        body_double,
        cards,
        content_gen,
        courses,
        explorer,
        history,
        mastery,
        modules,
        notes,
        now,
        parking,
        plans,
        second_brain,
        session,
        tts,
    )
    from studyloop.web.routes import retrieval as retrieval_routes

    app.include_router(courses.router, prefix="/api")
    app.include_router(cards.router, prefix="/api")
    app.include_router(history.router, prefix="/api")
    app.include_router(now.router, prefix="/api")
    app.include_router(backlog.router, prefix="/api")
    app.include_router(mastery.router, prefix="/api")
    app.include_router(session.router, prefix="/api")
    app.include_router(content_gen.router, prefix="/api")
    app.include_router(explorer.router, prefix="/api")
    app.include_router(artefacts.router)
    app.include_router(body_double.router, prefix="/api")
    app.include_router(
        modules.router, prefix="/api"
    )  # module-contract v1: Labs + practice-check hop
    # Topic exercises are a developer preview. Keep the router absent (404),
    # rather than registered-and-refusing, unless the web process was started
    # explicitly with `studyloop web --dev`; otherwise the API would remain a
    # hidden production backdoor after CLI/MCP discovery was gated.
    if dev_mode:
        from studyloop.web.routes import exercises

        app.include_router(exercises.router, prefix="/api")
    app.include_router(notes.router, prefix="/api")
    app.include_router(parking.router, prefix="/api")
    app.include_router(plans.router, prefix="/api")
    app.include_router(second_brain.router, prefix="/api")
    app.include_router(tts.router, prefix="/api")
    # The encoder-warm status chip reads this (lane A4): the boot warm takes
    # seconds and was previously invisible to a learner searching in that window.
    app.include_router(retrieval_routes.router, prefix="/api")

    try:
        from studyloop.web.routes.session._options import warm_session_options_index

        warm_session_options_index(app)
    except Exception:
        pass

    # Pomodoro config endpoint — serves configured durations for the slider
    @app.get("/api/config/pomodoro")
    async def pomodoro_config() -> dict:
        try:
            from studyloop.settings import load_settings

            pom = load_settings().pomodoro
            return {
                "focus_minutes": pom.focus,
                "short_break_minutes": pom.short_break,
                "long_break_minutes": pom.long_break,
                "cycle_length": pom.cycles,
            }
        except Exception:
            return {
                "focus_minutes": 25,
                "short_break_minutes": 5,
                "long_break_minutes": 15,
                "cycle_length": 4,
            }

    # Serve index.html at root (no-cache to prevent stale SW/browser cache).
    # In dev_mode=True the HTML is read and renderer-specific tags are injected
    # so the client-side JS swaps Terminal at runtime.
    @app.get("/", response_model=None)
    async def index() -> Response:
        no_cache = {"Cache-Control": "no-cache, no-store, must-revalidate"}
        if not dev_mode:
            return FileResponse(STATIC_DIR / "index.html", headers=no_cache)
        html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
        # Every dev_mode=True request goes through the dev_engines registry.
        # The deprecated inline `dev_renderer` path that used to sit here
        # injected materially different markup (content="ghostty-web" plus the
        # *.umd.js/bootstrap pair) and shipped a second, byte-identical copy of
        # the 624 KB bundle. It was the only runtime consumer of the standalone
        # ghostty-vt wasm; the registry bundle embeds that wasm as a base64 data
        # URL instead, so removing the path removed ~1 MB of vendored assets.
        from studyloop.web.dev_engines import inject_dev_engine

        return HTMLResponse(content=inject_dev_engine(html, app.state.dev_engine), headers=no_cache)

    # Redirect /session to hash-routed study-session tab
    @app.get("/session")
    async def session_page() -> RedirectResponse:
        return RedirectResponse(url="/#study-session")

    # Mount static files LAST (catch-all)
    app.mount("/", RevalidatedStaticFiles(directory=str(STATIC_DIR)), name="static")

    # Security headers: wraps the FINISHED app object rather than being
    # registered via app.add_middleware(). Starlette always puts its own
    # ServerErrorMiddleware OUTSIDE every user-added middleware, specifically
    # so it can catch exceptions raised BY user middleware too -- which means
    # a middleware added via add_middleware() can never see the 500 response
    # ServerErrorMiddleware builds for an unhandled exception (R-13d).
    # Wrapping the app object here makes this the true outermost ASGI layer,
    # so it sees every response, error or not. SecurityHeadersMiddleware's
    # __getattr__ forwards .state/.routes/etc. to the wrapped FastAPI
    # instance, so it remains a drop-in replacement for every caller that
    # holds onto create_app()'s return value -- but it is not actually a
    # FastAPI subclass, hence the ignore below.
    #
    # RequestBoundaryMiddleware sits directly inside it: the first layer that
    # judges a request, ahead of routing and every add_middleware() layer
    # (Basic auth included), with only the header decorator outside it.
    return SecurityHeadersMiddleware(  # type: ignore[return-value]
        RequestBoundaryMiddleware(app, server_secret=server_secret)
    )
