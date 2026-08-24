"""Durable reconnectable WebSocket stream for planning outbox events."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from studyloop.planning.conversation_contracts import ConversationConflictError
from studyloop.web.routes.planning import safe_event
from studyloop.web.ws_origin import origin_allowed

router = APIRouter()


@router.websocket("/planning/conversations/{conversation_id}/events")
async def planning_events(websocket: WebSocket, conversation_id: str) -> None:
    if not origin_allowed(
        websocket.headers.get("origin", ""),
        host=websocket.headers.get("host", ""),
    ):
        await websocket.close(code=1008)
        return
    services = websocket.app.state.planning_services
    try:
        services.store.get_conversation(conversation_id)
    except ConversationConflictError:
        await websocket.close(code=4404)
        return
    try:
        cursor = max(0, int(websocket.query_params.get("after_seq", "0")))
    except ValueError:
        await websocket.close(code=1008)
        return
    await websocket.accept()
    try:
        while True:
            events = services.store.replay_outbox(conversation_id, cursor)
            for event in events:
                await websocket.send_json(safe_event(event))
                cursor = event.sequence
            await asyncio.sleep(0.1)
    except WebSocketDisconnect:
        return


__all__ = ["router"]
