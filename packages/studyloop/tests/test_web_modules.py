"""Lane W (module-contract v1): the Labs entry and the practice-check loopback hop.

Three surfaces, all driven through ``TestClient`` against the real app
(``create_app``), so the router inclusion in ``web/app.py`` is part of what is tested:

* ``GET /api/session/options`` carries a ``labs`` entry only when ``modules.lock.json``
  lists a module (web-ui spec, scenarios 1-2); ``GET /api/modules/labs`` lists the same
  decks and tasks by id and prompt (plus ``successCriteria``), and **never** ``hint``,
  ``solution`` or ``mentorNotes`` (spec scenario 3, proposal §5.6, C7).
* ``POST /api/modules/labs/start`` reuses the one session-start path: with no session it
  starts the claimed session for the drill (201, the start payload plus ``drill``); with
  the session live it binds the drill to it (200, ``attached``); no phase runs
  (proposal §7: checks are triggered from the CLI; §8: browser execution is v1.1).
  ``POST /api/modules/labs/cancel`` leaves the session untouched.
* ``POST /api/modules/practice-check`` is the M0 Q2 route: loopback only, per-session
  capability token, exact session binding, replay dedup on ``(attempt_id, phase)``, a
  burst limit per session, lane T's validator, and the delivery outcome returned as a 200
  whose ``status`` says what happened (the hop maps any non-2xx to its own ``error``).

The module store is pointed at a private root exactly as ``test_module_lane_seams.py``
does (``store.default_store_root`` patched); the session state dir is isolated by the
suite-wide autouse fixture in ``conftest.py``.
"""

from __future__ import annotations

import json
import os
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from _helpers import run_async

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # pyright: ignore[reportMissingImports]

from studyloop import session_state
from studyloop.modules import hop, store
from studyloop.session import active
from studyloop.session.transport import DeliveryWrite, SessionConfig, Started
from studyloop.web.app import create_app

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from studyloop.session.transport import BlockFraming, TransportEventT

_tests_dir = str(Path(__file__).parent)
if _tests_dir not in sys.path:
    sys.path.insert(0, _tests_dir)

from conftest import StubTransport  # noqa: E402  # pyright: ignore[reportAttributeAccessIssue]

FIXTURE_MODULE = Path(__file__).parent / "fixtures" / "modules" / "valid-scaffold"
FIXTURE_DECK = json.loads((FIXTURE_MODULE / "decks" / "echo-basics.json").read_text("utf-8"))
FIXTURE_TASK = FIXTURE_DECK["tasks"][0]

MODULE_ID = "echo-drills"
DECK_ID = "echo-basics"
TASK_ID = "echo-01"
DRILL_REF = f"{MODULE_ID}/{DECK_ID}/{TASK_ID}"

ROUTE = hop.ROUTE
assert ROUTE == "/api/modules/practice-check", "lane R's hop and this route must agree"
LOOPBACK = ("127.0.0.1", 50000)

#: The three mentor-side task fields (proposal §5.6) -- keys AND the fixture's values,
#: so a response that renamed a key but leaked the text still fails.
MENTOR_ONLY_KEYS = ("hint", "solution", "mentorNotes", "mentor_notes")
MENTOR_ONLY_VALUES = (FIXTURE_TASK["hint"], FIXTURE_TASK["solution"], FIXTURE_TASK["mentorNotes"])


# ---------------------------------------------------------------------------
# doubles
# ---------------------------------------------------------------------------


class FakeBlockTransport:
    """``AgentSessionTransport`` + ``BlockDeliverer``: records every delivered block."""

    block_framing: BlockFraming = "plain"

    def __init__(self) -> None:
        self.sent: list[bytes] = []
        self.running = True

    async def start(self, config: SessionConfig) -> None:
        return

    async def send_input(self, data: bytes) -> None:
        return

    async def deliver_block(self, data: bytes) -> DeliveryWrite:
        self.sent.append(data)
        return DeliveryWrite(status="written", detail=f"{len(data)} bytes")

    async def resize(self, cols: int, rows: int) -> None:
        return

    async def events(self) -> AsyncIterator[TransportEventT]:
        return
        yield  # pragma: no cover -- makes this an async generator

    async def cancel(self) -> None:
        return

    async def end(self) -> None:
        self.running = False

    def is_running(self) -> bool:
        return self.running


@dataclass
class FakeActiveSession:
    """The three fields of ``session/active.py``'s ``ActiveSession``."""

    study_session_id: str
    transport: Any
    config: SessionConfig


