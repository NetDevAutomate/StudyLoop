"""The CLI side of mentor delivery: post a phase result to the web server's loopback route.

``studyloop drill`` runs in its own process; the mentor's transport lives in the web server
process that claimed the session (ADR-0012, M0 Q2 option (b)). This module is the *hop*
between them. It sends **typed fields, never rendered text** -- the server (lane T's
``session/module_delivery.py`` validator + lane W's route) re-renders, re-bounds to 8 KiB,
strips control bytes, chooses the framing and delivers; the CLI only reports the outcome.

**The body is exactly lane T's ``PracticeCheckEnvelope`` and nothing else** (M1 Q6). T's
model is ``extra: forbid``, so one extra key is a rejected hop. Field table, copied from
``session/module_delivery.py`` (W's route passes the parsed object to ``validate_envelope``):

====================  ======================  ==========================================
field                 type / bound            source in this lane
====================  ======================  ==========================================
``module_id``         slug, 1-63 chars        ``Attempt.drill.module_id``
``module_digest``     ``sha256:`` + 12-64 hex  ``Attempt.drill.module_digest`` -- the lockfile
                                              digest in its canonical ``sha256:<64 hex>`` form
                                              (C's ``LockEntry.digest``)
``deck_id``           slug                    ``Attempt.drill.deck_id``
``task_id``           slug                    ``Attempt.drill.task_id``
``attempt_id``        1-64 ``[A-Za-z0-9._:-]`` ``Attempt.attempt_id`` (a uuid4)
``phase``             setup|check|cleanup     ``PhaseResult.phase``
``exit_class``        passed|failed|error     ``PhaseResult.exit_class``
``exit_code``         int, -128..255          ``PhaseResult.exit_code``; when the runner
                                              stopped the child (``None`` in the result) the
                                              child's real return code (negative = signal)
``duration_s``        float, 0..604800        ``PhaseResult.duration_seconds``
``stdout_tail``       str                     redacted, runner-capped, tail-cut to 8 KiB here
``stderr_tail``       str                     as ``stdout_tail``
``triggered_by``      ``"learner"``           v1 has no automatic checks (§7)
====================  ======================  ==========================================

Not in the body, on purpose: ``message`` (the server renders from the typed fields --
M0 Q2.4), ``timed_out`` / ``truncated`` / ``cap_hit`` (recorded on the
``practice_check_events`` row, not part of T's envelope), and ``session_id`` (the
capability token is minted per session, so the token identifies the session; the envelope
has no such field).

Transport: ``POST http://127.0.0.1:<web_port>/api/modules/practice-check`` with
``Content-Type: application/json`` and the per-session capability token in the
:data:`TOKEN_HEADER` header. Both ``web_port`` and the token come from the session state
file (``session_state.STATE_FILE``), which the hop trusts **only** when it is a regular file
(not a symlink), owned by the current uid, with ``mode & 0o077 == 0`` (M1 Q6) -- the file
carries the capability token, and ``session_state._write_file_secure`` writes it ``0o600``
in a ``0o700`` directory, so anything looser means someone else wrote or loosened it. The
token key is :data:`TOKEN_KEY`, written by the web process when it claims the session
(lane W, wave 2), beside the ``web_port`` ``orchestrator.py`` already writes. No state file,
an untrusted one, no port or token, or a refused connection all mean there is no live
session to tell: ``no_active_session`` with the reason. A 2xx reply carrying
``{"status": <one of the six>, "reason": ...}`` is the server's own delivery outcome and is
reported as-is; a bare 2xx is ``delivered``; any other status is ``error``. The hop never
retries.
"""

from __future__ import annotations

import json
import os
import stat
import urllib.error
import urllib.request
from typing import TYPE_CHECKING, Any, cast, get_args

from studyloop import session_state
from studyloop.modules.attempt import DeliveryOutcome, DeliveryStatus

if TYPE_CHECKING:
    from collections.abc import Mapping

    from studyloop.modules.attempt import Attempt, PhaseResult

