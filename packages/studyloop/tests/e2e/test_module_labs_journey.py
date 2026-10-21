"""Labs journey (module-contract v1, lane W4): list -> start inside the one claimed session ->
keyboard -> reload re-attaches -> cancel -> the check reaches the mentor -> `module remove` ->
Labs gone. Real server, real Alpine, the real CLI in subprocesses, the deterministic harness
agent -- no stubbed selectors, no mocked fetches.

  Phase 1  With no module installed there is NO Labs entry (web-ui spec scenario 1) and no
           prerequisite text anywhere on the page (Persona A step 1, design.md §6)
  Phase 2  `studyloop module add` twice (the two fixture modules); reload; exactly one Labs
           entry; the view lists decks and tasks BY ID AND PROMPT, grouped by module, and the
           DOM carries none of hint / solution / mentorNotes (scenarios 2-3, C7)
  Phase 3  Start a drill: the Study Session console mounts (the mentor pane), the state file
           names the drill (`labs_drill`), the view that owns the session (`origin: study`)
           and the capability the hop needs (`practice_check_token` beside `web_port`); only
           ONE console mounted; nothing executed
  Phase 4  Keyboard: Tab / Shift-Tab traverse the Labs controls, with the focus visible
  Phase 5  Reload re-attaches: same study_session_id, one console, the live drill restored
  Phase 6  Cancel (Escape): the drill is dropped, the session is exactly where it was
  Phase 7  `studyloop drill check` (consent typed into the CLI) -> `Mentor told.` -> the
           mentor pane shows the delivered block, sentinel to sentinel, tail lines `| `-prefixed;
           a replay of the same (attempt, phase) is refused with 409 (session-transports spec)
  Phase 8  `studyloop module remove` x2; reload; Labs is gone

Ordering note (deviation from the W2 brief's list): the brief puts "the mentor pane shows the
delivered block" right after start. The harness agent answers ONE generic question and exits
after any delivered text, so the delivery is the last live-session step here; cancel, reload
and keyboard come first. Phase content is unchanged.

Run:  just e2e packages/studyloop/tests/e2e/test_module_labs_journey.py
"""

from __future__ import annotations

import contextlib
import json
import socket
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

pytest.importorskip("playwright")

_tests_dir = str(Path(__file__).resolve().parent.parent)
if _tests_dir not in sys.path:
    sys.path.insert(0, _tests_dir)

from _playwright_helpers import server_opener  # noqa: E402
from _playwright_paths import PLAYWRIGHT_ARTIFACTS as RESULTS  # noqa: E402
from e2e._env import RunningServer, build_test_world, start_server  # noqa: E402

if TYPE_CHECKING:
    from collections.abc import Generator

    from playwright.sync_api import Page

#: Explicit module budget: a real browser, a subprocess server, two `module add`s, a real
#: `drill check` and three reloads. Each wait below is bounded well under this.
pytestmark = [pytest.mark.e2e, pytest.mark.timeout(300)]

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "modules"
VALID_SCAFFOLD = FIXTURES / "valid-scaffold"
RUNNER_OFFLINE = FIXTURES / "runner-offline"
DRILL_REF = "echo-drills/echo-basics/echo-01"
DECK = json.loads((VALID_SCAFFOLD / "decks" / "echo-basics.json").read_text("utf-8"))
TASK = DECK["tasks"][0]
MENTOR_ONLY_TEXT = (TASK["hint"], TASK["solution"], TASK["mentorNotes"])

BEGIN_SENTINEL = "<<<studyloop:practice_check v1"
END_SENTINEL = "<<<end studyloop:practice_check>>>"
TAIL_LINE_PREFIX = "| "

#: Facts one phase establishes for a later one (the session id the start claimed).
JOURNEY: dict[str, str] = {}


# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture(scope="module")
def labs_env(tmp_path_factory: pytest.TempPathFactory) -> Generator[RunningServer, None, None]:
    """A server in its own world with the harness agent. Module-scoped: the phases are one
    journey against one lockfile, one state file and one live session."""
    root = tmp_path_factory.mktemp("labs-journey")
    world = build_test_world(root, _free_port(), fake_agent=True)
    server = start_server(world)
    try:
        yield server
    finally:
        with contextlib.suppress(Exception):
            server_opener(server.base_url).open(
                urllib.request.Request(
                    f"{server.base_url}/api/session/end", data=b"", method="POST"
                ),
                timeout=10,
            )
        server.stop()


