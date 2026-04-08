# ruff: noqa: N802, E501 — R01-R16 IDs are uppercase; embedded JS strings exceed 100 chars
"""Data-driven Playwright E2E tests for split-pane layout.

Autoagent-inspired closed-loop testing:
- Every requirement (R01-R16) maps to a verifier that produces binary pass/fail
- All DOM measurements are captured regardless of pass/fail
- results.json is written for agent consumption (no human in the loop)
- Tests use STUDYCTL_SESSION_DIR env var for full isolation (never touches real state)

Run:
    uv run pytest tests/test_split_pane_layout.py -v
    uv run pytest tests/test_split_pane_layout.py -v --headed   # watch in browser
    uv run pytest tests/test_split_pane_layout.py -v -k R01     # single requirement

Agent loop:
    1. Run tests -> read tests/results/split_pane_results.json
    2. Diagnose failures from measurements dict
    3. Modify CSS/JS
    4. Re-run tests
    5. If passed count improved -> keep; else -> discard
"""

from __future__ import annotations

import atexit
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

import pytest

pytest.importorskip("playwright")
pytest.importorskip("fastapi")
pytest.importorskip("uvicorn")

pytestmark = [pytest.mark.e2e]

WEB_PORT = 18572  # Unique port for this test suite (mock terminal tests)
WEB_PORT_TTYD = (
    18573  # Separate port for real-ttyd tests (avoids conflict with module-scoped server)
)
TTYD_TEST_PORT = 17682  # Unique ttyd port for real-terminal tests
RESULTS_DIR = Path(__file__).parent / "results"


# ===================================================================
# Results collector — accumulates per-requirement scores and writes
# results.json at session end for agent consumption.
# ===================================================================


class _ResultsCollector:
    """Accumulates per-requirement scores and measurements."""

    def __init__(self) -> None:
        self.scores: dict[str, float] = {}
        self.details: dict[str, str] = {}
        self.measurements: dict[str, dict] = {}

    def record(
        self, req_id: str, passed: bool, detail: str, measurements: dict | None = None
    ) -> None:
        self.scores[req_id] = 1.0 if passed else 0.0
        self.details[req_id] = detail
        if measurements:
            self.measurements[req_id] = measurements

    def write_json(self) -> Path:
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        passed = sum(1 for s in self.scores.values() if s == 1.0)
        failed = sum(1 for s in self.scores.values() if s == 0.0)
        failures = {k: self.details[k] for k, v in self.scores.items() if v == 0.0}
        result = {
            "timestamp": datetime.now(UTC).isoformat(),
            "total": len(self.scores),
            "passed": passed,
            "failed": failed,
            "scores": dict(sorted(self.scores.items())),
            "failures": dict(sorted(failures.items())),
            "measurements": self.measurements,
        }
        path = RESULTS_DIR / "split_pane_results.json"
        path.write_text(json.dumps(result, indent=2, default=str))
        return path


# Module-level collector instance
_collector = _ResultsCollector()


def _record(req_id: str, passed: bool, detail: str, measurements: dict | None = None) -> None:
    """Record a requirement result. Called by each test."""
    _collector.record(req_id, passed, detail, measurements)


# Write results.json when the module finishes (pytest_unconfigure not available
# without conftest.py, so we use atexit as a reliable fallback).
atexit.register(lambda: _collector.write_json() if _collector.scores else None)


# ===================================================================
# Test isolation — STUDYCTL_SESSION_DIR points to a temp directory.
# The web server subprocess inherits this env var, so both test code
# and server read/write IPC files in the temp dir.
# ===================================================================


@pytest.fixture(scope="module")
def isolated_session_dir(tmp_path_factory):
    """Create a temp directory for IPC state files. Sets env var for this process
    AND passes it to subprocesses via os.environ."""
    tmpdir = tmp_path_factory.mktemp("studyctl_ipc")
    old = os.environ.get("STUDYCTL_SESSION_DIR")
    os.environ["STUDYCTL_SESSION_DIR"] = str(tmpdir)

    # Force session_state module to pick up the new dir if already imported
    try:
        import studyctl.session_state as ss

        ss.SESSION_DIR = Path(str(tmpdir))
        ss.STATE_FILE = ss.SESSION_DIR / "session-state.json"
        ss.TOPICS_FILE = ss.SESSION_DIR / "session-topics.md"
        ss.PARKING_FILE = ss.SESSION_DIR / "session-parking.md"
        ss._LOCK_FILE = ss.SESSION_DIR / ".session-state.lock"
    except ImportError:
        pass

    yield tmpdir

    if old is None:
        os.environ.pop("STUDYCTL_SESSION_DIR", None)
    else:
        os.environ["STUDYCTL_SESSION_DIR"] = old


