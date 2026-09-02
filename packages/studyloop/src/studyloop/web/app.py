"""FastAPI application factory for the study PWA.

Replaces the stdlib http.server with FastAPI + uvicorn.
Serves JSON API endpoints and static PWA files.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
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
# - connect-src data:: `--dev --dev-engine ghostty` (opt-in developer
#   renderer, vendor/dev/js/ghostty-web-0.4.0.js) bootstraps its WASM VT100
#   parser via `fetch("data:application/wasm;base64,...")` rather than
#   `WebAssembly.instantiateStreaming` against a same-origin URL. Without
#   this, `default-src 'self'` (connect-src's fallback) blocks that fetch
#   and every `--dev` session fails to render with a CSP-caused 404. Scoped
#   to `connect-src` only — script-src stays `'self' 'unsafe-eval'`, no
#   `data:` script source.
_CSP = (
    "default-src 'self'; script-src 'self' 'unsafe-eval'; "
    "style-src 'self' 'unsafe-inline'; connect-src 'self' data:"
)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add security headers to all responses."""

    async def dispatch(self, request: Request, call_next) -> Response:  # type: ignore[override]
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        # DENY: no iframe surface exists anywhere in static/ (the ttyd
        # iframe fallback this used to justify SAMEORIGIN for was retired —
        # see ADR-0005 and the ttyd retirement, stage 4).
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = _CSP
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
        # X-XSS-Protection is deliberately NOT set: deprecated, a no-op (or
        # an XSS vector via its filter) in every modern browser, superseded
        # by the CSP above.
        return response


def create_app(
    study_dirs: list[str] | None = None,
    ttyd_port: int = 7681,
    username: str = "study",
    password: str = "",
    dev_mode: bool = False,
    dev_engine: str | None = None,
) -> FastAPI:
    """Create and configure the FastAPI application.

    Args:
        study_dirs: List of directory paths containing flashcard/quiz content.
        ttyd_port: Port where the local ttyd process is listening.
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
        lifespan=_lifespan,
    )

    # Store config on app state for route access
    app.state.study_dirs = study_dirs or []
    app.state.ttyd_port = ttyd_port
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

    # Security headers
    app.add_middleware(SecurityHeadersMiddleware)

    # Register API routes
    from studyloop.web.routes import (
        artefacts,
        backlog,
        body_double,
        cards,
        content_gen,
        courses,
        exercises,
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

    return app
