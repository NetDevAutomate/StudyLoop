"""``studyloop drill <setup|check|cleanup> <module>/<deck>/<task>`` end to end (lane R, R6).

Drives the exported ``drill_group`` with ``CliRunner`` (it is registered in ``cli/__init__.py``
by lane W in wave 2, so nothing here goes through the top-level ``studyloop`` command) against
the offline fixture module under ``tests/fixtures/modules/runner-offline/`` -- the shape
``studyloop module new`` produces, hand-written because lane C's scaffold had not merged when
R6 was built. Lane C's store is the other seam: ``_drill.locate_installed_module`` is pointed
at the fixture for each test.

What the spec scenarios need proven here: the three phases exit 0 with no Docker, kind or
network; consent is asked every time and there is no ``--yes``; a failing cleanup still
closes the attempt; the outcome line is one of ``Mentor told.`` / ``Mentor not told:
<reason>``; a shell token is refused before spawn; and a check records a ``practice_check``
event and nothing else.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import shutil
import sqlite3
import threading
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from click.testing import CliRunner
from test_module_runner import LEARNER_HISTORY_TABLES, SpawnCall, _table_rows, spawn_spy
from test_practice_verify import _attempt_db, _patch_db

from studyloop import session_state
from studyloop.cli import _drill
from studyloop.cli._drill import drill_group
from studyloop.modules import hop
from studyloop.modules.attempt import AttemptStore, DrillIdentity, InstalledModule

if TYPE_CHECKING:
    from collections.abc import Iterator

__all__ = ["spawn_spy"]  # re-exported pytest fixture from test_module_runner

FIXTURE_MODULE = Path(__file__).parent / "fixtures" / "modules" / "runner-offline"
MODULE_ID = "runner-offline"
DRILL_REF = f"{MODULE_ID}/offline/echo-check"


def _module_digest(root: Path) -> str:
    """sha256 over sorted relative paths + bytes -- the lockfile rule in lane C's brief."""
    digest = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        digest.update(str(path.relative_to(root)).encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _install(monkeypatch: pytest.MonkeyPatch, snapshot: Path) -> DrillIdentity:
    """Point the CLI's module locator at ``snapshot`` as the installed ``runner-offline``."""
    digest = _module_digest(snapshot)

    def locate(module_id: str) -> InstalledModule:
        if module_id != MODULE_ID:
            raise _drill.ModuleNotInstalledError(module_id)
        return InstalledModule(module_id=MODULE_ID, module_digest=digest, snapshot_dir=snapshot)

    monkeypatch.setattr(_drill, "locate_installed_module", locate)
    return DrillIdentity(
        module_id=MODULE_ID, module_digest=digest, deck_id="offline", task_id="echo-check"
    )


@pytest.fixture
def sessions_db(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    db = _attempt_db(tmp_path)
    _patch_db(monkeypatch, db)
    return db


@pytest.fixture
def installed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> DrillIdentity:
    """The fixture module copied to ``tmp_path`` (so a test may edit it) and 'installed'."""
    snapshot = tmp_path / "snapshot"
    shutil.copytree(FIXTURE_MODULE, snapshot)
    for script in (snapshot / "scripts").iterdir():
        script.chmod(0o755)
    # Attempts live under the learner's state dir in production; here each test gets its own.
    monkeypatch.setattr(_drill, "attempts_root", lambda: tmp_path / "module-attempts")
    return _install(monkeypatch, snapshot)


def _invoke(*args: str, confirm: str = "y") -> Any:
    return CliRunner().invoke(drill_group, list(args), input=f"{confirm}\n", catch_exceptions=False)


def _events(db: Path) -> list[sqlite3.Row]:
    """Rows of ``practice_check_events``; ``[]`` when no phase ever ran (table not yet created)."""
    with contextlib.closing(sqlite3.connect(db)) as conn:
        conn.row_factory = sqlite3.Row
        if not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='practice_check_events'"
        ).fetchone():
            return []
        return conn.execute("SELECT * FROM practice_check_events ORDER BY id").fetchall()


def _history(db: Path) -> dict[str, int]:
    return {table: _table_rows(db, table) for table in LEARNER_HISTORY_TABLES}


# ---------------------------------------------------------------------------
# Fake loopback route (lane W's, wave 2) -- records what the hop sent
# ---------------------------------------------------------------------------


@dataclass
class FakeRoute:
    status: int = 200
    body: bytes = b'{"status": "delivered"}'
    requests: list[dict[str, Any]] = field(default_factory=list)
    port: int = 0


@pytest.fixture
def fake_route() -> Iterator[FakeRoute]:
    route = FakeRoute()

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length)
            route.requests.append(
                {
                    "path": self.path,
                    "headers": {key.lower(): value for key, value in self.headers.items()},
                    "json": json.loads(raw),
                }
            )
            self.send_response(route.status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(route.body)))
            self.end_headers()
            self.wfile.write(route.body)

        def log_message(self, *_args: Any) -> None:
            return

    server = HTTPServer(("127.0.0.1", 0), Handler)
    route.port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield route
    finally:
        server.shutdown()
        server.server_close()