@pytest.fixture(autouse=True)
def _clean_ipc(isolated_session_dir):
    """Clean IPC files before/after each test — in the TEMP dir only."""
    state_file = isolated_session_dir / "session-state.json"
    topics_file = isolated_session_dir / "session-topics.md"
    parking_file = isolated_session_dir / "session-parking.md"
    for f in [state_file, topics_file, parking_file]:
        f.unlink(missing_ok=True)
    yield
    for f in [state_file, topics_file, parking_file]:
        f.unlink(missing_ok=True)


# ===================================================================
# Web server and Playwright fixtures
# ===================================================================


def _get_effective_credentials() -> tuple[str, str]:
    try:
        from studyctl.settings import load_settings

        settings = load_settings()
        return (settings.lan_username or "study", settings.lan_password or "")
    except Exception:
        return ("study", "")


_EFF_USER, _EFF_PASS = _get_effective_credentials()


def _start_web_server(port: int = WEB_PORT, ttyd_port: int = 0) -> subprocess.Popen:
    """Start web server subprocess. Inherits STUDYCTL_SESSION_DIR from env."""
    cmd = [sys.executable, "-m", "studyctl.cli", "web", "--port", str(port)]
    if ttyd_port:
        cmd.extend(["--ttyd-port", str(ttyd_port)])
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(30):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=1)
            return proc
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403):
                return proc
            time.sleep(0.3)
        except Exception:
            time.sleep(0.3)
    proc.kill()
    raise RuntimeError(f"Web server failed to start on port {port}")


@pytest.fixture(scope="module")
def web_server(isolated_session_dir):
    proc = _start_web_server()
    yield proc
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except Exception:
        proc.kill()
        proc.wait(timeout=5)


@pytest.fixture()
def web_page(web_server, browser):
    ctx_args: dict = {"viewport": {"width": 1280, "height": 800}}
    if _EFF_PASS:
        ctx_args["http_credentials"] = {"username": _EFF_USER, "password": _EFF_PASS}
    context = browser.new_context(**ctx_args)
    yield context.new_page()
    context.close()


# ===================================================================
# State helpers
# ===================================================================


def _write_state(data: dict, session_dir: Path) -> None:
    """Write session state JSON to the isolated temp dir."""
    session_dir.mkdir(parents=True, exist_ok=True)
    (session_dir / "session-state.json").write_text(json.dumps(data, indent=2))


def _setup_active_session(
    page, session_dir: Path, port: int = WEB_PORT, *, with_terminal: bool = False
) -> None:
    """Write session state and navigate to the study-session tab."""
    now = datetime.now(UTC).isoformat()
    state: dict = {
        "study_session_id": "test-split-pane",
        "topic": "Split Pane Test",
        "energy": 7,
        "mode": "focus",
        "started_at": now,
        "start_time": now,
    }
    if with_terminal:
        state["ttyd_port"] = 19999  # Dead port — "available" but not "connected"
    _write_state(state, session_dir)
    page.goto(f"http://127.0.0.1:{port}/#study-session")
    page.wait_for_load_state("load")
    page.wait_for_timeout(2000)  # Alpine + terminal health check init


# ===================================================================
# MEASUREMENT LAYER — single JS call captures all DOM metrics
# ===================================================================