def _config(session_id: str) -> SessionConfig:
    return SessionConfig(
        study_session_id=session_id,
        agent="codex",
        persona_file="/dev/null",
        cwd="/",
        env={},
        cols=80,
        rows=24,
    )


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _release_active_slot():
    run_async(active.release())
    yield
    run_async(active.release())


@pytest.fixture
def store_root(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """An empty private module store; ``default_store_root`` points at it."""
    root = tmp_path / "modules"
    monkeypatch.setattr(store, "default_store_root", lambda: root)
    return root


@pytest.fixture
def installed(store_root: Path) -> store.LockEntry:
    """Lane C's valid scaffold installed into the private store."""
    return store.ModuleStore(store_root).add(FIXTURE_MODULE)


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app(study_dirs=[]))


@pytest.fixture
def loopback_client() -> TestClient:
    """A client whose peer address is the loopback -- what ``studyloop drill`` is."""
    return TestClient(create_app(study_dirs=[]), client=LOOPBACK)


@pytest.fixture
def claimed_session() -> dict[str, Any]:
    """A web-claimed session recorded in the state file, with its capability token.

    A fresh ``study_session_id`` per test: the route's replay and burst memory is keyed
    by session, so no test can see another test's envelopes.
    """
    session_id = f"s-{uuid.uuid4().hex[:12]}"
    state = {
        hop.SESSION_KEY: session_id,
        "mode": "focus",
        "transport": "pty",
        "pid": os.getpid(),
        "origin": "study",
        hop.PORT_KEY: 8567,
        hop.TOKEN_KEY: f"tok-{uuid.uuid4().hex}",
    }
    session_state.write_session_state(state)
    return state


def _envelope(**overrides: Any) -> dict[str, Any]:
    """Exactly lane R's hop body (``hop.ENVELOPE_FIELDS``) for one check result."""
    fields: dict[str, Any] = {
        "module_id": MODULE_ID,
        "module_digest": "sha256:" + "ab" * 32,
        "deck_id": DECK_ID,
        "task_id": TASK_ID,
        "attempt_id": f"attempt-{uuid.uuid4().hex[:8]}",
        "phase": "check",
        "exit_class": "failed",
        "exit_code": 1,
        "duration_s": 0.25,
        "stdout_tail": "ready\n",
        "stderr_tail": "",
        "triggered_by": "learner",
    }
    fields.update(overrides)
    return fields


def _post_check(client: TestClient, body: dict[str, Any], token: str | None, **kwargs: Any) -> Any:
    headers = {hop.TOKEN_HEADER: token} if token is not None else {}
    return client.post(ROUTE, json=body, headers=headers, **kwargs)


def _assert_no_mentor_material(payload: Any) -> None:
    text = json.dumps(payload)
    for key in MENTOR_ONLY_KEYS:
        assert f'"{key}"' not in text, f"mentor-side key {key!r} reached the wire"
    for value in MENTOR_ONLY_VALUES:
        assert value not in text, f"mentor-side text {value!r} reached the wire"


# ---------------------------------------------------------------------------
# the Labs entry (web-ui spec scenarios 1-3)
# ---------------------------------------------------------------------------


def test_options_carry_no_labs_entry_with_an_empty_lockfile(
    client: TestClient, store_root: Path
) -> None:
    response = client.get("/api/session/options")

    assert response.status_code == 200, response.text
    assert "labs" not in response.json(), "Labs must be absent, not empty, with no module"


def test_options_list_the_installed_module_by_deck_and_task_ids_and_prompts(
    client: TestClient, installed: store.LockEntry
) -> None:
    response = client.get("/api/session/options")

    assert response.status_code == 200, response.text
    labs = response.json().get("labs")
    assert labs is not None, "Labs entry missing after `module add`"
    assert [module["module_id"] for module in labs] == [MODULE_ID]
    (module,) = labs
    assert [deck["id"] for deck in module["decks"]] == [DECK_ID]
    (deck,) = module["decks"]
    assert [task["id"] for task in deck["tasks"]] == [TASK_ID]
    (task,) = deck["tasks"]
    assert task["prompt"] == FIXTURE_TASK["prompt"]
    assert task["successCriteria"] == FIXTURE_TASK["successCriteria"]
    _assert_no_mentor_material(labs)


