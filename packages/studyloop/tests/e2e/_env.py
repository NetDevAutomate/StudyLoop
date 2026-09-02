"""Shared e2e scaffolding: isolated vault + server, and browser diagnostics.

Every e2e module in this package needs the same three things:

1. a **temp study vault** with real markdown lessons, so content-driven views
   (Course Explorer, generation, review) have deterministic data and the
   user's real vault is never read or written;
2. a **subprocess-hosted server** pointed at that vault (main thread owns the
   asyncio loop, which the PTY transport's ``SIGCHLD`` handler requires);
3. **failure artifacts** — screenshot + HTML + console log — because a headless
   browser failure with no artifact is unactionable.

Kept separate from ``_playwright_helpers`` (which serves the older
``test_web_*`` modules) so this package can evolve without churning those.
"""

from __future__ import annotations

import json
import os
import shlex
import sys
import time
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING

_tests_dir = str(Path(__file__).resolve().parent.parent)
if _tests_dir not in sys.path:
    sys.path.insert(0, _tests_dir)

from _playwright_helpers import start_web_server  # noqa: E402
from _playwright_paths import PLAYWRIGHT_ARTIFACTS  # noqa: E402

_TEST_AGENT_SCRIPT = Path(_tests_dir) / "_fake_agent.py"

if TYPE_CHECKING:
    import subprocess
    from collections.abc import Mapping

    from playwright.sync_api import Page

RESULTS = PLAYWRIGHT_ARTIFACTS

# ---------------------------------------------------------------------------
# The study topic every test in this package teaches against.
#
# One topic, one truth: the fake mentor's question bank, the generated deck,
# the review answers and the vault lesson all describe *Python decorators*, so
# "does the agent ask questions relevant to what the user is studying" is a
# checkable property rather than a vibe.
# ---------------------------------------------------------------------------

STUDY_TOPIC = "Python Decorators"
STUDY_TOPIC_SLUG = "python-decorators"

#: A real lesson exercising every render class the web UI must handle:
#: headings, prose, list, inline code, a fenced code block (highlight.js) and
#: a ```mermaid fence (mermaid.js two-pass render).
LESSON_MARKDOWN = """\
# Python Decorators

A **decorator** is a callable that takes a function and returns a new
function, letting you add behaviour without editing the original.

## Why they matter

- They make cross-cutting concerns (logging, caching, timing) reusable.
- `functools.wraps` preserves the wrapped function's metadata.
- Decorators are just syntax sugar for `f = decorator(f)`.

## Example

```python
import functools

def timed(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        return func(*args, **kwargs)
    return wrapper
```

## Call order

```mermaid
flowchart LR
    call["caller"] --> wrapper["wrapper()"]
    wrapper --> inner["original function"]
    inner --> ret["return value"]
```

## Common mistakes

Forgetting `functools.wraps`, which silently rewrites `__name__` and drops
the docstring.
"""

PROVIDER = "StudyLoopTest"
COURSE = "Python_Deep_Dive"
LESSON_STEM = "01-decorators"

#: lesson_id the explorer API uses: provider/course/relative-path (no suffix)
LESSON_ID = f"{PROVIDER}/{COURSE}/study-notes/{LESSON_STEM}"
COURSE_ID = f"{PROVIDER}/{COURSE}"


@dataclass
class E2EEnv:
    """A running server plus the isolated vault/config/IPC it was launched with."""

    base_url: str
    port: int
    vault: Path
    config: Path
    proc: subprocess.Popen
    session_dir: Path | None = None
    env: dict[str, str] = field(default_factory=dict)
    world: TestWorld | None = None
    server: RunningServer | None = None


@dataclass(frozen=True, slots=True)
class TestWorld:
    """Immutable description of one isolated StudyLoop environment."""

    root: Path
    cwd: Path
    home: Path
    tmp_dir: Path
    vault: Path
    config: Path
    session_db: Path
    session_dir: Path
    plans: Path
    port: int
    env: Mapping[str, str]

    @property
    def base_url(self) -> str:
        """Return the URL for the server bound to this world."""
        return f"http://127.0.0.1:{self.port}"


@dataclass
class RunningServer:
    """Mutable process handle bound to one immutable :class:`TestWorld`."""

    world: TestWorld
    proc: subprocess.Popen

    @property
    def base_url(self) -> str:
        return self.world.base_url

    @property
    def port(self) -> int:
        return self.world.port

    def stop(self) -> None:
        """Terminate this server and wait for its process to exit."""
        self.proc.terminate()
        try:
            self.proc.wait(timeout=5)
        except Exception:  # pragma: no cover - defensive cleanup
            with suppress(Exception):
                self.proc.kill()
                self.proc.wait(timeout=5)


def _controlled_path() -> str:
    """Return a predictable PATH without inheriting the shell's PATH."""
    candidates = (Path(sys.prefix) / "bin", Path(sys.executable).resolve().parent)
    bins = list(dict.fromkeys(str(path) for path in candidates if path.is_dir()))
    return os.pathsep.join((*bins, os.defpath))


