"""HTTP Basic Auth middleware for LAN-exposed web server.

When a password is configured, all requests require HTTP Basic Auth.
The username field is ignored — only the password is checked.
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
    """Enforce HTTP Basic Auth on all routes when a password is configured.

    Usage::

        app.add_middleware(BasicAuthMiddleware, password="secret")  # pragma: allowlist secret

    If password is empty, the middleware is a no-op (pass-through).
    """

    def __init__(self, app, *, password: str) -> None:
        super().__init__(app)
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
        """Check that the Authorization header contains the correct password.

        Uses hmac.compare_digest to prevent timing attacks.
        The username is ignored — only the password matters.
        """
        if not authorization.startswith("Basic "):
            return False

        try:
            decoded = base64.b64decode(authorization[6:]).decode("utf-8")
        except Exception:
            return False

        # decoded is "username:password" — split only on first colon
        parts = decoded.split(":", 1)
        if len(parts) != 2:
            return False

        _, password = parts
        # Constant-time comparison to prevent timing attacks
        return hmac.compare_digest(password, self._password)