def test_labs_route_lists_ids_prompts_and_success_criteria_only(
    client: TestClient, installed: store.LockEntry
) -> None:
    response = client.get("/api/modules/labs")

    assert response.status_code == 200, response.text
    body = response.json()
    (module,) = body["labs"]
    assert module["module_id"] == MODULE_ID
    assert module["version"] == installed.version
    (deck,) = module["decks"]
    (task,) = deck["tasks"]
    assert task["ref"] == DRILL_REF
    assert task["phases"] == ["check"], "the fixture declares a check phase only"
    assert task["commands"] == [f"studyloop drill check {DRILL_REF}"]
    assert set(task) <= {"id", "ref", "prompt", "successCriteria", "phases", "commands"}
    _assert_no_mentor_material(body)


def test_labs_route_is_empty_with_no_module(client: TestClient, store_root: Path) -> None:
    response = client.get("/api/modules/labs")

    assert response.status_code == 200, response.text
    assert response.json()["labs"] == []


# ---------------------------------------------------------------------------
# Labs start / cancel -- the one session-start path, no phase executed
# ---------------------------------------------------------------------------


@pytest.fixture
def _web_start_doubles(monkeypatch: pytest.MonkeyPatch):
    """The ``test_web_session_start_pty.py`` doubles: stub transport, fake agent, no DB."""
    stubs: list[StubTransport] = []

    def factory():
        stub = StubTransport(events=[Started(agent="claude")])
        stubs.append(stub)
        return stub

    monkeypatch.setattr(
        "studyloop.web.routes.session._build_pty_transport",
        lambda config: factory,
        raising=False,
    )
    monkeypatch.setattr("shutil.which", lambda name: f"/usr/bin/{name}")

    from studyloop.adapters._protocol import AgentAdapter
    from studyloop.agent_launcher import AGENTS

    real = AGENTS["claude"]
    monkeypatch.setitem(
        AGENTS,
        "claude",
        AgentAdapter(
            name=real.name,
            binary=real.binary,
            setup=lambda canonical, session_dir: session_dir / "persona.md",
            launch_cmd=lambda persona, resume: f"claude {persona}",
            teardown=None,
            mcp_setup=None,
        ),
    )
    monkeypatch.setattr(
        "studyloop.history.start_study_session",
        lambda topic, energy_label, topic_slug=None: "study-labs-1",
    )
    monkeypatch.setattr(
        "studyloop.history.sessions.update_persona_hash", lambda study_id, persona_hash: None
    )
    return stubs


def _start_body(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "module_id": MODULE_ID,
        "deck_id": DECK_ID,
        "task_id": TASK_ID,
        "agent": "claude",
        "transport": "pty",
    }
    body.update(overrides)
    return body


def test_labs_start_refuses_an_unknown_drill_with_404(
    loopback_client: TestClient, installed: store.LockEntry, _web_start_doubles
) -> None:
    response = loopback_client.post("/api/modules/labs/start", json=_start_body(task_id="nope"))

    assert response.status_code == 404, response.text
    assert "nope" in response.json()["error"]
    assert run_async(active.current()) is None, (
        "no session may be started for a drill that is not installed"
    )


def test_labs_start_starts_the_one_claimed_session_through_the_session_start_path(
    loopback_client: TestClient, installed: store.LockEntry, _web_start_doubles
) -> None:
    response = loopback_client.post("/api/modules/labs/start", json=_start_body())

    assert response.status_code == 201, response.text
    body = response.json()
    # The existing start payload shape, so the browser's console attaches as it would.
    assert body["study_session_id"] == "study-labs-1"
    assert body["ws_url"] == "/api/session/ws?study_session_id=study-labs-1"
    assert body["transport"] == "pty"
    assert body["attached"] is False
    assert DRILL_REF in body["topic"]
    # The drill the learner starts: prompt + success criteria + the CLI commands, no more.
    drill = body["drill"]
    assert (drill["module_id"], drill["deck_id"], drill["task_id"]) == (MODULE_ID, DECK_ID, TASK_ID)
    assert drill["prompt"] == FIXTURE_TASK["prompt"]
    assert drill["successCriteria"] == FIXTURE_TASK["successCriteria"]
    assert drill["commands"] == [f"studyloop drill check {DRILL_REF}"]
    _assert_no_mentor_material(body)
    # Inside the one claimed session: the in-process slot is held and the state file
    # names the drill, the view that owns it, and the capability the hop needs.
    current = run_async(active.current())
    assert current is not None and current.study_session_id == "study-labs-1"
    state = session_state.read_session_state()
    assert state["origin"] == "study"
    assert state["labs_drill"]["ref"] == DRILL_REF
    assert state[hop.TOKEN_KEY], "the capability token is minted when the drill goes live"
    assert isinstance(state[hop.PORT_KEY], int) and state[hop.PORT_KEY] > 0
    assert hop.TOKEN_KEY not in json.dumps(body), "the token never travels to the browser"
    # Nothing was executed: the transport saw no input and no phase ran.
    (stub,) = _web_start_doubles
    assert stub.sent_input == []