def _claim_session(port: int, token: str = "cap-token-for-tests") -> None:
    """What lane W's web process will do at claim: port + token + session id in the state file."""
    session_state.write_session_state(
        {"study_session_id": "sess-1", "mode": "active", hop.PORT_KEY: port, hop.TOKEN_KEY: token}
    )


# ---------------------------------------------------------------------------
# The spec scenarios
# ---------------------------------------------------------------------------


def test_scaffold_offline_drill_runs_setup_check_cleanup_end_to_end(
    installed: DrillIdentity, sessions_db: Path, spawn_spy: list[SpawnCall]
) -> None:
    """Spec: GIVEN the module ``studyloop module new`` produces, installed -- WHEN ``drill
    setup``, ``drill check`` and ``drill cleanup`` run with consent -- THEN each exits 0
    without Docker, kind or network. Plus: one ``practice_check`` row per phase, learner
    history untouched, the attempt closed by cleanup, every spawn an argv list with
    ``shell=False`` whose executable is one of the fixture's three scripts."""
    history_before = _history(sessions_db)
    store = AttemptStore(root=_drill.attempts_root())

    setup = _invoke("setup", DRILL_REF)
    assert setup.exit_code == 0, setup.output
    assert "setup passed (exit 0)" in setup.output
    assert "Mentor not told: no_active_session" in setup.output
    attempt = store.current(installed)
    assert attempt is not None, "setup must leave the attempt open for check"
    assert (attempt.attempt_dir / "hello.txt").read_text(encoding="utf-8") == "hello\n"

    check = _invoke("check", DRILL_REF)
    assert check.exit_code == 0, check.output
    assert "check passed (exit 0)" in check.output
    assert "hello.txt says hello" in check.output
    assert store.current(installed) == attempt, "check runs in the attempt setup opened"

    cleanup = _invoke("cleanup", DRILL_REF)
    assert cleanup.exit_code == 0, cleanup.output
    assert "cleanup passed (exit 0)" in cleanup.output
    assert store.current(installed) is None, "cleanup closes the attempt"
    assert not (attempt.attempt_dir / "hello.txt").exists()

    rows = _events(sessions_db)
    assert [row["phase"] for row in rows] == ["setup", "check", "cleanup"]
    assert {row["exit_class"] for row in rows} == {"passed"}
    assert {row["attempt_id"] for row in rows} == {attempt.attempt_id}
    assert {row["delivery_status"] for row in rows} == {"no_active_session"}
    assert _history(sessions_db) == history_before, "a drill must not touch learner history"

    assert len(spawn_spy) == 3
    executables = []
    for call in spawn_spy:
        assert call.kwargs.get("shell", False) is False
        assert isinstance(call.args, list)
        executables.append(Path(call.args[0]).name)
        assert Path(call.kwargs["cwd"]).resolve() == attempt.attempt_dir.resolve()
        env = call.kwargs["env"]
        assert env["PATH"] == "/usr/local/bin:/usr/bin:/bin"
        assert "DOCKER_HOST" not in env and "KUBECONFIG" not in env
    assert executables == ["setup.sh", "check.sh", "cleanup.sh"]
    assert spawn_spy[1].args[1:] == ["hello.txt"], "literal argument passed as its own element"


