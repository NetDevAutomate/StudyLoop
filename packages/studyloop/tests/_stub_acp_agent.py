"""Scripted NDJSON JSON-RPC agent for unit-testing ``ACPTransport``.

Reads JSON-RPC frames from stdin (one per line) and emits canned
responses + pre-scripted notifications on stdout, driven entirely by
environment variables so the harness stays serialisable.

Each ``ACPTransport`` test launches this as a subprocess via
``asyncio.create_subprocess_exec`` and scripts the agent's behaviour
through env vars:

- ``STUB_ACP_PRE_INIT_NOTIFS`` — JSON array of notification frames to
  emit *before* reading the first client request. Models Kiro's
  pre-session ``_kiro.dev/*`` chatter.
- ``STUB_ACP_INIT_RESULT`` — JSON object for the initialize response
  ``result`` field. Defaults to a minimal ``agentInfo`` + capabilities.
- ``STUB_ACP_NEW_SESSION_RESULT`` — JSON object for ``session/new``
  response. Defaults to ``{"sessionId": "stub-session-1"}``.
- ``STUB_ACP_POST_NEW_SESSION_UPDATES`` — JSON array of ``session/update``
  notifications to emit immediately after answering ``session/new``.
- ``STUB_ACP_PROMPT_UPDATES`` — JSON array of notifications to emit
  when a ``session/prompt`` arrives, interleaved with the prompt
  response.  Every prompt turn emits the same sequence (back-compat
  fallback).  If ``STUB_ACP_PROMPT_UPDATES_SEQ`` is also set, the SEQ
  variable takes priority.
- ``STUB_ACP_PROMPT_UPDATES_SEQ`` — JSON **array-of-arrays**.  Each
  inner array is the notification sequence emitted for the *nth*
  ``session/prompt`` (0-indexed).  When prompts exceed the array
  length the **last entry repeats**.  Takes priority over
  ``STUB_ACP_PROMPT_UPDATES`` when both are set.
- ``STUB_ACP_PROMPT_STOP_REASON`` — string placed in the ``session/prompt``
  result. Default ``"end_turn"``.
- ``STUB_ACP_PROMPT_ERROR`` — JSON-RPC error object (``{"code", "message"}``).
  When set, ``session/prompt`` returns an error instead of a result.
- ``STUB_ACP_CANCEL_STOP_REASON`` — string placed in the ``session/prompt``
  result *if a cancel is received mid-prompt*. Default ``"cancelled"``.
- ``STUB_ACP_CRASH_AFTER_INIT`` — if ``"1"``, exit with code 17 after
  emitting the initialize response. Models a crash during the handshake.
- ``STUB_ACP_EXIT_ON_CANCEL`` — if ``"1"``, exit cleanly after
  receiving ``session/cancel``. Models an agent that closes the pipe.
- ``STUB_ACP_EMIT_PERMISSION_REQUEST`` — if ``"1"``, emit a
  ``session/request_permission`` JSON-RPC **request** (with a unique id)
  as part of the prompt notification sequence, then await the matching
  JSON-RPC response on stdin. On receipt, validates the response shape
  and records the outcome in ``permission_responses``.

All timing defaults to "as fast as possible" — the agent responds
immediately. For scheduled-delay behaviour, use ``STUB_ACP_DELAY_MS``
(applied before each frame emission).

U6.5 NOTE: The correct ACP wire protocol for permission requests is:
  - Agent → client: JSON-RPC *request* ``session/request_permission`` (has id)
  - Client → agent: JSON-RPC *response* (matching id, result.outcome, no method)
There is no ``session/respond`` method on the agent side.
"""

from __future__ import annotations

import json
import os
import sys
import time


def _env_json(key: str, default):
    raw = os.environ.get(key)
    if not raw:
        return default
    return json.loads(raw)


# Per-process counter — incremented before each session/prompt response so
# that STUB_ACP_PROMPT_UPDATES_SEQ can address turns by index.
_prompt_count: int = 0

# Monotonic counter for outbound request ids (session/request_permission).
_request_id_counter: int = 0

# Recorded responses to session/request_permission (U6.5).
# Each entry is the full ``result`` dict from the client's JSON-RPC response.
permission_responses: list = []


def _prompt_updates_for_turn(turn_index: int) -> list:
    """Return the notification sequence for the given (0-based) prompt turn.

    Priority:
    1. ``STUB_ACP_PROMPT_UPDATES_SEQ`` (array-of-arrays) — indexed by
       *turn_index*; last entry repeats when the array is exhausted.
    2. ``STUB_ACP_PROMPT_UPDATES`` (flat array) — same sequence every turn.
    3. Empty list — no notifications emitted.
    """
    seq_raw = os.environ.get("STUB_ACP_PROMPT_UPDATES_SEQ")
    if seq_raw:
        seq: list[list] = json.loads(seq_raw)
        if seq:
            idx = min(turn_index, len(seq) - 1)
            return seq[idx]
        return []
    # Back-compat: flat STUB_ACP_PROMPT_UPDATES applies to every turn.
    return _env_json("STUB_ACP_PROMPT_UPDATES", [])


def _emit(frame: dict) -> None:
    """Write one JSON-RPC frame as NDJSON to stdout."""
    delay = int(os.environ.get("STUB_ACP_DELAY_MS", "0"))
    if delay:
        time.sleep(delay / 1000.0)
    sys.stdout.write(json.dumps(frame) + "\n")
    sys.stdout.flush()


