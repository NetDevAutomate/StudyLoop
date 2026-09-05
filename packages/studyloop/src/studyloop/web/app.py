"""FastAPI application factory for the study PWA.

Replaces the stdlib http.server with FastAPI + uvicorn.
Serves JSON API endpoints and static PWA files.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import FastAPI
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from starlette.datastructures import MutableHeaders
from starlette.responses import RedirectResponse, Response

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

STATIC_DIR = Path(__file__).parent / "static"


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
    """
    from studyloop.web._schema_init import prepare_schema
    from studyloop.web.routes.session import _grace

    prepare_schema()
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


def create_app(
    study_dirs: list[str] | None = None,
    username: str = "study",
    password: str = "",
    dev_mode: bool = False,
    dev_engine: str | None = None,
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
    """
    from studyloop.web.dev_engines import resolve_dev_engine

    app = FastAPI(
        title="StudyLoop",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=_lifespan,
    )

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
        notes,
        now,
        parking,
        plans,
        session,
        tts,
    )

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
    app.include_router(tts.router, prefix="/api")

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
    app.mount("/", StaticFiles(directory=str(STATIC_DIR)), name="static")

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
    return SecurityHeadersMiddleware(app)  # type: ignore[return-value]