def test_every_phase_asks_for_consent_and_declining_runs_nothing(
    installed: DrillIdentity, sessions_db: Path, spawn_spy: list[SpawnCall]
) -> None:
    """§5.5 *Consent*: per phase, per execution, shown then confirmed. Declining exits 2,
    spawns nothing, records nothing, and (for setup) leaves no open attempt behind."""
    result = _invoke("setup", DRILL_REF, confirm="n")

    assert result.exit_code == 2, result.output
    assert "Not confirmed" in result.output
    assert "Drill phase: setup" in result.output
    assert "Script sha256:" in result.output
    assert "scripts/setup.sh" in result.output
    assert spawn_spy == []
    assert _events(sessions_db) == []
    assert AttemptStore(root=_drill.attempts_root()).current(installed) is None


@pytest.mark.parametrize("phase", ["setup", "check", "cleanup"])
def test_drill_has_no_yes_flag(phase: str) -> None:
    """The CLI never bypasses consent: ``--yes`` does not exist on any phase (M0, §5.5)."""
    help_result = CliRunner().invoke(drill_group, [phase, "--help"])
    assert help_result.exit_code == 0
    assert "--yes" not in help_result.output

    result = CliRunner().invoke(drill_group, [phase, "--yes", DRILL_REF])
    assert result.exit_code == 2
    assert "No such option" in result.output and "--yes" in result.output


def test_check_exit_1_is_task_not_complete_and_recorded_as_failed(
    installed: DrillIdentity, sessions_db: Path
) -> None:
    """§5.5 *Exit codes*: check ``1`` = failed, task not complete -- the CLI exits 1, says so,
    and the ``practice_check`` row carries ``failed``. (No setup ran, so ``hello.txt`` is
    missing and the fixture's check script exits 1.)"""
    result = _invoke("check", DRILL_REF)

    assert result.exit_code == 1, result.output
    assert "task not complete (exit 1)" in result.output
    assert "missing or does not say hello" in result.output
    rows = _events(sessions_db)
    assert len(rows) == 1
    assert rows[0]["exit_class"] == "failed"
    assert rows[0]["exit_code"] == 1


def test_failing_cleanup_still_closes_the_attempt(
    installed: DrillIdentity, sessions_db: Path, tmp_path: Path
) -> None:
    """Spec scenario: GIVEN a cleanup script that exits 3 -- WHEN the cleanup phase runs with
    consent -- THEN the phase is classed as an error, the message is shown to the learner,
    and the attempt is closed."""
    cleanup = tmp_path / "snapshot" / "scripts" / "cleanup.sh"
    cleanup.write_text(
        "#!/bin/sh\necho 'could not remove the thing' >&2\nexit 3\n", encoding="utf-8"
    )
    store = AttemptStore(root=_drill.attempts_root())
    assert _invoke("setup", DRILL_REF).exit_code == 0
    attempt = store.current(installed)
    assert attempt is not None

    result = _invoke("cleanup", DRILL_REF)

    assert result.exit_code == 2, result.output
    assert "cleanup failed (exit 3; error)" in result.output
    assert "could not remove the thing" in result.output
    assert store.current(installed) is None, "a failed cleanup must still close the attempt"
    rows = _events(sessions_db)
    assert rows[-1]["phase"] == "cleanup"
    assert rows[-1]["exit_class"] == "error"
    assert rows[-1]["exit_code"] == 3


def test_failed_setup_does_not_start_an_attempt(
    installed: DrillIdentity, sessions_db: Path, tmp_path: Path
) -> None:
    """§5.5: setup non-zero = error, attempt not started -- so a second setup is possible."""
    setup = tmp_path / "snapshot" / "scripts" / "setup.sh"
    setup.write_text("#!/bin/sh\necho 'no cluster today' >&2\nexit 1\n", encoding="utf-8")
    store = AttemptStore(root=_drill.attempts_root())

    result = _invoke("setup", DRILL_REF)

    assert result.exit_code == 2, result.output
    assert "setup failed (exit 1; error) -- attempt not started" in result.output
    assert store.current(installed) is None
    assert _events(sessions_db)[0]["exit_class"] == "error"


