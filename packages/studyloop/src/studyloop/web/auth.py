"""HTTP Basic Auth middleware for LAN-exposed web server.

When credentials are configured, all requests require HTTP Basic Auth.
The username is timing-safe compared and the password is checked against a
salted one-way verifier.
This protects the study dashboard and terminal from unauthorised LAN access.
"""

from __future__ import annotations

import base64
import hmac
from typing import TYPE_CHECKING

from starlette.datastructures import Headers
from starlette.responses import Response

if TYPE_CHECKING:
    from starlette.types import ASGIApp, Receive, Scope, Send


class BasicAuthMiddleware:
    """Enforce HTTP Basic Auth on HTTP and WebSocket scopes.

    Usage::

        app.add_middleware(configured_basic_auth_middleware("study", verifier))

    The public app factory installs a bound subclass so Starlette's generic
    middleware specification contains no repr-visible verifier kwargs.
    """

    def __init__(self, app: ASGIApp, *, username: str, password_verifier: str) -> None:
        self.app = app
        self._username = username
        self._password_verifier = password_verifier

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        scope_type = scope["type"]
        if scope_type not in {"http", "websocket"}:
            await self.app(scope, receive, send)
            return

        auth_header = Headers(scope=scope).get("authorization", "")
        if self._check_auth(auth_header):
            scope.setdefault("state", {})["basic_auth_identity"] = self._username
            await self.app(scope, receive, send)
            return

        if scope_type == "websocket":
            await send({"type": "websocket.close", "code": 1008})
            return

        response = Response(
            content="Authentication required",
            status_code=401,
            headers={"WWW-Authenticate": 'Basic realm="studyloop"'},
            media_type="text/plain",
        )
        await response(scope, receive, send)

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
        from studyloop.learner_credentials import verify_password

        pass_ok = verify_password(password, self._password_verifier)
        return user_ok and pass_ok


def configured_basic_auth_middleware(username: str, password_verifier: str) -> type:
    """Bind auth material privately, outside Starlette's repr-visible kwargs."""
    from studyloop.learner_credentials import is_password_verifier

    if not is_password_verifier(password_verifier):
        raise ValueError("A valid LAN password verifier is required")

    class _ConfiguredBasicAuthMiddleware(BasicAuthMiddleware):
        def __init__(self, app: ASGIApp) -> None:
            super().__init__(
                app,
                username=username,
                password_verifier=password_verifier,
            )

    _ConfiguredBasicAuthMiddleware.__name__ = "ConfiguredBasicAuthMiddleware"
    _ConfiguredBasicAuthMiddleware.__qualname__ = "ConfiguredBasicAuthMiddleware"
    return _ConfiguredBasicAuthMiddleware
