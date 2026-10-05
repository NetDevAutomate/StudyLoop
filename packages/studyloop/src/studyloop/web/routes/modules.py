"""Module routes: the Labs entry and the ``practice_check`` loopback hop (module-contract v1).

Three surfaces, all under ``/api/modules``:

``GET /modules/labs``
    Installed modules' decks and tasks **by id and prompt** (plus ``successCriteria``, the
    phases a task declares and the exact ``studyloop drill`` commands for them). Read from
    lane C's lockfile and snapshots on every call -- ``module add`` / ``module remove`` while
    the server runs are visible on the next request. Nothing mentor-side ever leaves this
    process: ``hint``, ``solution`` and ``mentorNotes`` reach the learner through the mentor
    alone (proposal §5.6, web-ui spec scenario 3, C7). ``GET /session/options`` carries the
    same list under ``labs`` only when it is non-empty (web-ui spec scenarios 1-2).

``POST /modules/labs/start`` / ``POST /modules/labs/cancel``
    "Starting a drill uses the existing session start + terminal inside the one claimed
    session" (proposal §7). With no session in this process the drill's session is started
    through the one start path (``session/_start.py``'s ``start_session``) and the start
    payload comes back with ``drill`` added (201); with the learner's session already live
    the drill is bound to it (200, ``attached``). Either way the state file records
    ``labs_drill`` and the capability below. **No phase runs here**: the browser has no
    consent surface in v1 (§5.5 -- consent is per phase, per execution, and ``studyloop
    drill`` has no ``--yes``), browser-triggered execution is v1.1 (§8), and the proposal's
    MVP row says checks are triggered from the CLI. Cancel clears ``labs_drill`` and touches
    nothing else -- the session is where it was, nothing was executed.

``POST /modules/practice-check``
    Council M0 Q2, items 1-5, in this order: (1) loopback only, judged on the connection's
    peer address, never a header; (2) the per-session capability token
    (``hop.TOKEN_HEADER``) compared in constant time against ``practice_check_token`` in the
    owner-only session state file -- no header is 401, a mismatch is 403; (3) exact binding:
    the session the token names must be the one this process holds (403 otherwise), replay
    dedup on ``(attempt_id, phase)`` (409) and a burst limit per session (429), both in
    process memory; (4) lane T's ``validate_envelope`` on the typed fields (422 naming the
    field, never the value) and ``deliver_to_active_session`` -- the server renders and
    bounds, the CLI never does; (5) the outcome's ``status`` / ``reason`` returned as JSON with
    200, *including* a delivery that did not land: lane R's hop already maps any non-2xx to
    its own ``error``, so the status codes above are exactly the contract the learner sees.

The capability token is minted by ``session/orchestrator.py`` (``mint_practice_check_token``)
and written beside ``web_port`` -- by ``studyloop study`` when it launches the dashboard, and
here when a drill goes live in a web-claimed session (the only moment this process knows a
drill is coming and the only session kind delivery can reach).
"""

from __future__ import annotations

import hmac
import ipaddress
import json
import logging
import time
from collections import deque
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Literal

import yaml
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from studyloop import session_state
from studyloop.content.schemas import PracticeDeck, PracticeTask, SlugId
from studyloop.modules import hop, store
from studyloop.modules.manifest import ModuleManifest
from studyloop.session import active
from studyloop.session.module_delivery import (
    EnvelopeValidationError,
    deliver_to_active_session,
    validate_envelope,
)

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)

router = APIRouter()

__all__ = [
    "LABS_DRILL_KEY",
    "MENTOR_ONLY_FIELDS",
    "RATE_LIMIT_BURST",
    "RATE_LIMIT_WINDOW_SECONDS",
    "contains_mentor_only_fields",
    "drill_view",
    "ensure_practice_check_capability",
    "labs_listing",
    "reset_practice_check_guards",
    "router",
]

#: Task fields that are mentor-side material (proposal §5.6) and never on this wire. The
#: snake_case twin is the Python attribute name; a serialiser that forgot the alias would
#: leak under it.
MENTOR_ONLY_FIELDS: frozenset[str] = frozenset({"hint", "solution", "mentorNotes", "mentor_notes"})

#: Session-state key naming the drill the learner started from Labs (cleared on cancel).
LABS_DRILL_KEY = "labs_drill"

#: M0 Q2.3: one envelope per phase per attempt (the dedup), burst 5 per minute per session.
RATE_LIMIT_BURST = 5
RATE_LIMIT_WINDOW_SECONDS = 60.0