@pytest.fixture(scope="module")
def page(labs_env: RunningServer, browser):
    """One page for the whole journey; console errors and API calls are recorded on it."""
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    pg = context.new_page()
    errors: list[str] = []
    pg.on("pageerror", lambda exc: errors.append(f"pageerror: {exc}"))

    def _record(msg) -> None:
        if msg.type != "error":
            return
        where = ""
        with contextlib.suppress(Exception):
            loc = msg.location or {}
            where = f" @ {loc.get('url', '?')}:{loc.get('lineNumber', '?')}"
        errors.append(f"console.error: {msg.text}{where}")

    pg.on("console", _record)
    calls: list[tuple[str, str]] = []

    def _record_request(request) -> None:
        from urllib.parse import urlsplit

        path = urlsplit(request.url).path
        if path.startswith("/api/"):
            calls.append((request.method, path))

    pg.on("request", _record_request)
    pg._studyloop_errors = errors
    pg._studyloop_api_calls = calls
    yield pg
    with contextlib.suppress(Exception):
        pg.evaluate("async () => { await fetch('/api/session/end', {method: 'POST'}); }")
    context.close()


# ---------------------------------------------------------------------------
# Helpers -- the representative user actions and the CLI the learner types
# ---------------------------------------------------------------------------


def _cli(server: RunningServer, *args: str, stdin: str = "") -> subprocess.CompletedProcess[str]:
    """Run `studyloop <args>` exactly as the learner would, in the world's environment."""
    return subprocess.run(
        [sys.executable, "-m", "studyloop.cli", *args],
        env=dict(server.world.env),
        cwd=server.world.cwd,
        input=stdin,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


def _api(page: Page, path: str) -> dict:
    return page.evaluate("async (p) => { const r = await fetch(p); return await r.json(); }", path)


def _assert_called(page: Page, method: str, path: str) -> None:
    calls = getattr(page, "_studyloop_api_calls", [])
    assert (method, path) in calls, (
        f"the UI never issued {method} {path}; recent API calls: {calls[-12:]}"
    )


def _state_file(server: RunningServer) -> dict:
    return json.loads((server.world.session_dir / "session-state.json").read_text("utf-8"))


def _goto(page: Page, server: RunningServer, view: str) -> None:
    if not page.url.startswith(server.base_url):
        page.goto(f"{server.base_url}/#{view}")
    page.wait_for_function("() => !!window.Alpine && !!window.Alpine.store('nav')", timeout=15_000)
    page.evaluate("(v) => window.Alpine.store('nav').go(v)", view)
    page.wait_for_timeout(200)


def _reload(page: Page) -> None:
    page.reload()
    page.wait_for_function("() => !!window.Alpine && !!window.Alpine.store('nav')", timeout=15_000)


def _labs_entry_visible(page: Page) -> bool:
    return page.locator("[data-testid='nav-labs']").is_visible()


def _wait_labs_entry(page: Page, *, visible: bool) -> None:
    page.wait_for_selector(
        "[data-testid='nav-labs']", state="visible" if visible else "hidden", timeout=15_000
    )


def _diag(page: Page, label: str) -> None:
    RESULTS.mkdir(parents=True, exist_ok=True)
    with contextlib.suppress(Exception):
        page.screenshot(path=str(RESULTS / f"labs-{label}.png"), full_page=True)
    with contextlib.suppress(Exception):
        (RESULTS / f"labs-{label}.html").write_text(page.content(), encoding="utf-8")


#: xterm.js paints to a canvas, so the mentor pane's text is read from the live component's
#: buffer (the same technique the Body Double journey uses), scoped to the STUDY console.
_TERMINAL_TEXT_JS = """
() => {
  const el = document.querySelector('.session-active-layout .session-terminal-area');
  if (!el || !window.Alpine) return '';
  const data = window.Alpine.$data(el);
  const term = data && data._term;
  if (!term || !term.buffer) return '';
  const buf = term.buffer.active;
  /* Logical lines: xterm wraps at the column count and marks the continuation rows
     `isWrapped`; joining those rows untrimmed, then trimming once, restores the text
     the child wrote (a phrase split across a wrap is one phrase again). */
  const lines = [];
  for (let i = 0; i < buf.length; i += 1) {
    const line = buf.getLine(i);
    if (!line) continue;
    const text = line.translateToString(false);
    if (line.isWrapped && lines.length) lines[lines.length - 1] += text;
    else lines.push(text);
  }
  return lines.map((l) => l.replace(/\\s+$/, '')).join('\\n');
}
"""


def _terminal_text(page: Page) -> str:
    return page.evaluate(_TERMINAL_TEXT_JS)


def _wait_for_terminal_text(page: Page, needle: str, timeout: int = 60_000) -> None:
    page.wait_for_function(
        "(needle) => { const read = " + _TERMINAL_TEXT_JS + "; return read().includes(needle); }",
        arg=needle,
        timeout=timeout,
    )


def _study_consoles(page: Page) -> int:
    return page.evaluate(
        """() => document.querySelectorAll(
             '.session-active-layout .session-terminal-area .xterm-screen, '
             + '.session-active-layout .session-terminal-area canvas').length"""
    )


def _body_double_consoles(page: Page) -> int:
    return page.evaluate(
        "() => document.querySelectorAll('.bd-console-panel .xterm-screen, "
        ".bd-console-panel canvas').length"
    )


# ---------------------------------------------------------------------------
# Phase 1 -- no module, no Labs
# ---------------------------------------------------------------------------


def test_phase1_no_module_means_no_labs_entry(page: Page, labs_env: RunningServer) -> None:
    try:
        page.goto(f"{labs_env.base_url}/#today")
        page.wait_for_function(
            "() => !!window.Alpine && !!window.Alpine.store('labs')", timeout=15_000
        )
        _assert_called(page, "GET", "/api/modules/labs")
        page.wait_for_function("() => window.Alpine.store('labs').loaded === true", timeout=15_000)
        assert not _labs_entry_visible(page), "Labs must be hidden with an empty lockfile"
        assert "labs" not in _api(page, "/api/session/options"), "options carry no Labs entry"
        assert _api(page, "/api/modules/labs")["labs"] == []
        visible_text = page.evaluate("() => document.body.innerText")
        assert "prerequisite" not in visible_text.lower(), "no prerequisite text anywhere"
        for text in MENTOR_ONLY_TEXT:
            assert text not in page.content()
    except Exception:
        _diag(page, "phase1")
        raise


# ---------------------------------------------------------------------------
# Phase 2 -- module add -> one Labs entry listing ids and prompts
# ---------------------------------------------------------------------------


def test_phase2_module_add_shows_one_labs_entry_with_ids_and_prompts(
    page: Page, labs_env: RunningServer
) -> None:
    try:
        for fixture in (VALID_SCAFFOLD, RUNNER_OFFLINE):
            result = _cli(labs_env, "module", "add", str(fixture))
            assert result.returncode == 0, result.stdout + result.stderr
        listed = _cli(labs_env, "module", "list")
        assert "echo-drills" in listed.stdout and "runner-offline" in listed.stdout, listed.stdout

        _reload(page)
        _wait_labs_entry(page, visible=True)
        assert page.locator("[data-testid='nav-labs']").count() == 1, "exactly ONE Labs entry"
        options = _api(page, "/api/session/options")
        assert [m["module_id"] for m in options["labs"]] == ["echo-drills", "runner-offline"]

        _goto(page, labs_env, "labs")
        page.wait_for_selector("[data-testid='labs-view']", state="visible", timeout=15_000)
        page.wait_for_selector(
            "[data-testid='labs-start-echo-01']", state="visible", timeout=15_000
        )
        view_text = page.locator("[data-testid='labs-view']").inner_text()
        # Grouped by module, by id and prompt.
        assert view_text.index("echo-drills") < view_text.index("runner-offline")
        for needle in ("echo-basics", "echo-01", TASK["prompt"], TASK["successCriteria"][0]):
            assert needle in view_text, f"{needle!r} missing from the Labs view"
        assert "offline" in view_text and "echo-check" in view_text
        assert f"studyloop drill check {DRILL_REF}" not in view_text, (
            "the commands belong to the live-drill strip, not to every card"
        )
        # Nothing mentor-side, anywhere in the DOM -- not just the visible text.
        html = page.content()
        for text in MENTOR_ONLY_TEXT:
            assert text not in html, f"mentor-side text reached the DOM: {text!r}"
        assert "overdue" not in page.evaluate("() => document.body.innerText").lower()
        # A session-less page: the Study Session console is not mounted.
        assert _study_consoles(page) == 0
    except Exception:
        _diag(page, "phase2")
        raise


# ---------------------------------------------------------------------------
# Phase 3 -- start inside the one claimed session
# ---------------------------------------------------------------------------


def test_phase3_start_runs_inside_the_one_claimed_session(
    page: Page, labs_env: RunningServer
) -> None:
    try:
        _goto(page, labs_env, "labs")
        page.wait_for_function(
            """() => {
                const sel = document.querySelector('#labs-agent-select');
                return sel && sel.value === 'codex';
            }""",
            timeout=30_000,
        )
        page.locator("[data-testid='labs-start-echo-01']").click()

        # The one start path: POST /api/modules/labs/start, then the Study Session view
        # re-adopts the live session on load and the console -- the mentor pane -- mounts.
        page.wait_for_selector(
            ".session-active-layout .xterm-mount", state="visible", timeout=60_000
        )
        page.wait_for_function("() => location.hash === '#study-session'", timeout=15_000)
        _wait_for_terminal_text(page, "FAKE-AGENT READY")
        _wait_for_terminal_text(page, "FAKE-AGENT TOPIC: Lab: " + DRILL_REF)
        assert _study_consoles(page) >= 1
        assert _body_double_consoles(page) == 0, "the Body Double console must not cross-fire"

        state = _api(page, "/api/session/state")
        assert state["origin"] == "study"
        assert state["labs_drill"]["ref"] == DRILL_REF
        assert state["topic"] == f"Lab: {DRILL_REF}"
        JOURNEY["session_id"] = state["study_session_id"]

        # The capability for the hop sits in the owner-only state file beside the port.
        on_disk = _state_file(labs_env)
        assert on_disk["web_port"] == labs_env.port
        assert on_disk["practice_check_token"]
        mode = (labs_env.world.session_dir / "session-state.json").stat().st_mode & 0o777
        assert mode == 0o600, oct(mode)

        # Nothing ran: no attempt directory exists anywhere in the world.
        assert not list(labs_env.world.root.rglob("module-attempts")), "a phase ran from Labs"
    except Exception:
        _diag(page, "phase3")
        raise


# ---------------------------------------------------------------------------
# Phase 4 -- keyboard traversal
# ---------------------------------------------------------------------------


def test_phase4_tab_and_shift_tab_traverse_the_labs_controls(
    page: Page, labs_env: RunningServer
) -> None:
    try:
        _goto(page, labs_env, "labs")
        page.wait_for_selector("[data-testid='labs-active-drill']", state="visible", timeout=15_000)
        strip = page.locator("[data-testid='labs-active-drill']").inner_text()
        assert f"studyloop drill check {DRILL_REF}" in strip, "the live strip names the command"

        page.locator("[data-testid='labs-open-session']").focus()
        focused = page.evaluate("() => document.activeElement.getAttribute('data-testid')")
        assert focused == "labs-open-session"
        page.keyboard.press("Tab")
        focused = page.evaluate("() => document.activeElement.getAttribute('data-testid')")
        assert focused == "labs-cancel-drill", f"Tab landed on {focused!r}"
        page.keyboard.press("Shift+Tab")
        focused = page.evaluate("() => document.activeElement.getAttribute('data-testid')")
        assert focused == "labs-open-session", f"Shift-Tab landed on {focused!r}"
        # Tab through the agent select to the first Start button (disabled 'Live' is skipped).
        page.keyboard.press("Tab")
        page.keyboard.press("Tab")
        focused_id = page.evaluate("() => document.activeElement.id")
        assert focused_id == "labs-agent-select", f"Tab landed on #{focused_id!r}"
        page.keyboard.press("Tab")
        focused = page.evaluate("() => document.activeElement.getAttribute('data-testid')")
        assert focused == "labs-start-echo-check", f"Tab landed on {focused!r} (echo-01 is live)"
    except Exception:
        _diag(page, "phase4")
        raise


# ---------------------------------------------------------------------------
# Phase 5 -- reload re-attaches, no second session
# ---------------------------------------------------------------------------


def test_phase5_reload_reattaches_with_no_second_session(
    page: Page, labs_env: RunningServer
) -> None:
    try:
        before = _api(page, "/api/session/state")
        errors_before = len(getattr(page, "_studyloop_errors", []))
        _reload(page)
        _goto(page, labs_env, "study-session")
        page.wait_for_selector(
            ".session-active-layout .xterm-mount", state="visible", timeout=60_000
        )
        # A re-attach does not replay earlier output; the console says so, and that line is
        # the proof the SAME running session was adopted rather than a new one started.
        _wait_for_terminal_text(page, "reattached to your running session")
        after = _api(page, "/api/session/state")
        assert after["study_session_id"] == before["study_session_id"] == JOURNEY["session_id"]
        assert after["labs_drill"]["ref"] == DRILL_REF
        assert _study_consoles(page) >= 1 and _body_double_consoles(page) == 0
        # The live drill survived the reload in the Labs view too.
        _goto(page, labs_env, "labs")
        page.wait_for_selector("[data-testid='labs-active-drill']", state="visible", timeout=15_000)
        # W-review finding 10: `#labs` is a real hash view -- a reload ON Labs lands on Labs
        # (not on Today), with the live drill still shown.
        assert page.evaluate("() => location.hash") == "#labs"
        _reload(page)
        page.wait_for_function(
            "() => window.Alpine.store('nav').current === 'labs'", timeout=15_000
        )
        page.wait_for_selector("[data-testid='labs-view']", state="visible", timeout=15_000)
        page.wait_for_selector("[data-testid='labs-active-drill']", state="visible", timeout=15_000)
        assert _api(page, "/api/session/state")["study_session_id"] == JOURNEY["session_id"]
        # Post-reload the only tolerated noise is htmx re-owning its SSE stream (a bare
        # `Event`), exactly as the Body Double journey tolerates it. Anything else is real.
        post_reload = [
            err
            for err in getattr(page, "_studyloop_errors", [])[errors_before:]
            if not ("Event" in err and "htmx" in err)
        ]
        assert not post_reload, f"reload produced unexpected console errors: {post_reload}"
    except Exception:
        _diag(page, "phase5")
        raise


# ---------------------------------------------------------------------------
# Phase 6 -- cancel: the session returns to its prior state, nothing executed
# ---------------------------------------------------------------------------


def test_phase6_escape_cancels_the_drill_and_leaves_the_session_alone(
    page: Page, labs_env: RunningServer
) -> None:
    try:
        _goto(page, labs_env, "labs")
        page.wait_for_selector("[data-testid='labs-active-drill']", state="visible", timeout=15_000)
        page.locator("[data-testid='labs-cancel-drill']").focus()
        page.keyboard.press("Escape")
        page.wait_for_selector("[data-testid='labs-active-drill']", state="hidden", timeout=15_000)
        _assert_called(page, "POST", "/api/modules/labs/cancel")
        assert ("POST", "/api/session/end") not in getattr(page, "_studyloop_api_calls", []), (
            "cancel must never end the session"
        )
        state = _api(page, "/api/session/state")
        assert state["study_session_id"] == JOURNEY["session_id"]
        assert state["mode"] != "ended"
        assert state.get("labs_drill") is None
        assert not list(labs_env.world.root.rglob("module-attempts")), "a phase ran"
        # The Start button is offered again for the drill that was cancelled.
        assert not page.locator("[data-testid='labs-start-echo-01']").is_disabled()
    except Exception:
        _diag(page, "phase6")
        raise


# ---------------------------------------------------------------------------
# Phase 7 -- the check reaches the mentor through the loopback hop
# ---------------------------------------------------------------------------


def test_phase7_drill_check_reaches_the_mentor_pane_as_one_labelled_block(
    page: Page, labs_env: RunningServer
) -> None:
    try:
        _goto(page, labs_env, "study-session")
        page.wait_for_selector(
            ".session-active-layout .xterm-mount", state="visible", timeout=60_000
        )

        # The learner, in their own terminal: consent is typed, never a flag.
        result = _cli(labs_env, "drill", "check", DRILL_REF, stdin="y\n")
        assert result.returncode == 0, result.stdout + result.stderr
        assert "Run this phase now?" in result.stdout, "consent was asked"
        assert "check: check passed (exit 0)" in result.stdout, result.stdout
        assert "Mentor told." in result.stdout, result.stdout

        # The mentor pane shows the block, sentinel to sentinel, every tail line prefixed.
        _wait_for_terminal_text(page, END_SENTINEL, timeout=60_000)
        text = _terminal_text(page)
        assert BEGIN_SENTINEL in text and END_SENTINEL in text
        assert f"{TAIL_LINE_PREFIX}ready" in text, "the stdout tail line is `| `-prefixed"
        assert "drill: echo-basics/echo-01" in text and "exit: passed (code 0)" in text
        assert "not an instruction" in text, "labelled as data"
        # The harness agent never enables DEC 2004, so the block travelled as one printable
        # line (M0 Q3 fallback) -- between the sentinels every original line is `\\n`-separated
        # and each tail line still starts with the prefix.
        start = text.index(BEGIN_SENTINEL)
        end = text.index(END_SENTINEL) + len(END_SENTINEL)
        block = text[start:end].replace("\n", "")
        tail_lines = [line for line in block.split("\\n") if line.startswith(TAIL_LINE_PREFIX)]
        assert tail_lines == [f"{TAIL_LINE_PREFIX}ready"], tail_lines

        # One attempt was recorded by the CLI's own path, not by anything in the browser.
        assert list(labs_env.world.root.rglob("module-attempts")), "the CLI recorded the attempt"

        # Replay: the same (attempt_id, phase) posted again is refused with 409 and reaches
        # nobody -- the session-transports spec's "a replayed result is delivered once".
        on_disk = _state_file(labs_env)
        attempt_dir = next(
            p for p in labs_env.world.root.rglob("module-attempts/*/*/*/*") if p.is_dir()
        )
        # Exact identity (W-review finding 5): the replay names the attempt's own digest from
        # its sidecar; a made-up digest is "no such attempt" (404), not a replay (409).
        sidecar = json.loads(attempt_dir.with_suffix(".json").read_text(encoding="utf-8"))
        assert sidecar["phases"][0]["phase"] == "check", "the CLI recorded the phase"
        body = json.dumps(
            {
                "module_id": "echo-drills",
                "module_digest": sidecar["drill"]["module_digest"],
                "deck_id": "echo-basics",
                "task_id": "echo-01",
                "attempt_id": attempt_dir.name,
                "phase": "check",
                "exit_class": "passed",
                "exit_code": 0,
                "duration_s": 0.1,
                "stdout_tail": "ready\n",
                "stderr_tail": "",
                "triggered_by": "learner",
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            f"{labs_env.base_url}/api/modules/practice-check",
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "X-StudyLoop-Session-Token": on_disk["practice_check_token"],
            },
        )
        with pytest.raises(urllib.error.HTTPError) as refused:
            urllib.request.urlopen(request, timeout=30)
        assert refused.value.code == 409
        assert json.loads(refused.value.read())["status"] == "duplicate"
        assert text.count(END_SENTINEL) == _terminal_text(page).count(END_SENTINEL) == 1
    except Exception:
        _diag(page, "phase7")
        raise


# ---------------------------------------------------------------------------
# Phase 8 -- module remove -> Labs gone
# ---------------------------------------------------------------------------


def test_phase8_module_remove_takes_labs_away(page: Page, labs_env: RunningServer) -> None:
    try:
        for module_id in ("echo-drills", "runner-offline"):
            result = _cli(labs_env, "module", "remove", module_id)
            assert result.returncode == 0, result.stdout + result.stderr
        assert _api(page, "/api/modules/labs")["labs"] == []
        # A full reload with a stale #labs hash (a goto that only changes the hash is a
        # same-document navigation and would not re-run the page).
        page.evaluate("() => { window.location.hash = 'labs'; }")
        _reload(page)
        page.wait_for_function("() => window.Alpine.store('labs').loaded === true", timeout=15_000)
        assert not _labs_entry_visible(page), "Labs is gone with the lockfile emptied"
        assert "labs" not in _api(page, "/api/session/options")
        # `#labs` is a valid hash (finding 10) but an EMPTY Labs is not a view (C7): the Labs
        # view sends the learner to Today rather than showing a module-less page.
        page.wait_for_function(
            "() => window.Alpine.store('nav').current === 'today'", timeout=15_000
        )
        assert not page.locator("[data-testid='labs-view']").is_visible(), (
            "a stale #labs hash does not resurrect the view"
        )
        for text in MENTOR_ONLY_TEXT:
            assert text not in page.content()
    except Exception:
        _diag(page, "phase8")
        raise


def test_phase9_the_server_outlived_the_journey(page: Page, labs_env: RunningServer) -> None:
    """CHARACTERISATION, not red-first evidence (W-review finding 2): a liveness guard that is
    green by construction. Every phase drove the real server; it is still up and the page saw
    no 5xx.

    The journey's console/page errors are collected per phase (phase 5 reads them across the
    reload); a failed request would have surfaced in the phase that issued it. This closes
    the module with the two facts a later reader wants first.
    """
    assert labs_env.proc.poll() is None, "the server died during the journey"
    page_errors = [e for e in getattr(page, "_studyloop_errors", []) if "pageerror" in e]
    assert not page_errors, page_errors
