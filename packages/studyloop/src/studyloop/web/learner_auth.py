"""Server-minted browser learner sessions for authority-bearing plan writes."""

from __future__ import annotations

import hmac
import secrets
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from fastapi import HTTPException, Request

from studyloop.planning import ActorContext

if TYPE_CHECKING:
    from starlette.responses import Response

SESSION_COOKIE = "studyloop_learner_session"
CSRF_COOKIE = "studyloop_csrf"
CSRF_HEADER = "X-CSRF-Token"
SESSION_TTL_SECONDS = 8 * 60 * 60


@dataclass(frozen=True)
class BrowserLearnerSession:
    actor_id: str
    csrf_token: str
    expires_at: float


def initialise_browser_learner_sessions(app: object) -> None:
    """Create an application-local session registry; sessions die on restart."""
    app.state.browser_learner_sessions = {}  # type: ignore[attr-defined]


def mint_browser_learner_session(request: Request, response: Response) -> None:
    """Mint authority only during a genuine same-site top-level navigation."""
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
    username = str(getattr(request.app.state, "lan_username", "local-learner"))
    password_enabled = bool(getattr(request.app.state, "lan_password", ""))
    actor_id = f"basic:{username}" if password_enabled else "local-browser-learner"
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
    origin = request.headers.get("origin", "")
    expected_origin = str(request.base_url).rstrip("/")
    if not origin or not hmac.compare_digest(origin, expected_origin):
        raise HTTPException(status_code=403, detail="same-origin browser learner request required")
    if request.headers.get("sec-fetch-site", "").casefold() != "same-origin":
        raise HTTPException(status_code=403, detail="same-origin browser learner request required")
    session_id = request.cookies.get(SESSION_COOKIE, "")
    csrf_cookie = request.cookies.get(CSRF_COOKIE, "")
    csrf_header = request.headers.get(CSRF_HEADER, "")
    sessions: dict[str, BrowserLearnerSession] = request.app.state.browser_learner_sessions
    session = sessions.get(session_id)
    if session is None or session.expires_at <= time.monotonic():
        if session_id:
            sessions.pop(session_id, None)
        raise HTTPException(status_code=403, detail="valid browser learner session required")
    if not csrf_cookie or not csrf_header:
        raise HTTPException(status_code=403, detail="browser learner CSRF token required")
    if not hmac.compare_digest(csrf_cookie, session.csrf_token) or not hmac.compare_digest(
        csrf_header, session.csrf_token
    ):
        raise HTTPException(status_code=403, detail="browser learner CSRF token is invalid")
    return ActorContext("learner", session.actor_id, "web-browser")


__all__ = [
    "CSRF_COOKIE",
    "CSRF_HEADER",
    "SESSION_COOKIE",
    "initialise_browser_learner_sessions",
    "mint_browser_learner_session",
    "require_browser_learner",
]