_PHASE_FIELDS: tuple[tuple[str, str], ...] = (
    ("setup", "setup_command"),
    ("check", "command"),
    ("cleanup", "cleanup_command"),
)


# ---------------------------------------------------------------------------
# the Labs listing
# ---------------------------------------------------------------------------


def contains_mentor_only_fields(value: object) -> bool:
    """True when any mapping anywhere inside ``value`` carries a mentor-only key."""
    if isinstance(value, dict):
        return any(str(key) in MENTOR_ONLY_FIELDS for key in value) or any(
            contains_mentor_only_fields(item) for item in value.values()
        )
    if isinstance(value, list | tuple):
        return any(contains_mentor_only_fields(item) for item in value)
    return False


def _task_phases(task: PracticeTask) -> list[str]:
    verification = task.verification
    if verification is None or verification.kind != "command":
        return []
    return [phase for phase, field in _PHASE_FIELDS if getattr(verification, field, "").strip()]


def drill_view(module_id: str, deck: PracticeDeck, task: PracticeTask) -> dict[str, Any]:
    """What the learner may see of one task: ids, prompt, success criteria, the commands."""
    ref = f"{module_id}/{deck.id}/{task.id}"
    phases = _task_phases(task)
    return {
        "id": task.id,
        "ref": ref,
        "prompt": task.prompt,
        "successCriteria": list(task.success_criteria),
        "phases": phases,
        "commands": [f"studyloop drill {phase} {ref}" for phase in phases],
    }


def _read_manifest(snapshot: Path) -> ModuleManifest | None:
    try:
        raw = yaml.safe_load((snapshot / "module.yaml").read_text(encoding="utf-8"))
        return ModuleManifest.model_validate(raw)
    except (OSError, ValueError, yaml.YAMLError, ValidationError):
        logger.warning("Labs: module.yaml under %s does not validate; listing without it", snapshot)
        return None


def _read_decks(snapshot: Path) -> list[PracticeDeck]:
    decks_dir = snapshot / "decks"
    decks: list[PracticeDeck] = []
    for path in sorted(decks_dir.glob("*.json")) if decks_dir.is_dir() else []:
        if not path.is_file() or path.is_symlink():
            continue  # MC013: only regular files are module content
        try:
            deck = PracticeDeck.model_validate(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError, ValidationError):
            logger.warning("Labs: deck %s does not validate; skipped", path)
            continue
        if deck.id is not None:
            decks.append(deck)
    return decks


def labs_listing(root: Path | None = None) -> list[dict[str, Any]]:
    """Installed modules -> decks -> tasks, by id and prompt (``root`` defaults to the store)."""
    try:
        entries = store.load_lockfile(root)
    except store.StoreError as exc:
        logger.warning("Labs: lockfile unreadable (%s); no module is listed", exc)
        return []
    listing: list[dict[str, Any]] = []
    for entry in entries:
        snapshot = store.snapshot_dir(entry)
        manifest = _read_manifest(snapshot)
        decks = [
            {
                "id": deck.id,
                "title": deck.title,
                "tasks": [drill_view(entry.id, deck, task) for task in deck.tasks if task.id],
            }
            for deck in _read_decks(snapshot)
        ]
        listing.append(
            {
                "module_id": entry.id,
                "version": entry.version,
                "title": manifest.title if manifest else entry.id,
                "topic": manifest.topic if manifest else "",
                "decks": decks,
            }
        )
    # By construction nothing mentor-side is in a drill_view; this is the tripwire.
    assert not contains_mentor_only_fields(listing), "mentor-only field in the Labs listing"
    return listing


def _find_drill(module_id: str, deck_id: str, task_id: str) -> dict[str, Any] | None:
    for module in labs_listing():
        if module["module_id"] != module_id:
            continue
        for deck in module["decks"]:
            if deck["id"] != deck_id:
                continue
            for task in deck["tasks"]:
                if task["id"] == task_id:
                    return {
                        "module_id": module_id,
                        "deck_id": deck_id,
                        "task_id": task_id,
                        **task,
                    }
    return None


@router.get("/modules/labs")
def get_labs() -> dict[str, Any]:
    """The Labs list plus the agent choices the start needs (same builder as the picker)."""
    from studyloop.web.routes.session._options import _agent_options

    return {"labs": labs_listing(), "agents": _agent_options()}


# ---------------------------------------------------------------------------
# the capability token (M0 Q2.2)
# ---------------------------------------------------------------------------


