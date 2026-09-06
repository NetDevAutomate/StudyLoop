"""Validate finite API read responses before sending their headers or bodies."""

from fastapi.responses import JSONResponse

from agent_session_tools.context.response import read_boundary
from agent_session_tools.context.scope import ScopeError


class ContextResponseMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        # The live IPC stream has per-event semantics and a separate ownership
        # inventory. Do not buffer an unending stream as one finite response.
        if (
            scope["type"] != "http"
            or scope["method"] not in ("GET", "HEAD")
            or not scope["path"].startswith("/api/")
            or scope["path"] == "/api/session/stream"
        ):
            await self.app(scope, receive, send)
            return
        messages = []
        byte_count = 0

        async def capture(message):
            nonlocal byte_count
            byte_count += len(message.get("body", b""))
            if byte_count > 8 * 1024 * 1024 or len(messages) >= 1024:
                raise ResponseTooLargeError
            messages.append(message)

        try:
            with read_boundary():
                await self.app(scope, receive, capture)
        except ScopeError as exc:
            await JSONResponse(
                status_code=409,
                content={"code": "context_scope_unavailable", "detail": str(exc)},
            )(scope, receive, send)
            return
        except ResponseTooLargeError:
            await JSONResponse(
                status_code=413,
                content={
                    "code": "context_response_too_large",
                    "detail": "Use a narrower query or smaller limit for this response.",
                },
            )(scope, receive, send)
            return
        for message in messages:
            await send(message)


class ResponseTooLargeError(Exception):
    """Bound the buffer before any response is released."""