_MEASURE_JS = """() => {
    // Find the visible split-container (study-session tab)
    const containers = document.querySelectorAll('.split-container');
    let container = null;
    for (const c of containers) {
        if (c.offsetHeight > 0) { container = c; break; }
    }
    if (!container) {
        return { error: 'No visible split-container found', container_height: 0 };
    }

    const cRect = container.getBoundingClientRect();
    const dash = container.querySelector('.split-dashboard');
    const gutter = container.querySelector('.gutter') || container.querySelector('.gutter-vertical');
    const term = container.querySelector('.split-terminal');

    const dRect = dash ? dash.getBoundingClientRect() : null;
    const gRect = gutter ? gutter.getBoundingClientRect() : null;
    const tRect = term ? term.getBoundingClientRect() : null;

    // Inner content heights (must match panel heights for resize to be visible)
    const dashContent = dash ? dash.querySelector('.session-dashboard') : null;
    const dashContentRect = dashContent ? dashContent.getBoundingClientRect() : null;

    // iframe state
    const iframe = container.querySelector('.terminal-iframe');
    const iframeVisible = iframe ? (iframe.offsetHeight > 0 && getComputedStyle(iframe).visibility !== 'hidden') : false;

    // Dashboard content fill (must match panel for resize to be visible)
    const dashContentHeight = dashContentRect ? dashContentRect.height : 0;
    const dashFillRatio = (dRect && dRect.height > 0 && dashContentRect)
        ? dashContentRect.height / dRect.height : 0;

    // Visibility flags
    const picker = document.querySelector('.session-start-picker');
    const unavailable = container.querySelector('.terminal-unavailable');

    return {
        // Container
        container_height: cRect.height,
        container_top: cRect.top,
        container_bottom: cRect.bottom,

        // Dashboard panel (Split.js controlled)
        dashboard_height: dRect ? dRect.height : 0,
        dashboard_top: dRect ? dRect.top : 0,
        dashboard_bottom: dRect ? dRect.bottom : 0,
        // Dashboard CONTENT (must fill panel for resize to be visible)
        dashboard_content_height: dashContentHeight,
        dashboard_fill_ratio: dashFillRatio,

        // Gutter
        gutter_height: gRect ? gRect.height : 0,
        gutter_top: gRect ? gRect.top : 0,
        gutter_bottom: gRect ? gRect.bottom : 0,

        // Terminal
        terminal_height: tRect ? tRect.height : 0,
        terminal_top: tRect ? tRect.top : 0,
        terminal_bottom: tRect ? tRect.bottom : 0,
        terminal_display: term ? getComputedStyle(term).display : 'none',

        // iframe
        iframe_src: iframe ? (iframe.getAttribute('src') || iframe.src || '') : '',
        iframe_height: iframe ? iframe.offsetHeight : 0,
        iframe_visible: iframeVisible,

        // Visibility flags
        split_container_visible: cRect.height > 0,
        start_picker_visible: picker ? (picker.offsetHeight > 0) : false,
        terminal_unavailable_visible: unavailable ? (unavailable.offsetHeight > 0) : false,

        // Flex direction (for swap)
        flex_direction: container.style.flexDirection || getComputedStyle(container).flexDirection,

        error: null,
    };
}"""


def _measure_all(page) -> dict:
    """Capture all DOM metrics in a single JS call. Always returns a dict."""
    return page.evaluate(_MEASURE_JS)


def _measure_picker_visibility(page) -> dict:
    """Measure visibility when no split container is expected."""
    return page.evaluate("""() => {
        const picker = document.querySelector('.session-start-picker');
        const containers = document.querySelectorAll('.split-container');
        const visibleSplits = Array.from(containers).filter(c => c.offsetHeight > 0).length;
        return {
            start_picker_visible: picker ? (picker.offsetHeight > 0) : false,
            visible_split_count: visibleSplits,
        };
    }""")


def _find_gutter_center(page) -> dict | None:
    """Find the center point of the visible gutter for drag operations."""
    return page.evaluate("""() => {
        const containers = document.querySelectorAll('.split-container');
        for (const c of containers) {
            if (c.offsetHeight > 0) {
                const g = c.querySelector('.gutter');
                if (g && g.offsetHeight > 0) {
                    const rect = g.getBoundingClientRect();
                    return { x: rect.x + rect.width / 2, y: rect.y + rect.height / 2 };
                }
            }
        }
        return null;
    }""")


def _drag_gutter(page, delta_y: int) -> None:
    """Drag the gutter by delta_y pixels."""
    pos = _find_gutter_center(page)
    if pos is None:
        return
    page.mouse.move(pos["x"], pos["y"])
    page.mouse.down()
    page.mouse.move(pos["x"], pos["y"] + delta_y, steps=10)
    page.mouse.up()
    page.wait_for_timeout(500)


# ===================================================================
# VERIFIER FUNCTIONS — pure, testable without a browser
# Each returns (passed: bool, detail: str)
# ===================================================================


def verify_R01(m: dict) -> tuple[bool, str]:
    """R01: Two panes fill 100% of vertical space (all have non-zero height)."""
    if m.get("error"):
        return False, f"No visible container: {m['error']}"
    ok = m["container_height"] > 0 and m["dashboard_height"] > 0 and m["terminal_height"] > 0
    detail = (
        f"container={m['container_height']:.0f}, "
        f"dashboard={m['dashboard_height']:.0f}, "
        f"terminal={m['terminal_height']:.0f}"
    )
    return ok, detail


def verify_R02(m: dict) -> tuple[bool, str]:
    """R02: No gap between dashboard top and container top."""
    if m.get("error"):
        return False, f"No visible container: {m['error']}"
    gap = abs(m["dashboard_top"] - m["container_top"])
    ok = gap < 2
    detail = f"dashboard_top={m['dashboard_top']:.1f}, container_top={m['container_top']:.1f}, gap={gap:.1f}px"
    return ok, detail


def verify_R03(m: dict) -> tuple[bool, str]:
    """R03: No gap between terminal bottom and container bottom."""
    if m.get("error"):
        return False, f"No visible container: {m['error']}"
    gap = abs(m["terminal_bottom"] - m["container_bottom"])
    ok = gap < 2
    detail = f"terminal_bottom={m['terminal_bottom']:.1f}, container_bottom={m['container_bottom']:.1f}, gap={gap:.1f}px"
    return ok, detail


