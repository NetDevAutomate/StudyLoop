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

from studyloop.session_runtime import AgentSessionManager

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Run the session-slot reaper for the whole life of the app.

    The reaper is the backstop for every way the single-session slot can be
    pinned that the WebSocket grace timer cannot see — a session whose socket
    never attached, or one ended/cleaned from another process. Without it those
    slots stay occupied until the server restarts and every ``/session/start``
    409s. Started on app startup and torn down on shutdown so a stop cannot
    leave an orphaned agent child owned by a timer that will never fire.
    """
    from studyloop.web.routes.session import _grace

    _grace.start_reaper()
    try:
        yield
    finally:
        await _grace.shutdown()


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add security headers to all responses."""

    async def dispatch(self, request: Request, call_next) -> Response:  # type: ignore[override]
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        # SAMEORIGIN (not DENY) so our same-origin /terminal/ iframe can embed ttyd
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        return response


def create_app(
    study_dirs: list[str] | None = None,
    ttyd_port: int = 7681,
    username: str = "study",
    password_verifier: str = "",
    dev_mode: bool = False,
    dev_renderer: str | None = None,
    dev_engine: str | None = None,
) -> FastAPI:
    """Create and configure the FastAPI application.

    Args:
        study_dirs: List of directory paths containing flashcard/quiz content.
        ttyd_port: Port where the local ttyd process is listening.
        username: Username for HTTP Basic Auth (LAN protection). Default: "study".
        password_verifier: Optional one-way verifier for HTTP Basic Auth.
                           If empty, no authentication is applied.
        dev_mode: When True, the UI loads an alternative renderer instead of
                  xterm.js. Default (False) preserves existing behaviour exactly.
        dev_renderer: Deprecated legacy alias for ``dev_engine``. When set
                      (non-None), it takes precedence and drives the original
                      inline ghostty-web injection below. New callers
                      should use ``dev_engine`` instead, which is validated
                      against and injected via ``studyloop.web.dev_engines``.
        dev_engine: Which registered dev engine (``studyloop.web.dev_engines
                    .DEV_ENGINES``) to use in dev mode. Defaults to
                    ``DEFAULT_DEV_ENGINE`` ("ghostty") when dev_mode=True and
                    neither this nor ``dev_renderer`` is set. Ignored (and left
                    unvalidated) when dev_mode=False. Raises ValueError at
                    startup for an unknown engine name.
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
    app.state.dev_renderer = dev_renderer
    # The registry-backed engine choice (studyloop.web.dev_engines), distinct
    # from the legacy `dev_renderer` inline-injection path above. None unless
    # dev_mode is on — `--dev-engine` is inert without `--dev`, matching the
    # `--dev-renderer` behaviour it complements. Resolved (and validated) up
    # front so a bad --dev-engine fails at startup, not on first page load.
    app.state.dev_engine = resolve_dev_engine(dev_engine) if dev_mode else None
    # Routes need to know whether outer authentication exists, but must not be
    # able to recover its reusable credential from general application state.
    # Only the active BasicAuthMiddleware retains the verifier itself.
    app.state.lan_username = username
    app.state.lan_auth_configured = bool(password_verifier)
    app.state.agent_session_manager = AgentSessionManager()
    app.state.explorer_tree_cache = None
    app.state.explorer_tree_fingerprint = None
    app.state.session_options_targets_cache = None
    app.state.session_options_targets_fingerprint = None
    from studyloop.web.learner_auth import initialise_browser_learner_sessions

    initialise_browser_learner_sessions(app)

    # Optional password protection (LAN mode)
    if password_verifier:
        from studyloop.web.auth import configured_basic_auth_middleware

        app.add_middleware(configured_basic_auth_middleware(username, password_verifier))

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

    # Terminal proxy — MUST be registered before the static files catch-all
    try:
        from studyloop.web.routes import terminal_proxy

        app.include_router(terminal_proxy.router)
    except ImportError:
        pass  # httpx/websockets not installed — proxy unavailable

    # Serve index.html at root (no-cache to prevent stale SW/browser cache).
    # In dev_mode=True the HTML is read and renderer-specific tags are injected
    # so the client-side JS swaps Terminal at runtime.
    @app.get("/", response_model=None)
    async def index(request: Request) -> Response:
        from studyloop.web.learner_auth import mint_browser_learner_session

        def browser_response(response: Response) -> Response:
            mint_browser_learner_session(request, response)
            return response

        no_cache = {"Cache-Control": "no-cache, no-store, must-revalidate"}
        if not dev_mode:
            return browser_response(FileResponse(STATIC_DIR / "index.html", headers=no_cache))
        html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
        # `dev_renderer` is the deprecated legacy path: only taken when a
        # caller explicitly passes it, preserving its exact historical
        # markup (content="ghostty-web", the *.umd.js/bootstrap filenames).
        # Every other dev_mode=True call — including the new default — goes
        # through the dev_engines registry below.
        if dev_renderer is not None:
            renderer = dev_renderer
        else:
            from studyloop.web.dev_engines import inject_dev_engine

            return browser_response(
                HTMLResponse(
                    content=inject_dev_engine(html, app.state.dev_engine), headers=no_cache
                )
            )
        if renderer == "ghostty":
            dev_injection = '\n  <meta name="studyloop-dev-mode" content="ghostty-web">'
            html = html.replace("<head>", "<head>" + dev_injection, 1)
            # ghostty-web UMD + bootstrap: defer so they execute after the
            # xterm.js defer scripts; the bootstrap patches window.Terminal last.
            # No CSS needed (canvas renderer).
            ghostty_scripts = (
                "\n  <!-- ghostty-web dev-mode: defer so it runs after the xterm"
                " defer scripts; the bootstrap patches window.Terminal last -->"
                '\n  <script defer src="/vendor/js/ghostty-web-0.4.0.umd.js"></script>'
                '\n  <script defer src="/vendor/js/ghostty-web-bootstrap-0.4.0.js"></script>'
            )
            html = html.replace("</head>", ghostty_scripts + "\n</head>", 1)
        return browser_response(HTMLResponse(content=html, headers=no_cache))

    # Redirect /session to hash-routed study-session tab
    @app.get("/session")
    async def session_page() -> RedirectResponse:
        return RedirectResponse(url="/#study-session")

    # Mount static files LAST (catch-all)
    app.mount("/", StaticFiles(directory=str(STATIC_DIR)), name="static")

    return app
