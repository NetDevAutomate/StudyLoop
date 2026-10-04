"""The CLI side of mentor delivery: post a phase result to the web server's loopback route.

``studyloop drill`` runs in its own process; the mentor's transport lives in the web server
process that claimed the session (ADR-0012, M0 Q2 option (b)). This module is the *hop*
between them. It sends **typed fields, never rendered text** -- the server (lane T's
``session/module_delivery.py`` validator + lane W's route) re-renders, re-bounds to 8 KiB,
strips control bytes, chooses the framing and delivers; the CLI only reports the outcome.

Field names W's route and T2's ``PracticeCheckEnvelope`` build to (JSON object, all keys
present, ``null`` where noted):

====================  ======================  ==========================================
field                 type                    meaning
====================  ======================  ==========================================
``session_id``        str                     ``study_session_id`` from the session state file
``module_id``         str (<= 63)             drill identity (§5.5)
``module_digest``     str (64 hex)            the snapshot digest from ``modules.lock.json``
``deck_id``           str (<= 63, slug)       drill identity
``task_id``           str (<= 63, slug)       drill identity; ``STUDYLOOP_DRILL_ID`` is deck/task
``attempt_id``        str (<= 64)             the attempt the phase ran in
``phase``             "setup"|"check"|"cleanup"
``exit_class``        "passed"|"failed"|"error"
``exit_code``         int | null              ``null`` when the runner stopped the child
``duration_seconds``  float
``timed_out``         bool
``truncated``         bool                    a streamed cap was hit
``cap_hit``           "stdout"|"stderr"|"lines"|null
``message``           str                     the runner's one-line reading of the outcome
``stdout_tail``       str (<= 8 KiB)          redacted, already capped by the runner, tail-cut
``stderr_tail``       str (<= 8 KiB)          redacted, already capped by the runner, tail-cut
``triggered_by``      "learner"               v1 has no automatic checks (§7)
====================  ======================  ==========================================

Transport: ``POST http://127.0.0.1:<web_port>/api/modules/practice-check`` with
``Content-Type: application/json`` and the per-session capability token in the
:data:`TOKEN_HEADER` header. Both ``web_port`` and the token come from the owner-only
session state file (``session_state.py``: dir ``0o700``, file ``0o600``); the token is
minted by the web process when it claims the session (lane W, wave 2) under the key
:data:`TOKEN_KEY`, beside the ``web_port`` ``orchestrator.py`` already writes. No state
file, no port, no token, or a refused connection all mean there is no live session to tell:
``no_active_session``. A 2xx reply carrying ``{"status": <one of the six>, "reason": ...}``
is the server's own delivery outcome and is reported as-is; a bare 2xx is ``delivered``;
any other status is ``error``. The hop never retries.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import TYPE_CHECKING, Any, cast, get_args

from studyloop import session_state
from studyloop.modules.attempt import DeliveryOutcome, DeliveryStatus

if TYPE_CHECKING:
    from collections.abc import Mapping

    from studyloop.modules.attempt import Attempt, PhaseResult

__all__ = [
    "HOP_TAIL_BYTES",
    "ROUTE",
    "TOKEN_HEADER",
    "TOKEN_KEY",
    "DeliveryOutcome",
    "check_result_fields",
    "post_check_result",
]

#: The loopback route lane W mounts in wave 2 (M0 Q2 items 1-5).
ROUTE = "/api/modules/practice-check"

#: Request header carrying the per-session capability token. A custom header rather than
#: ``Authorization`` so it cannot collide with the web app's optional Basic Auth.
TOKEN_HEADER = "X-StudyLoop-Session-Token"

#: Session-state key under which the web process writes the capability token at claim.
TOKEN_KEY = "practice_check_token"

#: Session-state key the orchestrator already writes for the dashboard's port.
PORT_KEY = "web_port"

#: Session-state key naming the claimed study session.
SESSION_KEY = "study_session_id"

#: Client-side bound on each tail. The runner's caps (64/16 KiB) already apply; the server
#: re-bounds the whole envelope to 8 KiB, so sending more than that per stream is waste.
HOP_TAIL_BYTES = 8 * 1024

#: Longer than the server's 120 s ACP delivery bound (M0 Q5) so a slow-but-successful
#: delivery is not misreported by the client.
DEFAULT_TIMEOUT_SECONDS = 130.0

_STATUSES: frozenset[str] = frozenset(get_args(DeliveryStatus))


def _tail(text: str, limit: int = HOP_TAIL_BYTES) -> str:
    encoded = text.encode("utf-8")
    if len(encoded) <= limit:
        return text
    return encoded[-limit:].decode("utf-8", errors="ignore")


def check_result_fields(
    attempt: Attempt, result: PhaseResult, *, session_id: str
) -> dict[str, Any]:
    """The typed payload for one phase result -- the field table in the module docstring."""
    return {
        "session_id": session_id,
        "module_id": attempt.drill.module_id,
        "module_digest": attempt.drill.module_digest,
        "deck_id": attempt.drill.deck_id,
        "task_id": attempt.drill.task_id,
        "attempt_id": attempt.attempt_id,
        "phase": result.phase.value,
        "exit_class": result.exit_class.value,
        "exit_code": result.exit_code,
        "duration_seconds": result.duration_seconds,
        "timed_out": result.timed_out,
        "truncated": result.truncated,
        "cap_hit": result.cap_hit,
        "message": result.message,
        "stdout_tail": _tail(result.stdout),
        "stderr_tail": _tail(result.stderr),
        "triggered_by": "learner",
    }


def session_endpoint(state: Mapping[str, Any] | None = None) -> tuple[str, str, str] | None:
    """``(url, token, session_id)`` from the session state file, or ``None`` when no session.

    ``state`` defaults to :func:`studyloop.session_state.read_session_state` (looked up on the
    module at call time so the test suite's session-dir isolation applies).
    """
    if state is None:
        state = session_state.read_session_state()
    if not state or state.get("mode") == "ended":
        return None
    port = state.get(PORT_KEY)
    token = state.get(TOKEN_KEY)
    session_id = state.get(SESSION_KEY)
    if not port or not token or not session_id:
        return None
    try:
        port_number = int(port)
    except (TypeError, ValueError):
        return None
    return f"http://127.0.0.1:{port_number}{ROUTE}", str(token), str(session_id)


def _outcome_from_response(status_code: int, body: bytes) -> DeliveryOutcome:
    if not 200 <= status_code < 300:
        return DeliveryOutcome("error", f"http {status_code}")
    try:
        payload = json.loads(body.decode("utf-8")) if body else {}
    except (UnicodeDecodeError, json.JSONDecodeError):
        return DeliveryOutcome("delivered")
    if isinstance(payload, dict):
        status = payload.get("status")
        if isinstance(status, str) and status in _STATUSES:
            reason = payload.get("reason")
            return DeliveryOutcome(cast("DeliveryStatus", status), str(reason) if reason else "")
    return DeliveryOutcome("delivered")


def post_check_result(
    fields: Mapping[str, Any],
    *,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    state: Mapping[str, Any] | None = None,
) -> DeliveryOutcome:
    """POST the typed fields to the loopback route and map the reply to a DeliveryOutcome.

    Never raises: every failure is one of the six outcomes. ``fields["session_id"]`` is set
    from the state file when the caller left it empty, so the server can bind the request
    to the active session (M0 Q2 item 3).
    """
    endpoint = session_endpoint(state)
    if endpoint is None:
        return DeliveryOutcome("no_active_session", "no session state file or no web port/token")
    url, token, session_id = endpoint
    payload = dict(fields)
    payload.setdefault("session_id", session_id)
    if not payload.get("session_id"):
        payload["session_id"] = session_id
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            TOKEN_HEADER: token,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            return _outcome_from_response(response.status, response.read())
    except urllib.error.HTTPError as exc:
        return _outcome_from_response(exc.code, exc.read() if exc.fp else b"")
    except urllib.error.URLError as exc:
        reason = exc.reason
        if isinstance(reason, ConnectionRefusedError | ConnectionResetError):
            return DeliveryOutcome("no_active_session", "connection refused on the web port")
        if isinstance(reason, TimeoutError):
            return DeliveryOutcome("error", f"hop timed out after {timeout_seconds:.0f}s")
        return DeliveryOutcome("error", f"hop failed: {reason}")
    except TimeoutError:
        return DeliveryOutcome("error", f"hop timed out after {timeout_seconds:.0f}s")
    except OSError as exc:
        return DeliveryOutcome("error", f"hop failed: {exc}")