def test_shell_token_in_a_deck_command_is_refused_before_spawn(
    installed: DrillIdentity, sessions_db: Path, tmp_path: Path, spawn_spy: list[SpawnCall]
) -> None:
    """Spec scenario: GIVEN a check phase whose argv contains ``;`` -- WHEN ``drill check``
    runs -- THEN it refuses before spawning and names the token. Consent is never even
    asked for a command the runner would refuse."""
    deck_path = tmp_path / "snapshot" / "decks" / "offline.json"
    deck = json.loads(deck_path.read_text(encoding="utf-8"))
    deck["tasks"][0]["verification"]["command"] = "scripts/check.sh hello.txt; touch pwned"
    deck_path.write_text(json.dumps(deck), encoding="utf-8")

    result = _invoke("check", DRILL_REF)

    assert result.exit_code == 1, result.output
    assert "';'" in result.output or ";" in result.output
    assert "MC015" in result.output
    assert "Run this phase now?" not in result.output
    assert spawn_spy == []
    assert _events(sessions_db) == []


def test_regular_file_outside_scripts_is_refused_after_consent_before_spawn(
    installed: DrillIdentity, sessions_db: Path, tmp_path: Path, spawn_spy: list[SpawnCall]
) -> None:
    """Spec scenario: GIVEN a check phase naming ``decks/helper.sh`` -- THEN it is refused
    before spawn (MC013 at runtime) naming the path."""
    snapshot = tmp_path / "snapshot"
    helper = snapshot / "decks" / "helper.sh"
    helper.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    helper.chmod(0o755)
    deck_path = snapshot / "decks" / "offline.json"
    deck = json.loads(deck_path.read_text(encoding="utf-8"))
    deck["tasks"][0]["verification"]["command"] = "decks/helper.sh"
    deck_path.write_text(json.dumps(deck), encoding="utf-8")

    result = _invoke("check", DRILL_REF)

    assert result.exit_code == 1, result.output
    assert "decks/helper.sh" in result.output
    assert "MC013" in result.output
    assert spawn_spy == []


def test_mentor_told_when_the_loopback_route_accepts_the_typed_fields(
    installed: DrillIdentity, sessions_db: Path, fake_route: FakeRoute
) -> None:
    """M0 Q2: the CLI reads port + token from the session state file, posts typed fields with
    the token in a header to the loopback route, prints ``Mentor told.`` on success and
    records ``delivered`` on the row. The fields are the ones ``hop.py`` documents."""
    _claim_session(fake_route.port)

    result = _invoke("check", DRILL_REF)

    assert "Mentor told." in result.output
    assert len(fake_route.requests) == 1
    request = fake_route.requests[0]
    assert request["path"] == hop.ROUTE
    assert request["headers"][hop.TOKEN_HEADER.lower()] == "cap-token-for-tests"
    assert request["headers"]["content-type"] == "application/json"
    fields = request["json"]
    assert set(fields) == {
        "session_id",
        "module_id",
        "module_digest",
        "deck_id",
        "task_id",
        "attempt_id",
        "phase",
        "exit_class",
        "exit_code",
        "duration_seconds",
        "timed_out",
        "truncated",
        "cap_hit",
        "message",
        "stdout_tail",
        "stderr_tail",
        "triggered_by",
    }
    assert fields["session_id"] == "sess-1"
    assert fields["module_id"] == MODULE_ID
    assert fields["module_digest"] == installed.module_digest
    assert (fields["deck_id"], fields["task_id"]) == ("offline", "echo-check")
    assert fields["phase"] == "check"
    assert fields["exit_class"] == "failed"  # no setup ran: hello.txt is missing
    assert fields["exit_code"] == 1
    assert fields["triggered_by"] == "learner"
    assert "does not say hello" in fields["stdout_tail"]
    rows = _events(sessions_db)
    assert rows[0]["delivery_status"] == "delivered"
    assert rows[0]["attempt_id"] == fields["attempt_id"]