def verify_R04(m: dict) -> tuple[bool, str]:
    """R04: Gutter sits precisely between dashboard and terminal (no gaps)."""
    if m.get("error"):
        return False, f"No visible container: {m['error']}"
    if m["gutter_height"] == 0:
        return False, "gutter_height=0 (Split.js gutter not created)"
    gap_above = abs(m["gutter_top"] - m["dashboard_bottom"])
    gap_below = abs(m["gutter_bottom"] - m["terminal_top"])
    ok = m["gutter_height"] > 0 and gap_above < 2 and gap_below < 2
    detail = (
        f"gutter_height={m['gutter_height']:.0f}, "
        f"gap_above={gap_above:.1f}px (gutter_top={m['gutter_top']:.1f}, dash_bottom={m['dashboard_bottom']:.1f}), "
        f"gap_below={gap_below:.1f}px (gutter_bottom={m['gutter_bottom']:.1f}, term_top={m['terminal_top']:.1f})"
    )
    return ok, detail


def verify_R05(m: dict) -> tuple[bool, str]:
    """R05: Dashboard + gutter + terminal heights sum to container height."""
    if m.get("error"):
        return False, f"No visible container: {m['error']}"
    total = m["dashboard_height"] + m["gutter_height"] + m["terminal_height"]
    diff = abs(total - m["container_height"])
    ok = diff < 2
    detail = (
        f"dashboard={m['dashboard_height']:.0f} + gutter={m['gutter_height']:.0f} "
        f"+ terminal={m['terminal_height']:.0f} = {total:.0f}, "
        f"container={m['container_height']:.0f}, diff={diff:.1f}px"
    )
    return ok, detail


def verify_R06(m_before: dict, m_after: dict, drag_delta: int) -> tuple[bool, str]:
    """R06: Drag down -> dashboard grows AND content fills the panel."""
    growth = m_after["dashboard_height"] - m_before["dashboard_height"]
    threshold = drag_delta * 0.8
    panel_grew = growth >= threshold
    # CRITICAL: content must fill the panel (fill ratio > 0.9)
    # Without this check, the panel grows but the user sees no visual change
    fill = m_after.get("dashboard_fill_ratio", 0)
    content_fills = fill > 0.9
    ok = panel_grew and content_fills
    detail = (
        f"dashboard: {m_before['dashboard_height']:.0f} -> {m_after['dashboard_height']:.0f} "
        f"(growth={growth:.0f}px, expected>={threshold:.0f}px), "
        f"content_fill={fill:.2f} ({'OK' if content_fills else 'CONTENT DOES NOT FILL PANEL'})"
    )
    return ok, detail


def verify_R07(m_before: dict, m_after: dict, drag_delta: int) -> tuple[bool, str]:
    """R07: Drag down -> terminal shrinks by at least 80% of drag delta."""
    shrink = m_before["terminal_height"] - m_after["terminal_height"]
    threshold = drag_delta * 0.8
    ok = shrink >= threshold
    detail = (
        f"terminal: {m_before['terminal_height']:.0f} -> {m_after['terminal_height']:.0f} "
        f"(shrink={shrink:.0f}px, expected>={threshold:.0f}px from {drag_delta}px drag)"
    )
    return ok, detail


def verify_R08(m_after: dict) -> tuple[bool, str]:
    """R08: After drag, panels still sum to container height (R05 still holds)."""
    return verify_R05(m_after)


def verify_R09(m: dict) -> tuple[bool, str]:
    """R09: After swap, terminal is above dashboard."""
    if m.get("error"):
        return False, f"No visible container: {m['error']}"
    ok = m["terminal_top"] < m["dashboard_top"]
    detail = (
        f"terminal_top={m['terminal_top']:.1f}, dashboard_top={m['dashboard_top']:.1f} "
        f"({'terminal above dashboard' if ok else 'dashboard still above terminal'})"
    )
    return ok, detail