def _server_port(request: Request) -> int | None:
    port = request.url.port
    if port:
        return int(port)
    server = request.scope.get("server")
    if isinstance(server, list | tuple) and len(server) == 2 and server[1]:
        return int(server[1])
    return None


def ensure_practice_check_capability(request: Request) -> None:
    """Make sure the state file carries ``practice_check_token`` and ``web_port``.

    Minting is the orchestrator's (``mint_practice_check_token``); this only fills what is
    missing, so a token ``studyloop study`` wrote at launch is kept. Nothing is returned:
    the token is for ``studyloop drill`` to read from the owner-only file, never for a
    browser response.
    """
    from studyloop.session.orchestrator import mint_practice_check_token

    state = session_state.read_session_state()
    updates: dict[str, Any] = {}
    if not state.get(hop.TOKEN_KEY):
        updates[hop.TOKEN_KEY] = mint_practice_check_token()
    port = _server_port(request)
    if port is not None and state.get(hop.PORT_KEY) != port:
        updates[hop.PORT_KEY] = port
    if updates:
        session_state.write_session_state(updates)


# ---------------------------------------------------------------------------
# Labs start / cancel
# ---------------------------------------------------------------------------


class LabsStartRequest(BaseModel):
    """``POST /modules/labs/start``: which drill, and how to start the session if needed."""

    model_config = ConfigDict(extra="forbid")

    module_id: SlugId
    deck_id: SlugId
    task_id: SlugId
    energy: int = Field(default=5, ge=1, le=10)
    agent: str | None = None
    transport: Literal["pty", "acp"] | None = None


def _labs_topic(drill: dict[str, Any]) -> str:
    return f"Lab: {drill['ref']}"


def _record_live_drill(drill: dict[str, Any]) -> None:
    session_state.write_session_state(
        {
            LABS_DRILL_KEY: {
                "module_id": drill["module_id"],
                "deck_id": drill["deck_id"],
                "task_id": drill["task_id"],
                "ref": drill["ref"],
                "started_at": datetime.now(UTC).isoformat(),
            }
        }
    )


@router.post("/modules/labs/start")
async def start_lab(body: LabsStartRequest, request: Request) -> JSONResponse:
    """Start the chosen drill inside the one claimed session (proposal §7 Labs row)."""
    drill = _find_drill(body.module_id, body.deck_id, body.task_id)
    if drill is None:
        return JSONResponse(
            {
                "error": (
                    f"no installed drill {body.module_id}/{body.deck_id}/{body.task_id}; "
                    "`studyloop module list` shows what is installed"
                )
            },
            status_code=404,
        )

    current = await active.current()
    if current is not None:
        state = session_state.read_session_state()
        same_file = state.get(hop.SESSION_KEY) == current.study_session_id
        origin = str(state.get("origin") or "study") if same_file else "study"
        if origin != "study":
            # The Study Session console is the mentor pane; it must not adopt another
            # view's PTY (the origin guard), so a drill cannot go live there.
            return JSONResponse(
                {
                    "error": "A session is live in another view; end it or finish there first",
                    "study_session_id": current.study_session_id,
                    "origin": origin,
                },
                status_code=409,
            )
        ensure_practice_check_capability(request)
        _record_live_drill(drill)
        return JSONResponse(
            {
                "attached": True,
                "study_session_id": current.study_session_id,
                "topic": state.get("topic") if same_file else None,
                "transport": state.get("transport") if same_file else None,
                "reattach_url": f"/api/session/ws?study_session_id={current.study_session_id}",
                "drill": drill,
            },
            status_code=200,
        )

    # No session in this process: the one start path. A cross-process claim (a CLI
    # `studyloop study` session) is its 409, an absent agent its 503 -- passed through
    # untouched so the browser handles them exactly as the picker does.
    from studyloop.web.routes.session._models import StartSessionRequest
    from studyloop.web.routes.session._start import start_session

    start_body = StartSessionRequest(
        topic=_labs_topic(drill),
        energy=body.energy,
        agent=body.agent,
        transport=body.transport,
        purpose="focus",
    )
    response = await start_session(start_body, request)
    if response.status_code != 201:
        return response
    ensure_practice_check_capability(request)
    _record_live_drill(drill)
    payload = json.loads(bytes(response.body))
    payload.update({"attached": False, "drill": drill})
    return JSONResponse(payload, status_code=201)


