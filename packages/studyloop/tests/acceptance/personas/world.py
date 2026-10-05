"""One persona's world (module-contract v1, lane U1).

Built on lane W's test world (``tests/e2e/_env.py``: ``build_test_world`` / ``start_server`` --
a temp vault, a subprocess server, the deterministic harness agent) and on the acceptance tier's
conventions. The browser helpers at the bottom are the ones lane W's e2e journey
(``tests/e2e/test_module_labs_journey.py``) keeps private -- copied here, as the U1 brief allows,
because importing a sibling test module's underscore names would couple two lanes' tests; the
journey's PUBLIC constants are imported by the test module instead.

What this adds for the personas:

- every ``studyloop`` call goes through :meth:`PersonaWorld.cli`, which transcribes it;
- :class:`WallClockBudget` -- the persona's whole wall clock, checked before every phase and
  asserted at the end (design.md §6: 6 and 8 minutes);
- :meth:`PersonaWorld.phase` -- the phase runner: on any exception it writes the failure
  bundle (``.bundle``) and re-raises the ORIGINAL exception with the bundle path attached;
- ``STUDYLOOP_ACC_FORCE_FAIL=<phase id>`` -- the one knob that FLIPS a phase's precondition so
  its first assertion fails on its own merit (the red-first transcripts and the forced-failure
  bundle proof both use it; see the test module's docstring).
"""

from __future__ import annotations

import contextlib
import json
import os
import secrets
import socket
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

_tests_dir = str(Path(__file__).resolve().parents[2])
if _tests_dir not in sys.path:
    sys.path.insert(0, _tests_dir)

from _playwright_paths import PLAYWRIGHT_ARTIFACTS  # noqa: E402
from e2e._env import RunningServer, build_test_world, start_server  # noqa: E402

from .bundle import CliRecord, write_persona_failure_bundle  # noqa: E402

if TYPE_CHECKING:
    from collections.abc import Generator

    from playwright._impl._api_structures import HttpCredentials
    from playwright.sync_api import Browser, Page

FORCE_FAIL_ENV = "STUDYLOOP_ACC_FORCE_FAIL"

#: Where a persona's failure bundle lands: the repo's Playwright artefact root (gitignored), one
#: directory per run, so a failing `just testacc` leaves something a reader can open.
BUNDLE_ROOT = PLAYWRIGHT_ARTIFACTS / "personas"


def forced_failure_phase() -> str:
    return os.environ.get(FORCE_FAIL_ENV, "").strip()


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class BudgetExceededError(AssertionError):
    """The persona's wall clock ran past its budget (design.md §6)."""


@dataclass
class WallClockBudget:
    """The whole persona's wall clock: started at its first phase, checked before every phase."""

    persona: str
    limit_s: float
    _started: float | None = field(default=None, init=False, repr=False)

    def start(self) -> None:
        if self._started is None:
            self._started = time.monotonic()

    @property
    def started(self) -> bool:
        return self._started is not None

    def elapsed(self) -> float:
        return 0.0 if self._started is None else time.monotonic() - self._started

    def check(self, phase: str) -> None:
        """Fail BEFORE a phase starts if the budget is already spent, naming the phase."""
        elapsed = self.elapsed()
        if elapsed > self.limit_s:
            raise BudgetExceededError(
                f"Persona {self.persona} is over its {self.limit_s:.0f}s budget before "
                f"phase {phase}: {elapsed:.1f}s elapsed"
            )