def build_vault(root: Path) -> Path:
    """Create the deterministic study vault and return its base path."""
    vault = root / "study-materials"
    notes = vault / PROVIDER / COURSE / "study-notes"
    notes.mkdir(parents=True, exist_ok=True)
    (notes / f"{LESSON_STEM}.md").write_text(LESSON_MARKDOWN, encoding="utf-8")
    # A second lesson so list/carousel UI has more than one row to render.
    (notes / "02-closures.md").write_text(
        "# Closures\n\nA closure captures the enclosing scope's names.\n",
        encoding="utf-8",
    )
    return vault


def build_config(root: Path, vault: Path) -> Path:
    """Write a studyloop config scoped to the temp vault and a temp session DB.

    ``session_db`` is redirected on purpose: the parking board, progress rows
    and study-session history all write to it, and an e2e sweep must not
    mutate (or read) the learner's real database.
    """
    config = root / "studyloop-e2e-config.yaml"
    config.write_text(
        "topics:\n"
        f"  - name: {STUDY_TOPIC}\n"
        f"    slug: {STUDY_TOPIC_SLUG}\n"
        f"    obsidian_path: {PROVIDER}/{COURSE}\n"
        "    tags: [python, decorators]\n"
        "content:\n"
        f"  base_path: {vault}\n"
        f"  study_paths:\n    - {vault}\n"
        f"session_db: {root / 'sessions.db'}\n",
        encoding="utf-8",
    )
    return config


def build_test_world(
    root: Path,
    port: int,
    *,
    fake_agent: bool = False,
    plans_dir: Path | None = None,
    extra_env: dict[str, str] | None = None,
    vault_path: Path | None = None,
    config_path: Path | None = None,
    session_db_path: Path | None = None,
    path_prefix: Path | None = None,
) -> TestWorld:
    """Build an isolated world without starting a server.

    The returned environment is complete rather than parent-derived. This is
    deliberately separate from process startup so tests can inspect and
    poison the parent environment before proving the world remains stable.
    """
    root.mkdir(parents=True, exist_ok=True)
    home = root / "home"
    tmp_dir = root / "tmp"
    session_dir = root / "session-ipc"
    plans = plans_dir if plans_dir is not None else root / "study-plans"
    for directory in (home, tmp_dir, session_dir, plans):
        directory.mkdir(parents=True, exist_ok=True)

    vault = vault_path if vault_path is not None else build_vault(root)
    config = config_path if config_path is not None else build_config(root, vault)
    session_db = session_db_path if session_db_path is not None else root / "sessions.db"

    child_env = {
        "PATH": _controlled_path(),
        "HOME": str(home),
        "TMPDIR": str(tmp_dir),
        "XDG_CONFIG_HOME": str(home / ".config"),
        "XDG_STATE_HOME": str(home / ".local" / "state"),
        "XDG_CACHE_HOME": str(home / ".cache"),
        "LANG": "C",
        "LC_ALL": "C",
        "NO_COLOR": "1",
        "TERM": "dumb",
        "TZ": "UTC",
        "PYTHONHASHSEED": "0",
        "STUDYLOOP_CONFIG": str(config),
        "STUDYLOOP_SESSION_DIR": str(session_dir),
        "STUDYLOOP_PLANS_DIR": str(plans),
    }
    if fake_agent:
        child_env["STUDYLOOP_TEST_AGENT_CMD"] = shlex.join(
            [sys.executable, str(_TEST_AGENT_SCRIPT), "{persona_file}"]
        )
    if path_prefix is not None:
        child_env["PATH"] = os.pathsep.join((str(path_prefix), child_env["PATH"]))
    if extra_env:
        child_env.update(extra_env)

    return TestWorld(
        root=root,
        cwd=root,
        home=home,
        tmp_dir=tmp_dir,
        vault=vault,
        config=config,
        session_db=session_db,
        session_dir=session_dir,
        plans=plans,
        port=port,
        env=MappingProxyType(child_env),
    )


def start_server(world: TestWorld, *, extra_args: list[str] | None = None) -> RunningServer:
    """Start a real server using only the world's explicit environment."""
    proc = start_web_server(world.port, env=world.env, cwd=world.cwd, extra_args=extra_args)
    return RunningServer(world=world, proc=proc)


