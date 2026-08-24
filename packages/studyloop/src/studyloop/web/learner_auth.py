"""Server-minted browser learner sessions for authority-bearing plan writes."""

from __future__ import annotations

import hmac
import secrets
import time
from dataclasses import dataclass
from ipaddress import ip_address
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from fastapi import HTTPException, Request

from studyloop.planning import ActorContext

if TYPE_CHECKING:
    from fastapi import WebSocket
    from starlette.responses import Response

SESSION_COOKIE = "studyloop_learner_session"
CSRF_COOKIE = "studyloop_csrf"
CSRF_HEADER = "X-CSRF-Token"
SESSION_TTL_SECONDS = 8 * 60 * 60
WEB_AUTH_REQUIRED = {
    "code": "web_auth_required",
    "message": "Configure and authenticate with the StudyLoop web password for learner writes",
}


@dataclass(frozen=True)
class BrowserLearnerSession:
    actor_id: str
    csrf_token: str
    expires_at: float


def initialise_browser_learner_sessions(app: object) -> None:
    """Create an application-local session registry; sessions die on restart."""
    app.state.browser_learner_sessions = {}  # type: ignore[attr-defined]


def mint_browser_learner_session(request: Request, response: Response) -> None:
    """Mint authority for loopback navigation or authenticated LAN navigation."""
    hostname = request.url.hostname or ""
    try:
        loopback = ip_address(hostname).is_loopback
    except ValueError:
        loopback = hostname.casefold() == "localhost"
    authenticated_identity = getattr(request.state, "basic_auth_identity", "")
    if not loopback and (
        not getattr(request.app.state, "lan_auth_configured", False) or not authenticated_identity
    ):
        return
    if request.headers.get("sec-fetch-mode", "").casefold() != "navigate":
        return
    if request.headers.get("sec-fetch-site", "").casefold() not in {"same-origin", "none"}:
        return
    sessions: dict[str, BrowserLearnerSession] = request.app.state.browser_learner_sessions
    now = time.monotonic()
    for expired_id in [key for key, value in sessions.items() if value.expires_at <= now]:
        sessions.pop(expired_id, None)
    prior_id = request.cookies.get(SESSION_COOKIE, "")
    if prior_id:
        sessions.pop(prior_id, None)
    if len(sessions) >= 256:
        sessions.pop(min(sessions, key=lambda key: sessions[key].expires_at), None)
    session_id = secrets.token_urlsafe(32)
    csrf_token = secrets.token_urlsafe(32)
    actor_id = "loopback:local" if loopback else f"basic:{authenticated_identity}"
    sessions[session_id] = BrowserLearnerSession(
        actor_id=actor_id,
        csrf_token=csrf_token,
        expires_at=now + SESSION_TTL_SECONDS,
    )
    secure = request.url.scheme == "https"
    response.set_cookie(
        SESSION_COOKIE,
        session_id,
        httponly=True,
        secure=secure,
        samesite="strict",
        path="/",
        max_age=SESSION_TTL_SECONDS,
    )
    response.set_cookie(
        CSRF_COOKIE,
        csrf_token,
        httponly=False,
        secure=secure,
        samesite="strict",
        path="/",
        max_age=SESSION_TTL_SECONDS,
    )


def require_browser_learner(request: Request) -> ActorContext:
    """Authenticate a same-origin, CSRF-bound server-side browser session."""
    session_id = request.cookies.get(SESSION_COOKIE, "")
    sessions: dict[str, BrowserLearnerSession] = request.app.state.browser_learner_sessions
    session = sessions.get(session_id)
    if session is None or session.expires_at <= time.monotonic():
        if session_id:
            sessions.pop(session_id, None)
        raise HTTPException(status_code=403, detail=WEB_AUTH_REQUIRED)
    origin = request.headers.get("origin", "")
    expected_origin = str(request.base_url).rstrip("/")
    if not origin or not hmac.compare_digest(origin, expected_origin):
        raise HTTPException(status_code=403, detail="same-origin browser learner request required")
    if request.headers.get("sec-fetch-site", "").casefold() != "same-origin":
        raise HTTPException(status_code=403, detail="same-origin browser learner request required")
    csrf_cookie = request.cookies.get(CSRF_COOKIE, "")
    csrf_header = request.headers.get(CSRF_HEADER, "")
    if session.actor_id.startswith("basic:") and not getattr(
        request.state, "basic_auth_identity", ""
    ):
        raise HTTPException(status_code=403, detail=WEB_AUTH_REQUIRED)
    if not csrf_cookie or not csrf_header:
        raise HTTPException(status_code=403, detail="browser learner CSRF token required")
    if not hmac.compare_digest(csrf_cookie, session.csrf_token) or not hmac.compare_digest(
        csrf_header, session.csrf_token
    ):
        raise HTTPException(status_code=403, detail="browser learner CSRF token is invalid")
    return ActorContext("learner", session.actor_id, "web-browser")


def browser_csrf_token(request: Request) -> str:
    """Return the current server-bound token after learner authentication."""
    session_id = request.cookies.get(SESSION_COOKIE, "")
    sessions: dict[str, BrowserLearnerSession] = request.app.state.browser_learner_sessions
    session = sessions.get(session_id)
    return session.csrf_token if session is not None else ""


def websocket_origin_matches(origin: str, *, websocket_scheme: str, host: str) -> bool:
    """Require the exact browser origin represented by this WebSocket request."""
    parsed = urlsplit(origin.strip())
    expected_scheme = {"ws": "http", "wss": "https"}.get(websocket_scheme.casefold())
    return bool(
        expected_scheme
        and parsed.scheme.casefold() == expected_scheme
        and parsed.netloc
        and hmac.compare_digest(parsed.netloc.casefold(), host.strip().casefold())
        and parsed.path in {"", "/"}
        and not parsed.query
        and not parsed.fragment
    )


def websocket_browser_learner_valid(websocket: WebSocket) -> bool:
    """Validate exact origin plus the server-minted session and double-submit token."""
    if not websocket_origin_matches(
        websocket.headers.get("origin", ""),
        websocket_scheme=websocket.url.scheme,
        host=websocket.headers.get("host", ""),
    ):
        return False
    session_id = websocket.cookies.get(SESSION_COOKIE, "")
    csrf_cookie = websocket.cookies.get(CSRF_COOKIE, "")
    csrf_token = websocket.query_params.get("csrf_token", "")
    sessions: dict[str, BrowserLearnerSession] = websocket.app.state.browser_learner_sessions
    session = sessions.get(session_id)
    if session is None or session.expires_at <= time.monotonic():
        if session_id:
            sessions.pop(session_id, None)
        return False
    if session.actor_id.startswith("basic:") and not getattr(
        websocket.state, "basic_auth_identity", ""
    ):
        return False
    return bool(
        csrf_cookie
        and csrf_token
        and hmac.compare_digest(csrf_cookie, session.csrf_token)
        and hmac.compare_digest(csrf_token, session.csrf_token)
    )


__all__ = [
    "CSRF_COOKIE",
    "CSRF_HEADER",
    "SESSION_COOKIE",
    "browser_csrf_token",
    "initialise_browser_learner_sessions",
    "mint_browser_learner_session",
    "require_browser_learner",
    "websocket_browser_learner_valid",
    "websocket_origin_matches",
]