def verify_R10_drag(m_before: dict, m_after: dict, drag_delta: int) -> tuple[bool, str]:
    """R10: After swap + drag, resize still works (R06-R08 hold)."""
    # After swap, "drag down" still means the gutter moves down on screen.
    # Dashboard is now below terminal, so dashboard shrinks and terminal grows.
    # But from Split.js perspective, the first element (dashboard in DOM) gets
    # the size change. With column-reverse, visual down = logical up.
    # We test that SOME panel changed by the expected amount.
    dash_delta = abs(m_after["dashboard_height"] - m_before["dashboard_height"])
    term_delta = abs(m_after["terminal_height"] - m_before["terminal_height"])
    max_delta = max(dash_delta, term_delta)
    threshold = abs(drag_delta) * 0.5  # Relaxed — swap may invert direction
    ok = max_delta >= threshold
    # Also verify sum is preserved
    total_after = (
        m_after["dashboard_height"] + m_after["gutter_height"] + m_after["terminal_height"]
    )
    sum_diff = abs(total_after - m_after["container_height"])
    sum_ok = sum_diff < 2
    ok = ok and sum_ok
    detail = (
        f"max panel change={max_delta:.0f}px (threshold={threshold:.0f}px), "
        f"sum_diff={sum_diff:.1f}px, "
        f"dashboard: {m_before['dashboard_height']:.0f}->{m_after['dashboard_height']:.0f}, "
        f"terminal: {m_before['terminal_height']:.0f}->{m_after['terminal_height']:.0f}"
    )
    return ok, detail


def verify_R11(m: dict) -> tuple[bool, str]:
    """R11: Terminal iframe has /terminal/ src and non-zero height."""
    has_src = "/terminal/" in m.get("iframe_src", "")
    has_height = m.get("iframe_height", 0) > 0
    ok = has_src and has_height
    detail = f"iframe_src='{m.get('iframe_src', '')}', iframe_height={m.get('iframe_height', 0)}"
    return ok, detail


def verify_R12(pane_content: str, marker: str) -> tuple[bool, str]:
    """R12: Terminal is interactive — command output appears in tmux pane."""
    ok = marker in pane_content
    detail = f"marker='{marker}', found={ok}, pane_length={len(pane_content)}"
    return ok, detail


def verify_R13(m: dict) -> tuple[bool, str]:
    """R13: Terminal shows 'unavailable' when ttyd is dead."""
    ok = m.get("terminal_unavailable_visible", False)
    detail = f"terminal_unavailable_visible={m.get('terminal_unavailable_visible')}"
    return ok, detail


def verify_R14(m: dict) -> tuple[bool, str]:
    """R14: Active session shows split layout."""
    ok = m.get("split_container_visible", False)
    detail = f"split_container_visible={ok}, container_height={m.get('container_height', 0)}"
    return ok, detail


def verify_R15(m: dict) -> tuple[bool, str]:
    """R15: Ended session shows start picker."""
    ok = m.get("start_picker_visible", False)
    detail = f"start_picker_visible={ok}"
    return ok, detail


def verify_R16(m: dict) -> tuple[bool, str]:
    """R16: No session state shows start picker."""
    ok = m.get("start_picker_visible", False)
    detail = f"start_picker_visible={ok}"
    return ok, detail


# ===================================================================
# Real ttyd fixtures — used by ALL layout/resize/swap tests (R01-R12)
# Testing without a real terminal produces false positives because
# the iframe content (xterm.js) affects layout behaviour.
# ===================================================================


@pytest.fixture()
def tmux_session():
    """Create a temporary tmux session for ttyd to attach to."""
    if not shutil.which("tmux"):
        pytest.skip("tmux not installed")
    session_name = "studyctl-test-split"
    subprocess.run(["tmux", "kill-session", "-t", session_name], capture_output=True, check=False)
    subprocess.run(["tmux", "new-session", "-d", "-s", session_name, "bash"], check=True)
    yield session_name
    subprocess.run(["tmux", "kill-session", "-t", session_name], capture_output=True, check=False)