def test_mentor_not_told_when_nothing_listens_or_no_session(
    installed: DrillIdentity, sessions_db: Path
) -> None:
    """Spec scenario: no session state file, or no web process listening, is learner-visible
    as ``Mentor not told: no_active_session`` and recorded as such."""
    # (a) no state file at all -> the CLI's exact outcome line
    result = _invoke("check", DRILL_REF)
    assert "Mentor not told: no_active_session" in result.output
    rows = _events(sessions_db)
    assert rows[0]["delivery_status"] == "no_active_session"

    # (b) a state file naming a port nobody listens on -> connection refused -> same outcome
    outcome = hop.post_check_result(
        {"phase": "check"},
        state={"study_session_id": "sess-1", hop.PORT_KEY: _free_port(), hop.TOKEN_KEY: "t"},
        timeout_seconds=2,
    )
    assert outcome.status == "no_active_session"
    assert "refused" in outcome.reason

    # (c) a state file without the capability token -> nothing to present -> same outcome
    outcome = hop.post_check_result(
        {"phase": "check"}, state={"study_session_id": "sess-1", hop.PORT_KEY: 1}, timeout_seconds=2
    )
    assert outcome.status == "no_active_session"


def test_mentor_not_told_error_when_the_route_rejects(
    installed: DrillIdentity, sessions_db: Path, fake_route: FakeRoute
) -> None:
    """A non-2xx reply (here 401: wrong token) is ``error`` to the learner, never silent."""
    fake_route.status = 401
    fake_route.body = b'{"detail": "no token"}'
    _claim_session(fake_route.port)

    result = _invoke("check", DRILL_REF)

    assert "Mentor not told: error" in result.output
    assert "http 401" in result.output
    assert _events(sessions_db)[0]["delivery_status"] == "error"
    assert _events(sessions_db)[0]["delivery_reason"] == "http 401"


def test_server_reported_outcome_is_relayed_verbatim(
    installed: DrillIdentity, sessions_db: Path, fake_route: FakeRoute
) -> None:
    """The server owns the delivery outcome: a 2xx body naming one of the six states is what
    the learner sees (``transport_closed`` here), not a client-side guess."""
    fake_route.body = b'{"status": "transport_closed", "reason": "pty master closed"}'
    _claim_session(fake_route.port)

    result = _invoke("check", DRILL_REF)

    assert "Mentor not told: transport_closed" in result.output
    assert _events(sessions_db)[0]["delivery_status"] == "transport_closed"
    assert _events(sessions_db)[0]["delivery_reason"] == "pty master closed"


@pytest.mark.parametrize(
    "ref",
    ["runner-offline", "runner-offline/offline", "a/b/c/d", "Runner-Offline/offline/echo-check"],
)
def test_drill_ref_must_be_three_slugs(installed: DrillIdentity, ref: str) -> None:
    result = CliRunner().invoke(drill_group, ["check", ref], input="y\n")
    assert result.exit_code == 2, result.output
    assert "<module>/<deck>/<task>" in result.output


def test_unknown_module_deck_or_task_is_a_clear_error(installed: DrillIdentity) -> None:
    for ref, needle in [
        ("other-module/offline/echo-check", "not installed"),
        (f"{MODULE_ID}/nope/echo-check", "no deck"),
        (f"{MODULE_ID}/offline/nope", "no task"),
    ]:
        result = CliRunner().invoke(drill_group, ["check", ref], input="y\n")
        assert result.exit_code == 1, result.output
        assert needle in result.output, result.output


def test_task_without_the_phase_is_refused(installed: DrillIdentity, tmp_path: Path) -> None:
    deck_path = tmp_path / "snapshot" / "decks" / "offline.json"
    deck = json.loads(deck_path.read_text(encoding="utf-8"))
    del deck["tasks"][0]["verification"]["cleanupCommand"]
    deck_path.write_text(json.dumps(deck), encoding="utf-8")

    result = _invoke("cleanup", DRILL_REF)

    assert result.exit_code == 1, result.output
    assert "declares no cleanup phase" in result.output


def _free_port() -> int:
    import socket

    with contextlib.closing(socket.socket()) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]
