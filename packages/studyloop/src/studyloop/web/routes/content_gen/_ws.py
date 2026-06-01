"""WebSocket progress stream for content generation jobs."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect

from studyloop.web.routes.content_gen._jobs import _JOB_QUEUES, _drop_queue
from studyloop.web.routes.content_gen._router import router
from studyloop.web.ws_origin import origin_allowed

logger = logging.getLogger(__name__)

# RFC 6455 close codes. 1008 is "policy violation" (origin mismatch);
# 4404 is in the application range (4000-4999) and reads as "job not
# found" -- consistent with the HTTP 404 idiom the WS would otherwise
# have to encode in a transport_error frame.
_WS_CLOSE_POLICY = 1008
_WS_CLOSE_NOT_FOUND = 4404


_TERMINAL_FRAMES = frozenset({"all_done", "transport_error"})


@router.websocket("/content/generate/ws")
async def content_generate_socket(websocket: WebSocket) -> None:
    """Stream generation progress for a given ``job_id``.

    Pre-accept guards (origin + queue lookup) follow the same shape as
    ``/session/ws`` so the two WS endpoints feel consistent. After
    ``accept()``, the handler is a pure consumer: pull from the queue,
    forward to the client, exit on a terminal frame.

    Close codes:

    - ``1008`` — disallowed origin.
    - ``4404`` — no queue for the requested ``job_id``.
    - ``1000`` — normal close after the orchestrator's ``all_done`` /
      ``transport_error`` frame.
    """
    origin = websocket.headers.get("origin", "")
    host = websocket.headers.get("host", "")
    if not origin_allowed(origin, host=host):
        logger.warning("WS /content/generate/ws rejected: origin=%r host=%r", origin, host)
        await websocket.close(code=_WS_CLOSE_POLICY)
        return

    job_id = websocket.query_params.get("job_id", "")
    queue = _JOB_QUEUES.get(job_id)
    if queue is None:
        await websocket.close(code=_WS_CLOSE_NOT_FOUND)
        return

    await websocket.accept()
    try:
        while True:
            frame = await queue.get()
            try:
                await websocket.send_json(frame)
            except WebSocketDisconnect:
                # Client gone -- keep draining the queue silently so
                # the orchestrator's push side never blocks. The job
                # itself is unaffected; its writes still hit disk.
                logger.debug("WS client disconnected job_id=%s; draining queue", job_id)
                await _drain_queue_quietly(queue)
                return
            if frame.get("type") in _TERMINAL_FRAMES:
                return
    finally:
        # Drop the queue once the consumer exits. The orchestrator's
        # background task has already released the singleton; the
        # queue is no longer reachable from a future WS client.
        _drop_queue(job_id)


async def _drain_queue_quietly(queue: asyncio.Queue[dict[str, Any]]) -> None:
    """Pull and discard remaining items so the producer never blocks.

    Stops when a terminal frame is seen, capping wait time even if the
    job runs long.
    """
    while True:
        try:
            frame = await asyncio.wait_for(queue.get(), timeout=30.0)
        except TimeoutError:
            return
        if frame.get("type") in _TERMINAL_FRAMES:
            return
