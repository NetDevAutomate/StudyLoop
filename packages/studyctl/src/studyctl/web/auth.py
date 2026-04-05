"""HTTP Basic Auth middleware for LAN-exposed web server.

When credentials are configured, all requests require HTTP Basic Auth.
Both username and password are checked (timing-safe comparison).
This protects the study dashboard and terminal from unauthorised LAN access.
"""

from __future__ import annotations

import base64
import hmac
from typing import TYPE_CHECKING

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

if TYPE_CHECKING:
    from fastapi import Request


class BasicAuthMiddleware(BaseHTTPMiddleware):
    """Enforce HTTP Basic Auth on all routes when credentials are configured.

    Usage::

        app.add_middleware(
            BasicAuthMiddleware,
            username="study",
            password="secret",  # pragma: allowlist secret
        )

    If password is empty, the middleware is a no-op (pass-through).
    """

    def __init__(self, app, *, username: str = "study", password: str) -> None:
        super().__init__(app)
        self._username = username
        self._password = password

    async def dispatch(self, request: Request, call_next) -> Response:  # type: ignore[override]
        if not self._password:
            return await call_next(request)

        auth_header = request.headers.get("Authorization", "")
        if self._check_auth(auth_header):
            return await call_next(request)

        return Response(
            content="Authentication required",
            status_code=401,
            headers={"WWW-Authenticate": 'Basic realm="studyctl"'},
            media_type="text/plain",
        )

    def _check_auth(self, authorization: str) -> bool:
        """Check that the Authorization header contains valid credentials.

        Uses hmac.compare_digest to prevent timing attacks on both fields.
        """
        if not authorization.startswith("Basic "):
            return False

        try:
            decoded = base64.b64decode(authorization[6:]).decode("utf-8")
        except Exception:
            return False

        parts = decoded.split(":", 1)
        if len(parts) != 2:
            return False

        username, password = parts
        user_ok = hmac.compare_digest(username, self._username)
        pass_ok = hmac.compare_digest(password, self._password)
        return user_ok and pass_ok