__all__ = [
    "ENVELOPE_FIELDS",
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

#: Session-state key naming the claimed study session (read for the active check only).
SESSION_KEY = "study_session_id"

#: Client-side bound on each tail. The runner's caps (64/16 KiB) already apply; the server
#: re-bounds the whole envelope to 8 KiB, so sending more than that per stream is waste.
HOP_TAIL_BYTES = 8 * 1024

#: Longer than the server's 120 s ACP delivery bound (M0 Q5) so a slow-but-successful
#: delivery is not misreported by the client.
DEFAULT_TIMEOUT_SECONDS = 130.0

#: Exactly lane T's ``PracticeCheckEnvelope`` field names -- the body's key set.
ENVELOPE_FIELDS: frozenset[str] = frozenset(
    {
        "module_id",
        "module_digest",
        "deck_id",
        "task_id",
        "attempt_id",
        "phase",
        "exit_class",
        "exit_code",
        "duration_s",
        "stdout_tail",
        "stderr_tail",
        "triggered_by",
    }
)

#: Wire exit code when neither the result nor the process has one (a phase that never
#: started and recorded no code) -- the runner's own "could not execute" convention.
_EXIT_CODE_FALLBACK = 126

_STATUSES: frozenset[str] = frozenset(get_args(DeliveryStatus))


def _tail(text: str, limit: int = HOP_TAIL_BYTES) -> str:
    encoded = text.encode("utf-8")
    if len(encoded) <= limit:
        return text
    return encoded[-limit:].decode("utf-8", errors="ignore")


def _wire_exit_code(result: PhaseResult) -> int:
    """T's ``exit_code`` is a required int: the result's own code, else the child's real
    return code (negative = killed by that signal), else the not-started convention."""
    if result.exit_code is not None:
        return result.exit_code
    if result.process_returncode is not None:
        return result.process_returncode
    return _EXIT_CODE_FALLBACK


def check_result_fields(attempt: Attempt, result: PhaseResult) -> dict[str, Any]:
    """The typed payload for one phase result -- exactly :data:`ENVELOPE_FIELDS`."""
    fields = {
        "module_id": attempt.drill.module_id,
        "module_digest": attempt.drill.module_digest,
        "deck_id": attempt.drill.deck_id,
        "task_id": attempt.drill.task_id,
        "attempt_id": attempt.attempt_id,
        "phase": result.phase.value,
        "exit_class": result.exit_class.value,
        "exit_code": _wire_exit_code(result),
        "duration_s": max(0.0, result.duration_seconds),
        "stdout_tail": _tail(result.stdout),
        "stderr_tail": _tail(result.stderr),
        "triggered_by": "learner",
    }
    assert set(fields) == ENVELOPE_FIELDS
    return fields


def _load_trusted_state() -> tuple[dict[str, Any] | None, str]:
    """``(state, reason)``: the session state file's JSON, or ``None`` and why it was refused.

    Trust conditions (M1 Q6): a regular file (``lstat`` -- a symlink is refused, never
    followed), owned by the current uid, ``mode & 0o077 == 0``. The content is then read
    through an ``O_NOFOLLOW`` descriptor so the checked inode is the one read.
    """
    path = session_state.STATE_FILE
    try:
        st = os.stat(path, follow_symlinks=False)
    except FileNotFoundError:
        return None, "no session state file"
    except OSError as exc:
        return None, f"session state file unreadable: {exc.strerror}"
    if not stat.S_ISREG(st.st_mode):
        return None, "session state file is not a regular file (symlink or special file)"
    if st.st_uid != os.getuid():
        return None, f"session state file is owned by uid {st.st_uid}, not this user"
    if st.st_mode & 0o077:
        return None, (
            f"session state file mode {oct(st.st_mode & 0o777)} is readable by others; "
            "expected 0o600"
        )
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError as exc:
        return None, f"session state file unreadable: {exc.strerror}"
    try:
        with os.fdopen(fd, encoding="utf-8") as handle:
            data = json.loads(handle.read())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return None, f"session state file is not valid JSON: {exc}"
    if not isinstance(data, dict):
        return None, "session state file does not hold an object"
    return data, ""


def session_endpoint(
    state: Mapping[str, Any] | None = None,
) -> tuple[tuple[str, str] | None, str]:
    """``((url, token), "")`` from the session state, or ``(None, reason)`` when no session.

    ``state`` defaults to the trusted read of ``session_state.STATE_FILE`` (looked up on the
    module at call time so the test suite's session-dir isolation applies).
    """
    reason = ""
    if state is None:
        loaded, reason = _load_trusted_state()
        if loaded is None:
            return None, reason
        state = loaded
    if not state or state.get("mode") == "ended":
        return None, "no active session (state file empty or session ended)"
    port = state.get(PORT_KEY)
    token = state.get(TOKEN_KEY)
    session_id = state.get(SESSION_KEY)
    if not session_id:
        return None, "no active session (no study_session_id in the state file)"
    if not port:
        return None, "no web port in the session state file"
    if not token:
        return None, "no capability token in the session state file (web process not claimed)"
    try:
        port_number = int(port)
    except (TypeError, ValueError):
        return None, f"web port {port!r} in the session state file is not a number"
    return (f"http://127.0.0.1:{port_number}{ROUTE}", str(token)), ""


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

    Never raises: every failure is one of the six outcomes. ``fields`` is sent as given --
    build it with :func:`check_result_fields` so it is exactly T's envelope.
    """
    endpoint, reason = session_endpoint(state)
    if endpoint is None:
        return DeliveryOutcome("no_active_session", reason)
    url, token = endpoint
    body = json.dumps(dict(fields)).encode("utf-8")
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