def launch_env(
    root: Path,
    port: int,
    *,
    fake_agent: bool = False,
    plans_dir: Path | None = None,
    extra_args: list[str] | None = None,
) -> E2EEnv:
    """Build a hermetic world and start a server bound to it.

    ``STUDYLOOP_SESSION_DIR`` is redirected too: the live-session IPC files
    (state / topics / parking) otherwise live in the learner's real
    ``~/.config/studyloop`` and an e2e run would clobber an in-progress study
    session — and read its contents into test assertions.

    ``plans_dir`` redirects ``STUDYLOOP_PLANS_DIR`` for the same reason: study
    plans are files under the learner's real state dir, so a plans test would
    otherwise list, mutate, and delete their actual plans. Defaults to a
    directory under ``root`` so every caller is isolated whether it asks or not.

    ``extra_args`` is appended to the ``studyloop web`` command line — used to
    launch an experimental terminal renderer (``["--dev"]``, optionally with
    ``["--dev-engine", "ghostty"]``) so the UI can be asserted to say so.
    """
    world = build_test_world(root, port, fake_agent=fake_agent, plans_dir=plans_dir)
    server = start_server(world, extra_args=extra_args)
    return E2EEnv(
        base_url=server.base_url,
        port=port,
        vault=world.vault,
        config=world.config,
        proc=server.proc,
        session_dir=world.session_dir,
        env=dict(world.env),
        world=world,
        server=server,
    )


def shutdown(env: E2EEnv) -> None:
    if env.server is not None:
        env.server.stop()
        return
    env.proc.terminate()
    try:
        env.proc.wait(timeout=5)
    except Exception:  # pragma: no cover - defensive
        env.proc.kill()


# ---------------------------------------------------------------------------
# Browser diagnostics
# ---------------------------------------------------------------------------


class ConsoleWatch:
    """Collect console errors and uncaught page errors for a page.

    A silent JS exception is the most common cause of "the DOM node exists but
    nothing rendered", so render tests assert on this rather than trusting a
    visible-element check.
    """

    #: Noise that is not a product defect. Kept explicit and short — anything
    #: added here must be justified, or a real bug hides behind it.
    IGNORE = (
        "favicon",
        "net::ERR_ABORTED",
        "Failed to load resource: the server responded with a status of 404",
    )

    def __init__(self, page: Page) -> None:
        self.errors: list[str] = []
        #: Failed responses, recorded so a bare "Failed to load resource: 500"
        #: console line names its URL. Without this the most common browser
        #: failure is undebuggable from the log alone.
        self.failed_requests: list[str] = []
        page.on("console", self._on_console)
        page.on("pageerror", lambda e: self.errors.append(f"pageerror: {e}"))
        page.on("response", self._on_response)

    def _on_response(self, response) -> None:
        if response.status >= 500:
            self.failed_requests.append(f"HTTP {response.status} {response.url}")

    def _on_console(self, msg) -> None:
        if msg.type != "error":
            return
        text = msg.text
        if any(pat in text for pat in self.IGNORE):
            return
        self.errors.append(f"console.error: {text}")

    def assert_no_csp_violations(self) -> None:
        """Fail specifically if any captured console error is a CSP report.

        Distinct from ``assert_clean()`` (which fails on ANY console error,
        CSP violations included) so a Content-Security-Policy regression is
        diagnosed by name in its own assertion message, not lost inside a
        generic error list. This is the evidence for R-13's `script-src
        'self'` with no `'unsafe-inline'`/nonce exception (ttyd retirement
        stage 4): if either of the two inline `<script>` blocks that used to
        live in index.html ever came back, Chromium reports it as exactly
        this shape of console error, and this method names it.
        """
        violations = [e for e in self.errors if "Content Security Policy" in e or "Refused to" in e]
        assert not violations, "CSP violation(s) detected:\n" + "\n".join(
            f"  - {v}" for v in violations
        )

    def assert_clean(self, context: str) -> None:
        """Fail if the page saw a JS error OR the server returned a 5xx.

        The 5xx list used to be collected and then only interpolated into this
        assertion's message, so a server error with no accompanying JS error
        passed silently -- which is how a 500 on /api/session/state survived a
        run reported as fully green. Both are now failures, because a page that
        rendered from an error response is not a page that worked.
        """
        problems = [*self.errors, *self.failed_requests]
        if not problems:
            return
        detail = "\n".join(f"  - {p}" for p in problems)
        msg = f"browser or server errors while {context}:\n{detail}"
        raise AssertionError(msg)


def diag(page: Page | None, name: str, watch: ConsoleWatch | None = None) -> None:
    """Write screenshot + HTML + console log for a failing test."""
    if page is None:
        return
    RESULTS.mkdir(exist_ok=True)
    ts = int(time.time())
    try:
        page.screenshot(path=str(RESULTS / f"{name}-{ts}.png"), full_page=True)
        (RESULTS / f"{name}-{ts}.html").write_text(page.content(), encoding="utf-8")
        if watch is not None:
            (RESULTS / f"{name}-{ts}-console.json").write_text(
                json.dumps(
                    {"errors": watch.errors, "failed_requests": watch.failed_requests},
                    indent=2,
                ),
                encoding="utf-8",
            )
    except Exception:  # pragma: no cover - diagnostics must never mask the real failure
        pass


def goto_view(page: Page, view: str) -> None:
    """Navigate through the real Alpine nav store (hash routing is by design)."""
    page.wait_for_function("() => !!window.Alpine && !!window.Alpine.store('nav')", timeout=15000)
    page.evaluate("(v) => window.Alpine.store('nav').go(v)", view)
    page.wait_for_timeout(250)