def test_labs_start_with_the_session_live_attaches_instead_of_starting_a_second(
    loopback_client: TestClient, installed: store.LockEntry, _web_start_doubles
) -> None:
    first = loopback_client.post("/api/modules/labs/start", json=_start_body())
    assert first.status_code == 201, first.text

    second = loopback_client.post("/api/modules/labs/start", json=_start_body())

    assert second.status_code == 200, second.text
    body = second.json()
    assert body["attached"] is True
    assert body["study_session_id"] == "study-labs-1"
    assert body["reattach_url"] == "/api/session/ws?study_session_id=study-labs-1"
    assert body["drill"]["ref"] == DRILL_REF
    assert len(_web_start_doubles) == 1, "a second start would have built a second transport"


def test_labs_cancel_leaves_the_session_untouched(
    loopback_client: TestClient, installed: store.LockEntry, _web_start_doubles
) -> None:
    started = loopback_client.post("/api/modules/labs/start", json=_start_body())
    assert started.status_code == 201, started.text

    response = loopback_client.post("/api/modules/labs/cancel")

    assert response.status_code == 200, response.text
    assert response.json() == {"cancelled": True, "study_session_id": "study-labs-1"}
    current = run_async(active.current())
    assert current is not None and current.study_session_id == "study-labs-1"
    state = session_state.read_session_state()
    assert state.get("labs_drill") is None, "cancel clears the live drill"
    assert state["mode"] != "ended"
    (stub,) = _web_start_doubles
    assert stub.end_calls == 0 and stub.sent_input == []


def test_labs_start_rejects_a_body_with_an_unknown_field(
    loopback_client: TestClient, installed: store.LockEntry, _web_start_doubles
) -> None:
    response = loopback_client.post("/api/modules/labs/start", json=_start_body(command="rm -rf /"))

    assert response.status_code == 422, response.text
    assert run_async(active.current()) is None


# ---------------------------------------------------------------------------
# POST /api/modules/practice-check -- the loopback hop (M0 Q2 items 1-5)
# ---------------------------------------------------------------------------


def test_practice_check_without_the_token_header_is_401(
    loopback_client: TestClient, claimed_session: dict[str, Any]
) -> None:
    response = _post_check(loopback_client, _envelope(), token=None)

    assert response.status_code == 401, response.text
    assert hop.TOKEN_HEADER in response.json()["error"]


def test_practice_check_with_the_wrong_token_is_403(
    loopback_client: TestClient, claimed_session: dict[str, Any]
) -> None:
    response = _post_check(loopback_client, _envelope(), token="tok-wrong")

    assert response.status_code == 403, response.text


def test_practice_check_from_a_non_loopback_address_is_403_even_with_the_token(
    claimed_session: dict[str, Any],
) -> None:
    lan_client = TestClient(create_app(study_dirs=[]), client=("192.168.1.20", 50000))

    response = _post_check(lan_client, _envelope(), token=claimed_session[hop.TOKEN_KEY])

    assert response.status_code == 403, response.text
    assert "loopback" in response.json()["error"]


def test_practice_check_names_an_extra_field_with_422(
    loopback_client: TestClient, claimed_session: dict[str, Any]
) -> None:
    response = _post_check(
        loopback_client,
        _envelope(message="rendered by the CLI"),
        token=claimed_session[hop.TOKEN_KEY],
    )

    assert response.status_code == 422, response.text
    error = response.json()["error"]
    assert "message" in error, "the rejected field is named"
    assert "rendered by the CLI" not in error, "never the value (module output may be secret)"


def test_practice_check_with_no_active_session_is_200_no_active_session(
    loopback_client: TestClient, claimed_session: dict[str, Any]
) -> None:
    """A delivery that did not land is a 200 whose status says so: the hop already
    treats every non-2xx as its own ``error``."""
    response = _post_check(loopback_client, _envelope(), token=claimed_session[hop.TOKEN_KEY])

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "no_active_session"
    assert body["reason"]


