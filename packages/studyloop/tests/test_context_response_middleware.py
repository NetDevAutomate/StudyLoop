"""No partial ASGI messages escape an over-budget finite API response."""

import asyncio

from studyloop.web.context_response import ContextResponseMiddleware


def test_http_buffer_limit_discards_early_headers_and_body():
    async def application(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"PRIVATE_PREFIX", "more_body": True})
        await send({"type": "http.response.body", "body": b"x" * (8 * 1024 * 1024)})

    async def run():
        messages = []

        async def receive():
            return {"type": "http.request", "body": b""}

        async def send(message):
            messages.append(message)

        await ContextResponseMiddleware(application)(
            {"type": "http", "method": "GET", "path": "/api/test"}, receive, send
        )
        assert [m["status"] for m in messages if m["type"] == "http.response.start"] == [413]
        assert b"PRIVATE_PREFIX" not in b"".join(m.get("body", b"") for m in messages)

    asyncio.run(run())