@dataclass
class PersonaWorld:
    """One persona's server, CLI, browser page and the facts its phases share."""

    persona: str
    server: RunningServer
    budget: WallClockBudget
    lan_password: str | None
    cli_records: list[CliRecord] = field(default_factory=list)
    phases: list[dict[str, Any]] = field(default_factory=list)
    facts: dict[str, Any] = field(default_factory=dict)
    page: Page | None = None
    console_errors: list[str] = field(default_factory=list)
    api_calls: list[tuple[str, str]] = field(default_factory=list)
    lockfile_baseline: str | None = None
    bundle_dir: Path | None = None
    run_id: str = field(default_factory=lambda: f"{int(time.time())}-{secrets.token_hex(4)}")

    # -- paths -------------------------------------------------------------------------

    @property
    def world(self):
        return self.server.world

    @property
    def lockfile_path(self) -> Path:
        """``<config dir>/modules/modules.lock.json`` exactly as ``modules.store`` derives it:
        the config dir is ``$STUDYLOOP_CONFIG``'s parent in a test world."""
        return Path(self.world.env["STUDYLOOP_CONFIG"]).parent / "modules" / "modules.lock.json"

    def lockfile_text(self) -> str | None:
        try:
            return self.lockfile_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None

    def attempt_dirs(self) -> list[Path]:
        return [p for p in self.world.root.rglob("module-attempts") if p.is_dir()]

    def server_log_text(self) -> str:
        path = getattr(self.server.proc, "studyloop_log_path", None)
        if not path:
            return "(the server process carries no studyloop_log_path)\n"
        try:
            return Path(path).read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            return f"(could not read the server log {path}: {exc})\n"

    def state_file(self) -> dict[str, Any]:
        return json.loads((self.world.session_dir / "session-state.json").read_text("utf-8"))

    def secrets(self) -> dict[str, str]:
        """Run secrets the bundle must never carry: the LAN password, the capability token."""
        found: dict[str, str] = {}
        if self.lan_password:
            found["lan_password"] = self.lan_password
        with contextlib.suppress(Exception):
            token = self.state_file().get("practice_check_token")
            if isinstance(token, str) and token:
                found["practice_check_token"] = token
        return found

    # -- the learner's CLI -------------------------------------------------------------

    def cli(
        self,
        *args: str,
        stdin: str = "",
        cwd: Path | None = None,
        env: dict[str, str] | None = None,
        timeout: int = 120,
    ) -> subprocess.CompletedProcess[str]:
        """Run ``studyloop <args>`` as the learner would, in the world's env, transcribed."""
        started = time.monotonic()
        result = subprocess.run(
            [sys.executable, "-m", "studyloop.cli", *args],
            env=dict(self.world.env) if env is None else env,
            cwd=self.world.cwd if cwd is None else cwd,
            input=stdin,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        self.cli_records.append(
            CliRecord(
                argv=tuple(args),
                stdin=stdin,
                returncode=result.returncode,
                stdout=result.stdout,
                stderr=result.stderr,
                duration_s=time.monotonic() - started,
            )
        )
        return result

    # -- phases ------------------------------------------------------------------------

    def flipped(self, phase: str) -> bool:
        """True when ``STUDYLOOP_ACC_FORCE_FAIL`` names this phase: flip its precondition."""
        return forced_failure_phase() == phase

    @contextlib.contextmanager
    def phase(
        self, phase_id: str, title: str, *, bundle: bool = True
    ) -> Generator[None, None, None]:
        """Run one phase: budget check first; on failure the bundle, then the same exception.

        ``bundle=False`` for a phase whose failure is EXPECTED (an ``xfail`` naming a product
        gap): the failure is the finding, and a bundle per run would only bury the real ones.
        """
        self.budget.start()
        self.budget.check(phase_id)
        record: dict[str, Any] = {
            "phase": phase_id,
            "title": title,
            "flipped": self.flipped(phase_id),
            "started_at_s": round(self.budget.elapsed(), 3),
        }
        started = time.monotonic()
        try:
            yield
        except BaseException as exc:
            record.update(status="failed", error=f"{type(exc).__name__}: {exc}")
            record["elapsed_s"] = round(time.monotonic() - started, 3)
            self.phases.append(record)
            if bundle:
                bundle_dir = self.write_failure_bundle(phase_id, str(exc))
                if isinstance(exc, Exception):
                    exc.add_note(f"[persona {self.persona}] failure bundle: {bundle_dir}")
            raise
        record.update(status="passed", elapsed_s=round(time.monotonic() - started, 3))
        self.phases.append(record)

    def attempt_envelope(self) -> dict[str, Any] | None:
        """What a drill start left behind: the state file's ``labs_drill`` record, the session it
        was bound to, and every attempt sidecar the CLI recorded (none when Labs only started)."""
        try:
            state = self.state_file()
        except (OSError, ValueError):
            state = {}
        drill = state.get("labs_drill")
        sidecars = []
        for attempts in self.attempt_dirs():
            for sidecar in sorted(attempts.rglob("*.json")):
                with contextlib.suppress(OSError, ValueError):
                    sidecars.append(json.loads(sidecar.read_text(encoding="utf-8")))
        if drill is None and not sidecars and "drill_started" not in self.facts:
            return None
        return {
            "labs_drill": drill,
            "study_session_id": state.get("study_session_id"),
            "started_from_labs": self.facts.get("drill_started"),
            "attempt_records": sidecars,
        }

    def write_failure_bundle(self, phase_id: str, reason: str) -> Path | None:
        """Write the failure bundle; never raises (a bundle must not mask the real failure)."""
        try:
            screenshot: bytes | None = None
            html: str | None = None
            if self.page is not None:
                with contextlib.suppress(Exception):
                    screenshot = self.page.screenshot(full_page=True)
                with contextlib.suppress(Exception):
                    html = self.page.content()
            bundle, violations = write_persona_failure_bundle(
                BUNDLE_ROOT,
                run_id=f"persona-{self.persona.lower()}-{self.run_id}-{phase_id}",
                persona=self.persona,
                outcome=f"failed at {phase_id}: {reason[:200]}",
                phases=list(self.phases),
                server_log=self.server_log_text(),
                cli_records=list(self.cli_records),
                lockfile_before=self.lockfile_baseline,
                lockfile_after=self.lockfile_text(),
                attempt_envelope=self.attempt_envelope(),
                screenshot_png=screenshot,
                page_html=html,
                console={
                    "errors": list(self.console_errors),
                    "api_calls": [list(call) for call in self.api_calls[-40:]],
                },
                homes=[self.world.root, Path.home()],
                secrets=self.secrets(),
            )
            self.bundle_dir = bundle.run_dir
            if violations:
                print(f"[persona {self.persona}] REDACTION VIOLATIONS in {bundle.run_dir}:")
                for violation in violations:
                    print(f"  - {violation}")
            print(f"[persona {self.persona}] failure bundle written: {bundle.run_dir}")
            return bundle.run_dir
        except Exception as exc:  # pragma: no cover - diagnostics never mask the failure
            print(f"[persona {self.persona}] could not write the failure bundle: {exc!r}")
            return None


# ---------------------------------------------------------------------------
# Building a world
# ---------------------------------------------------------------------------


def launch_persona_world(root: Path, *, persona: str, budget_s: float, lan: bool) -> PersonaWorld:
    """A server in its own world with the harness agent; ``--lan`` for Persona A.

    ``--lan`` makes the product bind ``0.0.0.0`` and protect the UI with HTTP Basic Auth; the
    password travels the production way (``STUDYLOOP_WEB_PASSWORD`` in the server's env, never
    argv). The TEST only ever connects to ``127.0.0.1`` -- the world's ``base_url`` -- so no LAN
    address is used anywhere.
    """
    password = secrets.token_urlsafe(16) if lan else None
    extra_env = {"STUDYLOOP_WEB_PASSWORD": password} if password else None
    world = build_test_world(root, free_port(), fake_agent=True, extra_env=extra_env)
    server = start_server(world, extra_args=["--lan"] if lan else None)
    persona_world = PersonaWorld(
        persona=persona,
        server=server,
        budget=WallClockBudget(persona, budget_s),
        lan_password=password,
    )
    persona_world.lockfile_baseline = persona_world.lockfile_text()
    return persona_world


def stop_persona_world(world: PersonaWorld) -> None:
    with contextlib.suppress(Exception):
        if world.page is not None:
            world.page.evaluate(
                "async () => { await fetch('/api/session/end', {method: 'POST'}); }"
            )
    with contextlib.suppress(Exception):
        if world.page is not None:
            world.page.context.close()
    world.server.stop()


def open_page(browser: Browser, world: PersonaWorld, *, viewport: tuple[int, int]) -> Page:
    """One page for the whole persona, console errors and API calls recorded on the world."""
    credentials: HttpCredentials | None = (
        {"username": "study", "password": world.lan_password} if world.lan_password else None
    )
    context = browser.new_context(
        viewport={"width": viewport[0], "height": viewport[1]}, http_credentials=credentials
    )
    page = context.new_page()
    page.on("pageerror", lambda exc: world.console_errors.append(f"pageerror: {exc}"))

    def _record(msg) -> None:
        if msg.type != "error":
            return
        where = ""
        with contextlib.suppress(Exception):
            loc = msg.location or {}
            where = f" @ {loc.get('url', '?')}:{loc.get('lineNumber', '?')}"
        world.console_errors.append(f"console.error: {msg.text}{where}")

    page.on("console", _record)

    def _record_request(request) -> None:
        path = urlsplit(request.url).path
        if path.startswith("/api/"):
            world.api_calls.append((request.method, path))

    page.on("request", _record_request)
    world.page = page
    return page


# ---------------------------------------------------------------------------
# Browser helpers (copied from lane W's e2e journey, which keeps them private)
# ---------------------------------------------------------------------------


def api(page: Page, path: str) -> Any:
    return page.evaluate("async (p) => { const r = await fetch(p); return await r.json(); }", path)


def wait_alpine(page: Page) -> None:
    page.wait_for_function("() => !!window.Alpine && !!window.Alpine.store('nav')", timeout=15_000)


def goto(page: Page, world: PersonaWorld, view: str) -> None:
    if not page.url.startswith(world.server.base_url):
        page.goto(f"{world.server.base_url}/#{view}")
    wait_alpine(page)
    page.evaluate("(v) => window.Alpine.store('nav').go(v)", view)
    page.wait_for_timeout(200)


def reload(page: Page) -> None:
    page.reload()
    wait_alpine(page)


def labs_entry_visible(page: Page) -> bool:
    return page.locator("[data-testid='nav-labs']").is_visible()


def wait_labs_entry(page: Page, *, visible: bool) -> None:
    page.wait_for_selector(
        "[data-testid='nav-labs']", state="visible" if visible else "hidden", timeout=15_000
    )


def wait_labs_loaded(page: Page) -> None:
    page.wait_for_function("() => !!window.Alpine && !!window.Alpine.store('labs')", timeout=15_000)
    page.wait_for_function("() => window.Alpine.store('labs').loaded === true", timeout=15_000)


def visible_text(page: Page) -> str:
    return page.evaluate("() => document.body.innerText")


def active_testid(page: Page) -> str | None:
    return page.evaluate(
        "() => document.activeElement && document.activeElement.getAttribute('data-testid')"
    )


def active_element_description(page: Page) -> str:
    return page.evaluate(
        """() => {
            const el = document.activeElement;
            if (!el) return 'null';
            const cls = typeof el.className === 'string' && el.className
              ? '.' + el.className.split(' ').join('.') : '';
            const testid = el.getAttribute('data-testid');
            return el.tagName.toLowerCase()
              + (el.id ? '#' + el.id : '')
              + cls
              + (testid ? '[data-testid=' + testid + ']' : '');
        }"""
    )


#: xterm.js paints to a canvas, so the mentor pane's text is read from the live component's
#: buffer, scoped to the STUDY console (the e2e journey's technique).
TERMINAL_TEXT_JS = """
() => {
  const el = document.querySelector('.session-active-layout .session-terminal-area');
  if (!el || !window.Alpine) return '';
  const data = window.Alpine.$data(el);
  const term = data && data._term;
  if (!term || !term.buffer) return '';
  const buf = term.buffer.active;
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


def terminal_text(page: Page) -> str:
    return page.evaluate(TERMINAL_TEXT_JS)


def wait_for_terminal_text(page: Page, needle: str, timeout: int = 60_000) -> None:
    page.wait_for_function(
        "(needle) => { const read = " + TERMINAL_TEXT_JS + "; return read().includes(needle); }",
        arg=needle,
        timeout=timeout,
    )


def study_consoles(page: Page) -> int:
    return page.evaluate(
        """() => document.querySelectorAll(
             '.session-active-layout .session-terminal-area .xterm-screen, '
             + '.session-active-layout .session-terminal-area canvas').length"""
    )


def body_double_consoles(page: Page) -> int:
    return page.evaluate(
        "() => document.querySelectorAll('.bd-console-panel .xterm-screen, "
        ".bd-console-panel canvas').length"
    )


def terminal_has_focus(page: Page) -> bool:
    """True when the focused element is inside the Study Session console's xterm mount
    (xterm's own ``.xterm-helper-textarea`` is what carries keyboard focus)."""
    return page.evaluate(
        """() => {
            const el = document.activeElement;
            if (!el) return false;
            return !!el.closest('.session-active-layout .session-terminal-area');
        }"""
    )


__all__ = [
    "BUNDLE_ROOT",
    "FORCE_FAIL_ENV",
    "TERMINAL_TEXT_JS",
    "BudgetExceededError",
    "PersonaWorld",
    "WallClockBudget",
    "active_element_description",
    "active_testid",
    "api",
    "body_double_consoles",
    "forced_failure_phase",
    "free_port",
    "goto",
    "labs_entry_visible",
    "launch_persona_world",
    "open_page",
    "reload",
    "stop_persona_world",
    "study_consoles",
    "terminal_has_focus",
    "terminal_text",
    "visible_text",
    "wait_alpine",
    "wait_for_terminal_text",
    "wait_labs_entry",
    "wait_labs_loaded",
]
