"""ACP wire-format normaliser.

Translates between the on-the-wire shapes used by Agent Client Protocol
Kiro CLI and the ``AgentSessionTransport`` event vocabulary.

The captured Kiro protocol uses the slash-prefixed
method names (``session/new``, ``session/prompt``, ``session/cancel``,
etc.). The plan pre-loaded a ``METHOD_ALIASES`` dict for translating
Earlier experimental clients translated ``session/new`` to ``newSession``;
that translation is not required by the admitted Kiro harness.

This module is deliberately thin. It exists so:

1. When ACPTransport dispatches the outbound method list below, we
   have one import site to audit if a future CLI drifts again. The
   ``OUTBOUND_METHOD_ALIASES`` dict is an extension point — empty
   today.
2. Inbound ``session/update`` notifications carry an
   ``update.sessionUpdate`` discriminator (``agent_message_chunk``,
   ``tool_call``, ``turn_end``, etc.) that maps one-to-one onto our
   ``AgentMessage.kind``. ``normalise_session_update`` does that
   translation and drops UI-chrome updates (``available_commands_update``)
   by default so we don't flood the WebSocket.

Phase 2 — not yet wired into ``ACPTransport`` (skeleton only).
"""

from __future__ import annotations

from typing import Any

# Outbound request/method aliasing. Empty today because Kiro accepts the
# slash-prefixed spec names. If a future admitted
# CLI drifts, add a mapping here — e.g.
# ``{"session/new": "newSession"}`` would rewrite our outbound call when
# targeting that CLI.
OUTBOUND_METHOD_ALIASES: dict[str, dict[str, str]] = {
    # agent_slug -> {canonical_method: alias_for_this_agent}
}


# Inbound discriminator map: ACP ``update.sessionUpdate`` → our
# ``AgentMessage.kind``. One-to-one today. Unmapped values pass
# through verbatim so forward-compat CLI changes don't break us
# silently — they just surface with the raw ACP name.
UPDATE_KIND_MAP: dict[str, str] = {
    "agent_message_chunk": "agent_chunk",
    "agent_thought_chunk": "agent_thought",
    "tool_call": "tool_call",
    "tool_call_update": "tool_call_update",
    "turn_end": "turn_end",
    "plan": "plan",
    "plan_update": "plan_update",
    # NOTE: request_permission is NOT here. It arrives as a JSON-RPC *request*
    # (session/request_permission with an id), not as a session/update
    # notification. _dispatch_frame handles it via the inbound-request branch
    # and embeds _request_id in the payload. See acp.py and U6.5 notes.
    "available_commands_update": "available_commands",
}


# Updates we deliberately drop by default. These are UI chrome that
# don't represent learner-visible progress; surfacing them would just
# noise up the agent terminal / agent-message log.
DROPPED_UPDATE_KINDS: frozenset[str] = frozenset(
    {
        "available_commands_update",
    }
)


def normalise_session_update(
    params: dict[str, Any], *, drop_chrome: bool = True
) -> dict[str, Any] | None:
    """Translate one ``session/update`` notification into an
    ``AgentMessage`` payload shape.

    Returns ``None`` when the update is chrome we drop by default
    (currently only ``available_commands_update``). Pass
    ``drop_chrome=False`` to surface every update verbatim.

    Returned dict shape: ``{"kind": <str>, "payload": <dict>}`` —
    ready to become ``AgentMessage(**normalised)``.
    """
    update = params.get("update")
    if not isinstance(update, dict):
        return None
    raw_kind = update.get("sessionUpdate")
    if not isinstance(raw_kind, str):
        return None
    if drop_chrome and raw_kind in DROPPED_UPDATE_KINDS:
        return None
    normalised_kind = UPDATE_KIND_MAP.get(raw_kind, raw_kind)
    # Strip the discriminator from the payload so consumers don't see
    # two copies of the same value.
    payload = {k: v for k, v in update.items() if k != "sessionUpdate"}
    session_id = params.get("sessionId")
    if session_id is not None and "sessionId" not in payload:
        payload["sessionId"] = session_id
    return {"kind": normalised_kind, "payload": payload}


def is_kiro_extension(method: str) -> bool:
    """Return True for non-spec Kiro-only notifications (``_kiro.dev/*``).

    Kiro 0.11.131 emits these freely alongside standard ACP traffic.
    Callers can drop them, or wrap them as
    ``AgentMessage(kind="kiro_extension", payload=params)``.
    """
    return method.startswith("_kiro.dev/")


def rewrite_outbound_method(method: str, agent_slug: str) -> str:
    """Apply agent-specific outbound aliasing if any is registered.

    Pure function. Returns ``method`` unchanged when no alias exists,
    which is the current Kiro behaviour.
    """
    aliases = OUTBOUND_METHOD_ALIASES.get(agent_slug, {})
    return aliases.get(method, method)