@pytest.fixture()
def ttyd_process(tmux_session):
    """Start ttyd attached to the test tmux session."""
    if not shutil.which("ttyd"):
        pytest.skip("ttyd not installed")
    proc = subprocess.Popen(
        [
            "ttyd",
            "-W",
            "-i",
            "127.0.0.1",
            "-p",
            str(TTYD_TEST_PORT),
            "tmux",
            "attach",
            "-t",
            tmux_session,
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    for _ in range(20):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{TTYD_TEST_PORT}/", timeout=1)
            break
        except Exception:
            time.sleep(0.3)
    else:
        proc.kill()
        pytest.fail("ttyd failed to start")
    yield {"proc": proc, "port": TTYD_TEST_PORT, "session": tmux_session}
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except Exception:
        proc.kill()


@pytest.fixture()
def web_server_with_ttyd(isolated_session_dir, ttyd_process):
    """Web server configured to proxy to the test ttyd."""
    proc = _start_web_server(port=WEB_PORT_TTYD, ttyd_port=ttyd_process["port"])
    yield proc
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except Exception:
        proc.kill()
        proc.wait(timeout=5)


@pytest.fixture()
def web_page_ttyd(web_server_with_ttyd, browser, isolated_session_dir, ttyd_process):
    """Page with auth + session state pointing to real ttyd."""
    now = datetime.now(UTC).isoformat()
    _write_state(
        {
            "study_session_id": "test-real-ttyd",
            "topic": "Real Terminal Test",
            "energy": 7,
            "mode": "focus",
            "started_at": now,
            "start_time": now,
            "ttyd_port": ttyd_process["port"],
        },
        isolated_session_dir,
    )
    ctx_args: dict = {"viewport": {"width": 1280, "height": 800}}
    if _EFF_PASS:
        ctx_args["http_credentials"] = {"username": _EFF_USER, "password": _EFF_PASS}
    context = browser.new_context(**ctx_args)
    page = context.new_page()
    yield page
    context.close()


def _tmux_send(session_name: str, text: str) -> None:
    subprocess.run(["tmux", "send-keys", "-t", session_name, text, "Enter"], check=True)


def _tmux_capture(session_name: str) -> str:
    result = subprocess.run(
        ["tmux", "capture-pane", "-t", session_name, "-p"],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout


def _wait_for_split_with_terminal(page, port: int = WEB_PORT_TTYD) -> dict:
    """Navigate to study-session and wait for Split.js + iframe to fully load.
    Returns the measurements dict once both gutter and iframe are visible."""
    page.goto(f"http://127.0.0.1:{port}/#study-session")
    page.wait_for_load_state("load")
    m = {}
    for _ in range(30):
        page.wait_for_timeout(500)
        m = _measure_all(page)
        if m.get("gutter_height", 0) > 0 and m.get("iframe_height", 0) > 0:
            return m
    pytest.fail(
        f"Split layout with live terminal never appeared after 15s.\n"
        f"gutter_height={m.get('gutter_height', 0)}, "
        f"iframe_height={m.get('iframe_height', 0)}, "
        f"terminal_height={m.get('terminal_height', 0)}, "
        f"container_height={m.get('container_height', 0)}"
    )


# ===================================================================
# TESTS — Layout requirements R01-R05 (with REAL terminal)
# ===================================================================


class TestLayoutRequirements:
    """R01-R05: Static layout geometry with live terminal iframe loaded."""

    def test_R01_panels_fill_vertical_space(self, web_page_ttyd) -> None:
        m = _wait_for_split_with_terminal(web_page_ttyd)
        ok, detail = verify_R01(m)
        _record("R01", ok, detail, m)
        assert ok, f"R01 FAIL: {detail}"

    def test_R02_no_gap_at_top(self, web_page_ttyd) -> None:
        m = _wait_for_split_with_terminal(web_page_ttyd)
        ok, detail = verify_R02(m)
        _record("R02", ok, detail, m)
        assert ok, f"R02 FAIL: {detail}"

    def test_R03_no_gap_at_bottom(self, web_page_ttyd) -> None:
        m = _wait_for_split_with_terminal(web_page_ttyd)
        ok, detail = verify_R03(m)
        _record("R03", ok, detail, m)
        assert ok, f"R03 FAIL: {detail}"

    def test_R04_gutter_between_panels(self, web_page_ttyd) -> None:
        m = _wait_for_split_with_terminal(web_page_ttyd)
        ok, detail = verify_R04(m)
        _record("R04", ok, detail, m)
        assert ok, f"R04 FAIL: {detail}"

    def test_R05_panels_sum_to_container(self, web_page_ttyd) -> None:
        m = _wait_for_split_with_terminal(web_page_ttyd)
        ok, detail = verify_R05(m)
        _record("R05", ok, detail, m)
        assert ok, f"R05 FAIL: {detail}"


# ===================================================================
# TESTS — Resize requirements R06-R08 (with REAL terminal)
# ===================================================================


class TestResizeRequirements:
    """R06-R08: Drag-to-resize with live terminal iframe loaded."""

    def test_R06_drag_down_dashboard_grows(self, web_page_ttyd) -> None:
        m_before = _wait_for_split_with_terminal(web_page_ttyd)
        drag_delta = 100
        _drag_gutter(web_page_ttyd, drag_delta)
        m_after = _measure_all(web_page_ttyd)
        ok, detail = verify_R06(m_before, m_after, drag_delta)
        _record("R06", ok, detail, {"before": m_before, "after": m_after})
        assert ok, f"R06 FAIL: {detail}"

    def test_R07_drag_down_terminal_shrinks(self, web_page_ttyd) -> None:
        m_before = _wait_for_split_with_terminal(web_page_ttyd)
        drag_delta = 100
        _drag_gutter(web_page_ttyd, drag_delta)
        m_after = _measure_all(web_page_ttyd)
        ok, detail = verify_R07(m_before, m_after, drag_delta)
        _record("R07", ok, detail, {"before": m_before, "after": m_after})
        assert ok, f"R07 FAIL: {detail}"

    def test_R08_sum_preserved_after_drag(self, web_page_ttyd) -> None:
        _wait_for_split_with_terminal(web_page_ttyd)
        _drag_gutter(web_page_ttyd, 100)
        m_after = _measure_all(web_page_ttyd)
        ok, detail = verify_R08(m_after)
        _record("R08", ok, detail, m_after)
        assert ok, f"R08 FAIL: {detail}"


# ===================================================================
# TESTS — Swap requirements R09-R10 (with REAL terminal)
# ===================================================================


class TestSwapRequirements:
    """R09-R10: Swap panel order and verify resize still works, with live terminal."""

    def _click_swap(self, page) -> bool:
        """Click the swap button. Returns False if not found."""
        swap_btn = page.locator(".terminal-panel:visible .timer-btn[title*='Swap']")
        if not swap_btn.is_visible():
            return False
        swap_btn.click()
        page.wait_for_timeout(500)
        return True

    def test_R09_swap_reverses_panel_order(self, web_page_ttyd) -> None:
        _wait_for_split_with_terminal(web_page_ttyd)
        if not self._click_swap(web_page_ttyd):
            _record("R09", False, "Swap button not visible")
            pytest.skip("Swap button not visible")
        m = _measure_all(web_page_ttyd)
        ok, detail = verify_R09(m)
        _record("R09", ok, detail, m)
        assert ok, f"R09 FAIL: {detail}"

    def test_R10_resize_works_after_swap(self, web_page_ttyd) -> None:
        _wait_for_split_with_terminal(web_page_ttyd)
        if not self._click_swap(web_page_ttyd):
            _record("R10", False, "Swap button not visible")
            pytest.skip("Swap button not visible")
        m_before = _measure_all(web_page_ttyd)
        if m_before.get("gutter_height", 0) == 0:
            _record("R10", False, "No gutter after swap", m_before)
            pytest.fail("R10 FAIL: No gutter after swap")
        drag_delta = 80
        _drag_gutter(web_page_ttyd, drag_delta)
        m_after = _measure_all(web_page_ttyd)
        ok, detail = verify_R10_drag(m_before, m_after, drag_delta)
        _record("R10", ok, detail, {"before": m_before, "after": m_after})
        assert ok, f"R10 FAIL: {detail}"


# ===================================================================
# TESTS — Terminal requirements R11-R13
# ===================================================================


class TestTerminalRequirements:
    """R11-R13: Terminal iframe, interactivity, and unavailable state."""

    def test_R11_iframe_src_and_height(self, web_page_ttyd) -> None:
        """R11: Terminal iframe has /terminal/ src and non-zero height."""
        m = _wait_for_split_with_terminal(web_page_ttyd)
        ok, detail = verify_R11(m)
        _record("R11", ok, detail, m)
        assert ok, f"R11 FAIL: {detail}"

    def test_R12_terminal_interactive(self, web_page_ttyd, ttyd_process) -> None:
        session_name = ttyd_process["session"]
        web_page_ttyd.goto(f"http://127.0.0.1:{WEB_PORT_TTYD}/#study-session")
        web_page_ttyd.wait_for_load_state("load")

        # Wait for split + terminal to appear
        for _ in range(30):
            web_page_ttyd.wait_for_timeout(500)
            dims = _measure_all(web_page_ttyd)
            if dims.get("gutter_height", 0) > 0 and dims.get("terminal_height", 0) > 50:
                break
        else:
            _record("R12", False, f"Split layout never appeared: {dims}", dims)
            pytest.fail(f"R12 FAIL: Split layout never appeared: {dims}")

        # Send a unique marker command
        marker = "R12_DATA_DRIVEN_TEST_PASS"
        _tmux_send(session_name, f"echo {marker}")
        time.sleep(1)

        pane = _tmux_capture(session_name)
        ok, detail = verify_R12(pane, marker)
        _record("R12", ok, detail, {"pane_excerpt": pane[-500:], "marker": marker})
        assert ok, f"R12 FAIL: {detail}"


# ===================================================================
# TESTS — R13: Dead ttyd (uses mock, no real ttyd needed)
# ===================================================================


class TestDeadTerminal:
    """R13: Terminal unavailable state when ttyd is dead."""

    @pytest.mark.skip(
        reason="Requires real ttyd killed mid-test; mock server probe differs from real dead-ttyd behaviour"
    )
    def test_R13_unavailable_when_ttyd_dead(self, web_page, isolated_session_dir) -> None:
        _setup_active_session(web_page, isolated_session_dir, with_terminal=True)
        web_page.wait_for_timeout(12000)
        m = _measure_all(web_page)
        ok, detail = verify_R13(m)
        _record("R13", ok, detail, m)
        assert ok, f"R13 FAIL: {detail}"


# ===================================================================
# TESTS — Session lifecycle R14-R16 (uses mock, no real ttyd needed)
# ===================================================================


class TestSessionLifecycleRequirements:
    """R14-R16: Correct view based on session state."""

    def test_R14_active_session_shows_split(self, web_page, isolated_session_dir) -> None:
        _setup_active_session(web_page, isolated_session_dir, with_terminal=False)
        m = _measure_all(web_page)
        ok, detail = verify_R14(m)
        _record("R14", ok, detail, m)
        assert ok, f"R14 FAIL: {detail}"

    def test_R15_ended_session_shows_picker(self, web_page, isolated_session_dir) -> None:
        _write_state(
            {
                "study_session_id": "test-ended",
                "topic": "Ended",
                "energy": 5,
                "mode": "ended",
            },
            isolated_session_dir,
        )
        web_page.goto(f"http://127.0.0.1:{WEB_PORT}/#study-session")
        web_page.wait_for_load_state("load")
        web_page.wait_for_timeout(2000)
        m = _measure_picker_visibility(web_page)
        ok, detail = verify_R15(m)
        _record("R15", ok, detail, m)
        assert ok, f"R15 FAIL: {detail}"

    def test_R16_no_session_shows_picker(self, web_page, isolated_session_dir) -> None:
        web_page.goto(f"http://127.0.0.1:{WEB_PORT}/#study-session")
        web_page.wait_for_load_state("load")
        web_page.wait_for_timeout(2000)
        m = _measure_picker_visibility(web_page)
        ok, detail = verify_R16(m)
        _record("R16", ok, detail, m)
        assert ok, f"R16 FAIL: {detail}"


# ===================================================================
# TESTS — Alpine reactive stability (bonus: validates R05 survives ticks)
# ===================================================================


class TestAlpineStability:
    """Verify split layout survives Alpine.js reactive updates (pomodoro ticks)."""

    def test_layout_survives_pomodoro_ticks(self, web_page, isolated_session_dir) -> None:
        """Split.js styles must not be clobbered by Alpine reactive updates."""
        _setup_active_session(web_page, isolated_session_dir, with_terminal=True)
        m_before = _measure_all(web_page)
        if m_before.get("dashboard_height", 0) == 0:
            pytest.skip("Dashboard not rendered")

        # Start pomodoro — triggers Alpine reactive ticks every 1s
        web_page.evaluate("Alpine.store('pomodoro').start()")
        assert web_page.evaluate("Alpine.store('pomodoro').running"), "Pomodoro did not start"

        try:
            web_page.wait_for_timeout(3500)  # 3+ ticks
            m_after = _measure_all(web_page)

            height_diff = abs(m_after["dashboard_height"] - m_before["dashboard_height"])
            ok = height_diff < 5
            detail = (
                f"dashboard before={m_before['dashboard_height']:.0f}, "
                f"after={m_after['dashboard_height']:.0f}, diff={height_diff:.0f}px"
            )
            # Not a numbered requirement but record for diagnostics
            _record("ALPINE_STABILITY", ok, detail, {"before": m_before, "after": m_after})
            assert ok, f"Alpine clobber detected: {detail}"
        finally:
            web_page.evaluate("Alpine.store('pomodoro').stop()")

    def test_drag_position_survives_pomodoro_ticks(self, web_page, isolated_session_dir) -> None:
        """After dragging, the new position must survive Alpine reactive ticks."""
        _setup_active_session(web_page, isolated_session_dir, with_terminal=True)
        m_init = _measure_all(web_page)
        if m_init.get("gutter_height", 0) == 0:
            pytest.skip("No gutter — terminal not available")

        _drag_gutter(web_page, 80)
        m_after_drag = _measure_all(web_page)

        web_page.evaluate("Alpine.store('pomodoro').start()")
        assert web_page.evaluate("Alpine.store('pomodoro').running"), "Pomodoro did not start"

        try:
            web_page.wait_for_timeout(3500)
            m_after_ticks = _measure_all(web_page)

            drift = abs(m_after_ticks["dashboard_height"] - m_after_drag["dashboard_height"])
            ok = drift < 5
            detail = (
                f"after_drag={m_after_drag['dashboard_height']:.0f}, "
                f"after_ticks={m_after_ticks['dashboard_height']:.0f}, drift={drift:.0f}px"
            )
            _record(
                "DRAG_STABILITY",
                ok,
                detail,
                {"after_drag": m_after_drag, "after_ticks": m_after_ticks},
            )
            assert ok, f"Drag position lost after pomodoro ticks: {detail}"
        finally:
            web_page.evaluate("Alpine.store('pomodoro').stop()")
