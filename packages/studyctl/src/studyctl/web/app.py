"""FastAPI application factory for the study PWA.

Replaces the stdlib http.server with FastAPI + uvicorn.
Serves JSON API endpoints and static PWA files.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

if TYPE_CHECKING:
    from starlette.responses import Response

STATIC_DIR = Path(__file__).parent / "static"


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
    password: str = "",
) -> FastAPI:
    """Create and configure the FastAPI application.

    Args:
        study_dirs: List of directory paths containing flashcard/quiz content.
        ttyd_port: Port where the local ttyd process is listening.
        username: Username for HTTP Basic Auth (LAN protection). Default: "study".
        password: Optional password for HTTP Basic Auth (LAN protection).
                  If empty, no authentication is applied.
    """
    app = FastAPI(
        title="Socratic Study Mentor",
        docs_url=None,
        redoc_url=None,
    )

    # Store config on app state for route access
    app.state.study_dirs = study_dirs or []
    app.state.ttyd_port = ttyd_port

    # Optional password protection (LAN mode)
    if password:
        from studyctl.web.auth import BasicAuthMiddleware

        app.add_middleware(BasicAuthMiddleware, username=username, password=password)

    # Security headers
    app.add_middleware(SecurityHeadersMiddleware)

    # Register API routes
    from studyctl.web.routes import artefacts, cards, courses, history, session

    app.include_router(courses.router, prefix="/api")
    app.include_router(cards.router, prefix="/api")
    app.include_router(history.router, prefix="/api")
    app.include_router(session.router, prefix="/api")
    app.include_router(artefacts.router)

    # Terminal proxy — MUST be registered before the static files catch-all
    try:
        from studyctl.web.routes import terminal_proxy

        app.include_router(terminal_proxy.router)
    except ImportError:
        pass  # httpx/websockets not installed — proxy unavailable

    # Serve index.html at root
    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    # Serve session dashboard (unified page with hash routing)
    @app.get("/session")
    async def session_page() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    # Mount static files LAST (catch-all)
    app.mount("/", StaticFiles(directory=str(STATIC_DIR)), name="static")

    return app