@router.post("/modules/labs/cancel")
async def cancel_lab() -> dict[str, Any]:
    """Abandon the drill started from Labs. The session stays as it was; nothing ran."""
    state = session_state.read_session_state()
    if state.get(LABS_DRILL_KEY) is not None:
        session_state.write_session_state({LABS_DRILL_KEY: None})
    current = await active.current()
    session_id = current.study_session_id if current is not None else state.get(hop.SESSION_KEY)
    return {"cancelled": True, "study_session_id": session_id}


# ---------------------------------------------------------------------------
# POST /modules/practice-check -- the loopback hop
# ---------------------------------------------------------------------------

#: ``hop.ROUTE`` is the full path the CLI posts to; the router is mounted under ``/api``.
_ROUTE_UNDER_API = hop.ROUTE.removeprefix("/api")

#: Per-session replay memory and burst window. One claimed session at a time, so the
#: memory is pruned to the session that last posted (``_remember``).
_seen: dict[str, set[tuple[str, str]]] = {}
_bursts: dict[str, deque[float]] = {}


def reset_practice_check_guards() -> None:
    """Forget every session's replay and burst memory (tests)."""
    _seen.clear()
    _bursts.clear()


def _is_loopback(request: Request) -> bool:
    client = request.client
    if client is None or not client.host:
        return False
    try:
        return ipaddress.ip_address(client.host).is_loopback
    except ValueError:
        return False  # a hostname is not an address we can judge; refuse


def _token_matches(presented: str, expected: object) -> bool:
    if not isinstance(expected, str) or not expected:
        return False
    return hmac.compare_digest(presented.encode("utf-8"), expected.encode("utf-8"))


def _burst_exceeded(session_id: str, now: float) -> bool:
    window = _bursts.setdefault(session_id, deque())
    while window and now - window[0] >= RATE_LIMIT_WINDOW_SECONDS:
        window.popleft()
    return len(window) >= RATE_LIMIT_BURST


def _remember(session_id: str, key: tuple[str, str], now: float) -> None:
    for stale in [sid for sid in _seen if sid != session_id]:
        _seen.pop(stale, None)
        _bursts.pop(stale, None)
    _seen.setdefault(session_id, set()).add(key)
    _bursts.setdefault(session_id, deque()).append(now)


@router.post(_ROUTE_UNDER_API)
async def practice_check(request: Request) -> JSONResponse:
    """Deliver one typed check result to the mentor in this process (M0 Q2 items 1-5)."""
    if not _is_loopback(request):
        return JSONResponse(
            {"error": "practice-check accepts loopback clients only"}, status_code=403
        )
    presented = request.headers.get(hop.TOKEN_HEADER, "")
    if not presented:
        return JSONResponse(
            {"error": f"missing {hop.TOKEN_HEADER}: no capability token presented"},
            status_code=401,
        )
    state = session_state.read_session_state()
    session_id = state.get(hop.SESSION_KEY)
    if (
        not session_id
        or state.get("mode") == "ended"
        or not _token_matches(presented, state.get(hop.TOKEN_KEY))
    ):
        return JSONResponse(
            {"error": "the token does not match the claimed session"}, status_code=403
        )
    session_id = str(session_id)
    current = await active.current()
    if current is not None and current.study_session_id != session_id:
        return JSONResponse(
            {"error": "the token names a session that is not the active one"}, status_code=403
        )

    try:
        fields = await request.json()
    except (ValueError, UnicodeDecodeError):
        return JSONResponse({"error": "body is not JSON"}, status_code=400)
    if not isinstance(fields, dict):
        return JSONResponse({"error": "body must be a JSON object"}, status_code=400)
    try:
        envelope = validate_envelope(fields)
    except EnvelopeValidationError as exc:
        return JSONResponse({"error": str(exc)}, status_code=422)

    key = (envelope.attempt_id, envelope.phase)
    if key in _seen.get(session_id, set()):
        return JSONResponse(
            {
                "status": "duplicate",
                "reason": (
                    f"{envelope.phase} of attempt {envelope.attempt_id} was already delivered"
                ),
            },
            status_code=409,
        )
    now = time.monotonic()
    if _burst_exceeded(session_id, now):
        return JSONResponse(
            {
                "error": (
                    f"more than {RATE_LIMIT_BURST} envelopes in {RATE_LIMIT_WINDOW_SECONDS:.0f}s "
                    "for this session"
                )
            },
            status_code=429,
        )
    _remember(session_id, key, now)

    outcome = await deliver_to_active_session(envelope)
    return JSONResponse({"status": outcome.status, "reason": outcome.reason}, status_code=200)