def test_practice_check_delivers_into_the_active_session(
    loopback_client: TestClient, claimed_session: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    transport = FakeBlockTransport()
    session_id = claimed_session[hop.SESSION_KEY]
    fake = FakeActiveSession(session_id, transport, _config(session_id))

    async def _current() -> Any:
        return fake

    monkeypatch.setattr(active, "current", _current)

    response = _post_check(loopback_client, _envelope(), token=claimed_session[hop.TOKEN_KEY])

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "delivered"
    assert len(transport.sent) == 1
    block = transport.sent[0].decode("utf-8")
    assert "<<<studyloop:practice_check v1" in block
    assert "| ready" in block, "lane T renders the tail; the route never does"


def test_practice_check_token_of_another_session_is_403_when_a_session_is_active(
    loopback_client: TestClient, claimed_session: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Exact binding (Q2.3): the token names the claimed session; a different live
    session refuses it rather than delivering into the wrong mentor."""
    other = FakeActiveSession("s-other", FakeBlockTransport(), _config("s-other"))

    async def _current() -> Any:
        return other

    monkeypatch.setattr(active, "current", _current)

    response = _post_check(loopback_client, _envelope(), token=claimed_session[hop.TOKEN_KEY])

    assert response.status_code == 403, response.text
    assert other.transport.sent == []


def test_practice_check_replay_of_the_same_attempt_and_phase_is_409(
    loopback_client: TestClient, claimed_session: dict[str, Any]
) -> None:
    body = _envelope(attempt_id="attempt-replay")
    token = claimed_session[hop.TOKEN_KEY]

    first = _post_check(loopback_client, body, token=token)
    second = _post_check(loopback_client, body, token=token)
    other_phase = _post_check(loopback_client, {**body, "phase": "cleanup"}, token=token)

    assert first.status_code == 200, first.text
    assert second.status_code == 409, second.text
    assert second.json()["status"] == "duplicate"
    assert other_phase.status_code == 200, "dedup is per (attempt_id, phase), not per attempt"


def test_practice_check_sixth_envelope_within_a_minute_is_429(
    loopback_client: TestClient, claimed_session: dict[str, Any]
) -> None:
    token = claimed_session[hop.TOKEN_KEY]

    statuses = [
        _post_check(loopback_client, _envelope(attempt_id=f"burst-{n}"), token=token).status_code
        for n in range(6)
    ]

    assert statuses == [200, 200, 200, 200, 200, 429], statuses


def test_practice_check_with_no_claimed_session_is_401(loopback_client: TestClient) -> None:
    """No state file, no token to compare against: nothing can be presented, nothing
    reaches a mentor."""
    response = _post_check(loopback_client, _envelope(), token="tok-anything")

    assert response.status_code in (401, 403), response.text


def test_practice_check_rejects_a_non_object_body_with_400(
    loopback_client: TestClient, claimed_session: dict[str, Any]
) -> None:
    response = loopback_client.post(
        ROUTE,
        content=b"[]",
        headers={
            hop.TOKEN_HEADER: claimed_session[hop.TOKEN_KEY],
            "Content-Type": "application/json",
        },
    )

    assert response.status_code == 400, response.text


# ---------------------------------------------------------------------------
# the route table (W3 verifies it; pinned here so the include line cannot be lost)
# ---------------------------------------------------------------------------


def test_the_module_routes_are_mounted_under_api() -> None:
    app = create_app(study_dirs=[])
    paths = {getattr(route, "path", None) for route in app.routes}

    assert "/api/modules/labs" in paths
    assert "/api/modules/labs/start" in paths
    assert "/api/modules/labs/cancel" in paths
    assert ROUTE in paths, "hop.ROUTE is the full path the CLI posts to"
    assert "/api/modules/practice-check" in paths, "the M0 Q2 loopback route, as the hop spells it"


# ---------------------------------------------------------------------------
# the module UAT rubric (W5) -- mechanism only, ungated: the file is pinned by hash
# ---------------------------------------------------------------------------


def test_the_module_uat_rubric_is_pinned_and_names_both_personas() -> None:
    from acceptance.uat.rubric import load_rubric  # pyright: ignore[reportMissingImports]

    data = Path(__file__).parent / "acceptance" / "uat" / "data"
    rubric = load_rubric(data / "module_rubric_v1.md", data / "module_rubric_registry.json")

    assert rubric.version == 1
    assert {c.id for c in rubric.criteria} >= {
        "labs_entry_discipline",
        "start_inside_one_session",
        "keyboard_and_cancel",
        "nothing_mentor_side_nothing_executed",
        "mentor_delivery",
        "contributor_path",
    }
    assert "Persona A" in rubric.body and "Persona B" in rubric.body
    assert any("mentorNotes" in reason for reason in rubric.reject_if)
    assert any("second study session" in reason for reason in rubric.reject_if)