def _read_frame():
    line = sys.stdin.readline()
    if not line:
        return None
    return json.loads(line)


def _emit_permission_request_and_await_response(session_id: str) -> None:
    """Emit ``session/request_permission`` as a JSON-RPC request, then read
    the client's JSON-RPC response from stdin.

    U6.5: Agents send permission requests as JSON-RPC *requests* (with id).
    The client (ACPTransport) must reply with a JSON-RPC *response* carrying
    the matching id and ``result.outcome``.

    On receipt the response is validated (jsonrpc 2.0, id matches, result.outcome
    present) and stored in ``permission_responses``.
    """
    global _request_id_counter
    _request_id_counter += 1
    req_id = _request_id_counter

    _emit(
        {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": "session/request_permission",
            "params": {
                "sessionId": session_id,
                "toolCallId": "tc-99",
                "options": [
                    {"kind": "allow", "name": "Allow", "optionId": "opt-allow"},
                    {"kind": "deny", "name": "Deny", "optionId": "opt-deny"},
                ],
            },
        }
    )

    # Drain stdin frames until we find the response for this request id.
    # We may receive unrelated frames (e.g. a session/cancel) before our
    # response arrives; buffer those for the main loop to handle.
    # For test purposes we only handle the simple case where the response
    # arrives promptly.
    for _ in range(20):
        resp = _read_frame()
        if resp is None:
            return  # stdin closed
        resp_id = resp.get("id")
        if resp_id == req_id and "result" in resp and "method" not in resp:
            # This is our response.
            result = resp.get("result") or {}
            outcome = result.get("outcome")
            assert isinstance(outcome, dict), (
                f"permission response result.outcome must be a dict, got {outcome!r}"
            )
            assert "outcome" in outcome, f"outcome dict must have 'outcome' key, got {outcome!r}"
            permission_responses.append(result)
            return
        # Not our response — push back into the dispatch queue.
        # For the stub's simple read-one-frame-at-a-time model, we just
        # process unrelated frames here and continue draining.
        method = resp.get("method")
        if method == "session/cancel":
            cancel_req_id = resp.get("id")
            if cancel_req_id is not None:
                _emit({"jsonrpc": "2.0", "id": cancel_req_id, "result": None})
            if os.environ.get("STUB_ACP_EXIT_ON_CANCEL") == "1":
                return


def main() -> int:
    # --- Stage 1: pre-init notifications (Kiro-style) ---------------------
    for notif in _env_json("STUB_ACP_PRE_INIT_NOTIFS", []):
        _emit(notif)

    session_id = "stub-session-1"

    # --- Stage 2: handle requests ----------------------------------------
    while True:
        frame = _read_frame()
        if frame is None:
            # Client closed stdin.
            return 0

        method = frame.get("method")
        req_id = frame.get("id")

        if method == "initialize":
            result = _env_json(
                "STUB_ACP_INIT_RESULT",
                {
                    "protocolVersion": 1,
                    "agentCapabilities": {
                        "loadSession": True,
                        "promptCapabilities": {"image": False, "audio": False},
                    },
                    "authMethods": [],
                    "agentInfo": {"name": "Stub ACP Agent", "version": "0.0.1"},
                },
            )
            _emit({"jsonrpc": "2.0", "id": req_id, "result": result})
            if os.environ.get("STUB_ACP_CRASH_AFTER_INIT") == "1":
                return 17

        elif method == "session/new":
            result = _env_json(
                "STUB_ACP_NEW_SESSION_RESULT",
                {
                    "sessionId": session_id,
                    "modes": {
                        "currentModeId": "default",
                        "availableModes": [
                            {
                                "id": "default",
                                "name": "Default",
                                "description": "Prompts for approval",
                            }
                        ],
                    },
                },
            )
            session_id = result.get("sessionId", session_id)
            _emit({"jsonrpc": "2.0", "id": req_id, "result": result})
            # Post-new-session notifications (e.g. available_commands_update).
            for notif in _env_json("STUB_ACP_POST_NEW_SESSION_UPDATES", []):
                _emit(notif)

        elif method == "session/prompt":
            global _prompt_count
            turn_index = _prompt_count
            _prompt_count += 1
            # Emit any scripted updates first, then the result.
            for notif in _prompt_updates_for_turn(turn_index):
                _emit(notif)

            # U6.5: if scripted, emit a session/request_permission request and
            # await the client's JSON-RPC response before finishing the turn.
            if os.environ.get("STUB_ACP_EMIT_PERMISSION_REQUEST") == "1":
                _emit_permission_request_and_await_response(session_id)

            error = _env_json("STUB_ACP_PROMPT_ERROR", None)
            if error is not None:
                _emit({"jsonrpc": "2.0", "id": req_id, "error": error})
                continue

            stop_reason = os.environ.get("STUB_ACP_PROMPT_STOP_REASON", "end_turn")
            _emit(
                {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {"stopReason": stop_reason},
                }
            )

        elif method == "session/cancel":
            # Respond to the cancel itself, then close if scripted.
            if req_id is not None:
                _emit({"jsonrpc": "2.0", "id": req_id, "result": None})
            if os.environ.get("STUB_ACP_EXIT_ON_CANCEL") == "1":
                return 0

        else:
            # Unknown methods → -32601.
            if req_id is not None:
                _emit(
                    {
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "error": {
                            "code": -32601,
                            "message": f'"Method not found": {method}',
                            "data": {"method": method},
                        },
                    }
                )


if __name__ == "__main__":
    sys.exit(main())
