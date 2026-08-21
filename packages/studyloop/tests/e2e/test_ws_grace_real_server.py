"""WS detach grace against a real server, a real PTY and a real agent process.

Companion to ``tests/test_session_ws_grace.py``. That module covers the
lifecycle logic and the route wiring in-process; four things cannot be proven
there and are proven here instead:

1. **Grace expiry actually fires.** The timer is an asyncio task. Under
   ``TestClient`` it lives on a per-socket blocking portal loop that is torn
   down when the with-block exits, so the timer never runs. A real uvicorn
   process has one long-lived loop, like production.
2. **The agent child is really reaped.** ``transport.end()`` closing an fd and
   waitpid-ing a pid is only meaningful against a real ``pty.fork()`` child.
   "No orphaned agent process" (a named risk in the handover) is a statement
   about the process table, so these assertions read the process table.
3. **The agent exiting while detached is a real signal**, not a flipped bool on
   a test double — here the child is killed out from under the server with no
   WebSocket attached, exactly as a crashing agent would be.
4. **Server shutdown during the grace window.** The timer dies with the loop, so
   without the lifespan hook the child would outlive the server that owns it.

These use ``STUDYLOOP_WS_GRACE_SECONDS`` to shorten the 90 s production window;
without it every case here would take a minute and a half.

Marked ``e2e`` (excluded from the default suite) because they spawn a server
subprocess and a real agent, and they skip without an editable install.
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

_tests_dir = str(Path(__file__).resolve().parent.parent)
if _tests_dir not in sys.path:
    sys.path.insert(0, _tests_dir)

from e2e._env import RunningServer, build_test_world, start_server  # noqa: E402

pytestmark = pytest.mark.e2e

pytest.importorskip("websockets")

from websockets.sync.client import connect as ws_connect  # noqa: E402

#: Grace window used by these tests. Long enough that "survives the window" is
#: a real wait, short enough that "expires" is testable.
GRACE_S = 3.0

AGENT_BINARY = "studyloop-fake-agent"
BANNER = b"FAKE-AGENT READY"


# ---------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _agent_pids() -> set[int]:
    """PIDs of every live fake-agent process.

    Read from the process table rather than tracked in-band on purpose: the
    ``Started`` event deliberately does not carry the pid, and "did the server
    leave an orphan behind" is a question about the OS, not about our bookkeeping.
    """
    result = subprocess.run(
        ["pgrep", "-f", AGENT_BINARY],
        capture_output=True,
        text=True,
        check=False,
    )
    return {int(line) for line in result.stdout.split() if line.strip().isdigit()}


class Server:
    """A real ``studyloop web`` process with isolated IPC state."""

    def __init__(self, root: Path, *, grace: float = GRACE_S) -> None:
        self.root = root
        self.port = _free_port()
        world = build_test_world(
            root,
            self.port,
            fake_agent=True,
            extra_env={
                "STUDYLOOP_WS_GRACE_SECONDS": str(grace),
                # Must tick INSIDE the shortened window, or the window always
                # expires first and the reaper never gets to notice a dead agent.
                "STUDYLOOP_REAP_INTERVAL_SECONDS": "0.5",
            },
        )
        self.running: RunningServer = start_server(world)
        self.session_dir = world.session_dir
        self.base = self.running.base_url

    # -- HTTP ---------------------------------------------------------------

    def post(self, path: str, payload: dict | None = None) -> tuple[int, dict]:
        data = json.dumps(payload).encode() if payload is not None else b""
        req = urllib.request.Request(
            f"{self.base}{path}",
            data=data,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=25) as resp:
                return resp.status, json.loads(resp.read() or b"{}")
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read() or b"{}")

    def state(self) -> dict:
        with urllib.request.urlopen(f"{self.base}/api/session/state", timeout=10) as resp:
            return json.loads(resp.read())

    # -- WS -----------------------------------------------------------------

    def ws(self, session_id: str):
        return ws_connect(
            f"ws://127.0.0.1:{self.port}/api/session/ws?study_session_id={session_id}",
            open_timeout=10,
            additional_headers={"Origin": self.base},
        )

    # -- lifecycle ----------------------------------------------------------

    def stop(self, *, graceful: bool = True) -> None:
        if self.running.proc.poll() is not None:
            return
        self.running.proc.terminate() if graceful else self.running.proc.kill()
        try:
            self.running.proc.wait(timeout=15)
        except subprocess.TimeoutExpired:  # pragma: no cover — defensive
            self.running.proc.kill()
            self.running.proc.wait(timeout=5)


def _await(predicate, what: str, timeout: float = 15.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.05)
    raise AssertionError(f"timed out waiting for {what}")


def _read_until(ws, marker: bytes, timeout: float = 15.0) -> bytes:
    """Drain frames until ``marker`` appears in the accumulated bytes."""
    buf = b""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            message = ws.recv(timeout=2)
        except TimeoutError:
            continue
        if isinstance(message, bytes):
            buf += message
        if marker in buf:
            return buf
    raise AssertionError(f"never saw {marker!r}; got {buf[-400:]!r}")


@pytest.fixture(autouse=True)
def _needs_editable_install() -> None:
    controlled_path = os.pathsep.join((str(Path(sys.prefix) / "bin"), os.defpath))
    if not shutil.which(AGENT_BINARY, path=controlled_path):
        pytest.skip(f"{AGENT_BINARY} not installed (editable install needed)")


@pytest.fixture()
def server(tmp_path: Path):
    srv = Server(tmp_path)
    baseline = _agent_pids()
    try:
        yield srv
    finally:
        # Teardown must not mask a test failure with its own noise.
        with contextlib.suppress(Exception):
            srv.post("/api/session/end")
        srv.stop()
        # Whatever the test asserted, never leak a child into the next test.
        for pid in _agent_pids() - baseline:
            with contextlib.suppress(ProcessLookupError):
                os.kill(pid, signal.SIGKILL)


def _start(server: Server, topic: str) -> str:
    status, body = server.post(
        "/api/session/start",
        {"topic": topic, "energy": 5, "agent": "fake", "transport": "pty"},
    )
    assert status == 201, (status, body)
    return body["study_session_id"]


# ---------------------------------------------------------------------------
# Cases
# ---------------------------------------------------------------------------


class TestGraceAgainstARealAgent:
    def test_disconnect_keeps_the_session_and_the_agent_process(self, server: Server) -> None:
        """Case 1, for real: closing the socket must not kill the child.

        This is the handover's reproduction script, inverted into an assertion.
        """
        before = _agent_pids()
        session_id = _start(server, "WS Grace Survives")
        with server.ws(session_id) as ws:
            _read_until(ws, BANNER)
        new_pids = _agent_pids() - before
        assert len(new_pids) == 1, f"expected one agent child, got {new_pids}"
        agent_pid = next(iter(new_pids))

        time.sleep(1.0)  # well inside the window, well past the old 0.4 s death
        assert server.state().get("study_session_id") == session_id, (
            "the session was destroyed by a plain WS close"
        )
        assert agent_pid in _agent_pids(), "the agent child was killed by a plain WS close"

    def test_reattach_inside_the_window_talks_to_the_same_agent(self, server: Server) -> None:
        """Case 2 + case 9's server half: same process, still answering.

        The strongest available proof that the *conversation* survived: the pid
        is unchanged and the same child answers a freshly typed line.
        """
        before = _agent_pids()
        session_id = _start(server, "WS Grace Reattach")
        with server.ws(session_id) as ws:
            _read_until(ws, BANNER)
        agent_pid = next(iter(_agent_pids() - before))

        with server.ws(session_id) as ws2:
            ws2.send(json.dumps({"type": "input", "data": "still there?\n"}))
            _read_until(ws2, b"FAKE-AGENT VERDICT:")

        assert server.state().get("study_session_id") == session_id
        assert agent_pid in _agent_pids(), "reattached to a different (or dead) agent"

    def test_window_expiry_releases_the_session_and_reaps_the_agent(self, server: Server) -> None:
        """Case 3 + the orphan-process risk: released, and nothing left running."""
        before = _agent_pids()
        session_id = _start(server, "WS Grace Expiry")
        with server.ws(session_id) as ws:
            _read_until(ws, BANNER)
        agent_pid = next(iter(_agent_pids() - before))

        _await(
            lambda: not server.state().get("study_session_id"),
            "the grace window to expire and release the session",
            timeout=GRACE_S + 10,
        )
        _await(lambda: agent_pid not in _agent_pids(), "the agent child to be reaped")

        state = server.state()
        assert state.get("last_release", {}).get("reason") == "grace_expired", state
        assert state["last_release"]["topic"] == "WS Grace Expiry"

    def test_agent_exit_while_detached_releases_without_waiting(self, server: Server) -> None:
        """Case 4 with a real death — the crux of the server change.

        A detached session has no consumer draining ``events()``, so ``Stopped``
        is never observed. If the timer only slept, this dead session would hold
        the single-session slot for the whole window and 409 the next start.
        Assert it goes *sooner* than the window, not merely eventually.
        """
        before = _agent_pids()
        session_id = _start(server, "WS Grace Agent Dies")
        with server.ws(session_id) as ws:
            _read_until(ws, BANNER)
        agent_pid = next(iter(_agent_pids() - before))

        os.kill(agent_pid, signal.SIGKILL)
        killed_at = time.monotonic()
        _await(
            lambda: not server.state().get("study_session_id"),
            "the dead session to be released",
            timeout=GRACE_S + 10,
        )
        elapsed = time.monotonic() - killed_at
        # Assert the MECHANISM, not the stopwatch. The old check was
        # `elapsed < GRACE_S` with GRACE_S == the window itself, so it had zero
        # margin: a poll that noticed at 2.9s passed and one at 3.1s failed, and
        # on a loaded machine that is a coin toss (measured: 1 fail / 2 pass at
        # load ~7.5). The reason field distinguishes the two outcomes this test
        # actually cares about — the liveness poll noticing the agent died
        # ("agent_exited") versus the timer simply running out ("grace_expired")
        # — and no amount of CPU contention can blur them.
        release = server.state().get("last_release") or {}
        assert release.get("reason") == "agent_exited", (
            f"released after {elapsed:.1f}s for reason {release.get('reason')!r} — "
            "expected 'agent_exited', meaning the liveness poll noticed the agent "
            "had gone. 'grace_expired' means it did not and the window merely ran out."
        )
        # Generous upper bound so a pathologically slow release still fails,
        # without re-introducing a race at the window boundary.
        assert elapsed < GRACE_S + 8, f"release took {elapsed:.1f}s, far too slow"

        # And the freed slot is immediately usable.
        status, _ = server.post(
            "/api/session/start",
            {"topic": "Next One", "energy": 5, "agent": "fake", "transport": "pty"},
        )
        assert status == 201, "slot still pinned after the agent died"

    def test_start_during_the_window_is_refused_with_a_reattach_hint(self, server: Server) -> None:
        """Case 6: a clear refusal beats silently pre-empting a live agent."""
        session_id = _start(server, "WS Grace Conflict")
        with server.ws(session_id) as ws:
            _read_until(ws, BANNER)

        status, body = server.post(
            "/api/session/start",
            {"topic": "Something Else", "energy": 5, "agent": "fake", "transport": "pty"},
        )
        assert status == 409, (status, body)
        assert "WS Grace Conflict" in body["error"], body
        assert body["study_session_id"] == session_id
        assert body["reattach_url"].endswith(session_id)

    def test_end_during_the_window_releases_at_once(self, server: Server) -> None:
        """Case 5: explicit end beats the timer and leaves no orphan child."""
        before = _agent_pids()
        session_id = _start(server, "WS Grace Explicit End")
        with server.ws(session_id) as ws:
            _read_until(ws, BANNER)
        agent_pid = next(iter(_agent_pids() - before))

        status, _ = server.post("/api/session/end")
        assert status == 200
        assert not server.state().get("study_session_id")
        _await(lambda: agent_pid not in _agent_pids(), "the agent child to be reaped on end")

    def test_end_then_start_gets_a_working_socket(self, server: Server) -> None:
        """The consumer-slot leak: "refresh → End → Start" used to 403.

        The claim on the event stream was freed only by the WS route's
        ``finally``, so the next session's first WebSocket could be refused by a
        claim belonging to a session that no longer existed. Freeing the slot
        with the session is what fixes it — and a handshake failure here is
        exactly what a learner saw as a terminal stuck on "Starting".
        """
        first = _start(server, "WS Grace First")
        with server.ws(first) as ws:
            _read_until(ws, BANNER)  # detach without ending: grace window open

        assert server.post("/api/session/end")[0] == 200

        second = _start(server, "WS Grace Second")
        assert second != first
        with server.ws(second) as ws:
            _read_until(ws, BANNER)

    def test_second_socket_takes_over_and_gets_the_whole_stream(self, server: Server) -> None:
        """Case 7 for real. Was: output SPLIT between two sockets, both wrong.

        ``events()`` is a drain, so each event went to exactly one consumer.
        Now the newer socket owns the stream and the displaced one is told why.
        """
        session_id = _start(server, "WS Grace Two Tabs")
        with server.ws(session_id) as ws_a:
            _read_until(ws_a, BANNER)

            with server.ws(session_id) as ws_b:
                # A is told where its session went.
                notice = None
                deadline = time.monotonic() + 10
                while time.monotonic() < deadline and notice is None:
                    try:
                        message = ws_a.recv(timeout=2)
                    except TimeoutError:
                        continue
                    except Exception:
                        break
                    if isinstance(message, str) and "attach_superseded" in message:
                        notice = json.loads(message)
                assert notice is not None, "displaced socket was never told it lost the stream"
                assert notice["reason"] == "taken_over"

                # B owns the stream whole: its own echo comes back intact.
                ws_b.send(json.dumps({"type": "input", "data": "who has me?\n"}))
                buf = _read_until(ws_b, b"FAKE-AGENT VERDICT:")
                assert b"who has me?" in buf, (
                    "B received a partial stream — output is still being split"
                )

        assert server.state().get("study_session_id") == session_id, (
            "a takeover must not end the session"
        )


class TestServerShutdown:
    def test_shutdown_during_the_window_leaves_no_orphan_agent(self, tmp_path: Path) -> None:
        """Case 8: the grace timer dies with the loop; the child must not survive.

        Owns its server rather than using the fixture, because the assertion is
        about what the *stop* leaves behind.
        """
        if not shutil.which(AGENT_BINARY):
            pytest.skip(f"{AGENT_BINARY} not installed (editable install needed)")

        before = _agent_pids()
        srv = Server(tmp_path, grace=300.0)  # long window: only shutdown can free it
        try:
            session_id = _start(srv, "WS Grace Shutdown")
            with srv.ws(session_id) as ws:
                _read_until(ws, BANNER)
            agent_pid = next(iter(_agent_pids() - before))
            assert agent_pid in _agent_pids()

            srv.stop()  # SIGTERM → uvicorn lifespan shutdown

            _await(
                lambda: agent_pid not in _agent_pids(),
                "the agent child to be reaped by the shutdown hook",
                timeout=20,
            )
        finally:
            srv.stop(graceful=False)
            for pid in _agent_pids() - before:
                with contextlib.suppress(ProcessLookupError):
                    os.kill(pid, signal.SIGKILL)
