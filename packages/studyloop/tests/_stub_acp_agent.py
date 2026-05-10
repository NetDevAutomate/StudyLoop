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
  response.
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

All timing defaults to "as fast as possible" — the agent responds
immediately. For scheduled-delay behaviour, use ``STUB_ACP_DELAY_MS``
(applied before each frame emission).
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
            # Emit any scripted updates first, then the result.
            for notif in _env_json("STUB_ACP_PROMPT_UPDATES", []):
                _emit(notif)

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
