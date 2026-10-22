"""Shared fixtures + utilities for Playwright UI tests (plan Test Strategy).

Not a pytest conftest — studyloop's ``tests/`` has no ``__init__.py`` so
plugin-level conftests collide with pluggy. Test files import the
helpers explicitly, following the precedent set in
``test_web_terminal.py`` and ``test_web_xterm_component.py``.
"""

from __future__ import annotations

import contextlib
import functools
import os
import secrets
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from collections.abc import Generator, Iterator, Mapping

    import requests
    from playwright.sync_api import Browser, BrowserContext, Page


# ---------------------------------------------------------------------------
# Child-process env isolation (C13/R-49g, council)
# ---------------------------------------------------------------------------
#
# The verifier's `just e2e` run on 1f544e7 created ~150 real directories
# under the developer's real ~/.config/studyloop/sessions/ and deleted the
# real session-oneline.txt. Root cause: several e2e/e2e-marked test files
# spawned a real `studyloop web` (or CLI) subprocess with `env=None` or
# `extra_env` merged over `os.environ` -- inheriting the developer's real
# HOME with no STUDYLOOP_SESSION_DIR override, so `session_state.SESSION_DIR`
# resolved to the real ~/.config/studyloop inside the spawned process.
# session/cleanup.py's own oneline.unlink() then deleted the real file the
# next time ANY session (in that unisolated process) ended.
#
# Fixed at the one choke point every such spawn should go through:
# `start_web_server`'s `extra_env` path now layers on an ISOLATED base
# (`_isolated_child_env`), not `os.environ`, and every path (`env=` too)
# is checked by `_refuse_if_env_reaches_real_dirs` before the subprocess
# ever starts -- a backstop for the day some other caller's `env=` has a
# gap, not just a fix for the one gap found here.


def _isolated_child_env(extra_env: Mapping[str, str] | None = None) -> dict[str, str]:
    """Build a hermetic child env for a spawned studyloop process.

    HOME/XDG_*/TMPDIR/STUDYLOOP_SESSION_DIR all point under a fresh,
    private temp directory -- never the developer's real ``~/.config``,
    ``~/.local/share``, or ``~/.cache``. ``PATH`` (and a couple of locale
    vars, when already set) are preserved from the real environment so
    real binaries (``tmux``, ``node``, ``uv``) are still found; everything
    else is built fresh rather than inherited, so a test that forgets to
    isolate some OTHER var cannot silently fall back to the developer's
    real one.

    ``extra_env`` is layered on top -- a caller's own explicit overrides
    (``STUDYLOOP_CONFIG``, ``STUDYLOOP_TEST_AGENT_CMD``, a caller-chosen
    ``STUDYLOOP_SESSION_DIR``, ...) always win over this base.
    """
    home = Path(tempfile.mkdtemp(prefix="studyloop-e2e-home-"))
    xdg_config = home / ".config"
    xdg_state = home / ".local" / "state"
    xdg_cache = home / ".cache"
    tmp_dir = home / "tmp"
    session_dir = xdg_config / "studyloop"
    for directory in (xdg_config, xdg_state, xdg_cache, tmp_dir, session_dir):
        directory.mkdir(parents=True, exist_ok=True)

    child_env = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": str(home),
        "TMPDIR": str(tmp_dir),
        "XDG_CONFIG_HOME": str(xdg_config),
        "XDG_STATE_HOME": str(xdg_state),
        "XDG_CACHE_HOME": str(xdg_cache),
        "STUDYLOOP_SESSION_DIR": str(session_dir),
        "LANG": os.environ.get("LANG", "C"),
        "LC_ALL": os.environ.get("LC_ALL", "C"),
        "NO_COLOR": "1",
        "TERM": "dumb",
        "PYTHONHASHSEED": "0",
        # The context system never infers a scope from a harness: without a
        # configured memory.default_scope a session/start raises ScopeError
        # (HTTP 409 context_scope_unavailable). The hermetic child gets no
        # real config, so classify it explicitly as unclassified — mirroring
        # conftest.py's in-process _isolate_memory_policy autouse fixture.
        "SESSION_CONTEXT_SCOPE": "unclassified",
    }
    # conftest.py sets these once, process-wide, to a tmp path (never the
    # developer's real sessions.db/state dir) via os.environ.setdefault --
    # the existing hermetic-DB net settings.get_db_path() relies on. Without
    # propagating them, a child that gets no explicit STUDYLOOP_CONFIG falls
    # through to its OWN, unrelated default under the fresh fake HOME above:
    # still safe (never real), but orphaned from the parent test process's
    # sessions.db, so an assertion made in-process (e.g.
    # get_last_study_session()) can never see what the child wrote.
    for shared_key in ("STUDYLOOP_DB", "STUDYLOOP_STATE_DIR"):
        if shared_value := os.environ.get(shared_key):
            child_env[shared_key] = shared_value
    if extra_env:
        child_env.update(extra_env)
    return child_env


def _refuse_if_env_reaches_real_dirs(child_env: dict[str, str]) -> None:
    """Raise if ``child_env`` would let a spawned process reach the
    developer's real config/session directories (C13/R-49g).

    Checked on EVERY spawn through :func:`start_web_server`, whether the
    caller passed ``env=`` (a complete, hermetic environment the caller
    built itself -- e.g. ``e2e._env.build_test_world``) or ``extra_env=``
    (now merged over :func:`_isolated_child_env`, not ``os.environ``) --
    this is the backstop for the day either path has a gap, not the
    primary defence.
    """
    real_home = os.path.realpath(str(Path.home()))
    home = child_env.get("HOME")
    if not home:
        msg = "start_web_server: child env has no HOME set -- refusing to spawn (C13/R-49g)"
        raise RuntimeError(msg)
    if os.path.realpath(home) == real_home:
        msg = (
            f"start_web_server: child env's HOME ({home!r}) is the developer's "
            "real home directory -- refusing to spawn a process that could "
            "read or write the real ~/.config/studyloop (C13/R-49g). Build the "
            "child env from an isolated base (e2e._env.build_test_world, or "
            "this module's _isolated_child_env) instead of inheriting "
            "os.environ wholesale."
        )
        raise RuntimeError(msg)

    real_session_dir = os.path.realpath(str(Path.home() / ".config" / "studyloop"))
    session_dir = child_env.get("STUDYLOOP_SESSION_DIR")
    if session_dir and os.path.realpath(session_dir) == real_session_dir:
        msg = (
            f"start_web_server: child env's STUDYLOOP_SESSION_DIR ({session_dir!r}) "
            "is the developer's real ~/.config/studyloop -- refusing to spawn "
            "(C13/R-49g)."
        )
        raise RuntimeError(msg)


def start_web_server(
    port: int,
    extra_env: dict[str, str] | None = None,
    *,
    env: Mapping[str, str] | None = None,
    cwd: Path | str | None = None,
    extra_args: list[str] | None = None,
) -> subprocess.Popen:
    """Spin up ``studyloop web`` on the given port. Returns the proc.

    Blocks until the server responds on ``/`` (or returns 401 when
    password protection is configured — still "up").

    Two mutually exclusive ways to give the child an environment:

    ``extra_env`` is merged *over* the inherited environment — the original
    contract, used by the older ``test_web_*`` modules and by the journey to
    inject the source-test agent command while selecting a release adapter.

    ``env`` replaces the environment *verbatim*, inheriting nothing. The e2e
    harness (``e2e/_env.py``) builds a complete ``TestWorld`` environment this
    way so a run cannot read or clobber the developer's real HOME, config,
    session DB or study plans. Passing both is a caller error, because the
    merge semantics would silently defeat that isolation.

    ``cwd`` sets the child's working directory (the world root, so relative
    paths resolve inside the temp world rather than the repo).

    ``extra_args`` is appended to the ``studyloop web`` command line — used to
    select an experimental terminal renderer, e.g. ``["--dev"]`` or
    ``["--dev-engine", "ghostty"]``.

    C13/R-49g: ``extra_env`` is now merged over :func:`_isolated_child_env`'s
    hermetic base, not ``os.environ`` -- the "original contract" this
    docstring used to describe (inheriting the real environment) is what
    let several callers spawn a real ``studyloop web`` against the
    developer's real ``~/.config/studyloop``. Every resulting ``child_env``,
    from either path, is checked by :func:`_refuse_if_env_reaches_real_dirs`
    before the subprocess starts.
    """
    if env is not None and extra_env is not None:
        msg = (
            "start_web_server: pass either env (complete, hermetic) or "
            "extra_env (merged over an isolated base), not both"
        )
        raise ValueError(msg)

    # Pre-flight: refuse to start if something is ALREADY serving this port.
    #
    # The readiness probe below cannot tell our child's response from another
    # process's. If a previous server leaked or two test files declare the same
    # port, the probe would accept the stranger's 200, hand back our (about to
    # die) child, and the test would drive the wrong server — passing or failing
    # for reasons that have nothing to do with it. Failing here names the real
    # problem instead.
    if not _port_is_free(port):
        msg = (
            f"port {port} is already being served before the child started. "
            "Either a previous server leaked, or two test modules declare this "
            "same port (see test_port_uniqueness). Refusing to continue: the "
            "readiness probe cannot distinguish that server from ours."
        )
        raise RuntimeError(msg)

    child_env = dict(env) if env is not None else _isolated_child_env(extra_env)
    _refuse_if_env_reaches_real_dirs(child_env)
    token = give_child_sign_in_token(child_env, port)
    cmd = [sys.executable, "-m", "studyloop.cli", "web", "--port", str(port)]
    if extra_args:
        cmd.extend(extra_args)

    # Capture the child's output to a file rather than discarding it.
    #
    # This used to be stderr=DEVNULL, which threw away every server-side
    # traceback. Two separate defects in this repo were diagnosable only from
    # output that had already been destroyed here: an "Errno 48 address already
    # in use" bind failure, and an HTTP 500 on /api/backlog whose traceback was
    # unrecoverable. A file (not a PIPE) because nobody drains a PIPE and a
    # chatty server would deadlock on a full buffer.
    log_fd, log_path = tempfile.mkstemp(prefix=f"studyloop-web-{port}-", suffix=".log")
    log_file = os.fdopen(log_fd, "w")

    proc = subprocess.Popen(
        cmd,
        stdout=log_file,
        stderr=subprocess.STDOUT,
        env=child_env,
        cwd=None if cwd is None else str(cwd),
    )
    # Discoverable by tests and by a failing teardown.
    proc.studyloop_log_path = log_path  # type: ignore[attr-defined]
    proc.studyloop_token = token  # type: ignore[attr-defined]
    # Every start path funnels through here, so registering the log at this one
    # point is what makes the per-test server-error check unbypassable.
    _register_server_log(log_path)
    # ...and registering the token here is what lets every client sign in
    # without each test file learning the bootstrap.
    register_server_token(port, token)

    def _fail(reason: str) -> RuntimeError:
        tail = _read_log_tail(log_path)
        return RuntimeError(f"{reason}\n--- server output ---\n{tail}")

    for _ in range(40):
        # A dead child can never become ready, and continuing to poll would let
        # an unrelated server on this port answer for it.
        exit_code = proc.poll()
        if exit_code is not None:
            raise _fail(f"studyloop web exited with code {exit_code} before serving port {port}")
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
    raise _fail(f"Web server failed to start on port {port} within 12s")


def _port_is_free(port: int) -> bool:
    """True when no process is currently listening on ``port``.

    ``SO_REUSEADDR`` is set deliberately: a socket left in ``TIME_WAIT`` by a
    just-stopped server is not a problem (uvicorn can still bind it), so it must
    not be reported as occupied. An active listener still refuses the bind,
    which is the case worth catching.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


# ---------------------------------------------------------------------------
# Signing clients in (F-WEB-20 follow-up; D2 bootstrap token, council pass 3)
# ---------------------------------------------------------------------------
#
# `studyloop web` mints a per-process secret; every /api/* request (403) and both
# WebSockets (1008) are refused without it as the HttpOnly `studyloop_auth`
# cookie. Since D2 the server hands that cookie only to a client presenting the
# secret as `/?token=<secret>` (303 + Set-Cookie); a bare `/` sets nothing. So a
# test needs the token, and `start_web_server` is where it comes from: it passes
# the child a token through STUDYLOOP_WEB_TOKEN, as the launcher does, and
# registers it here by port. Every helper below signs in through the server's
# real front door with it; they change nothing about the server.
#
# Out-of-band clients (urllib, requests, websockets) use server_cookie_header /
# server_opener / server_session. Playwright pages need nothing: importing this
# module wraps Page.goto so the first navigation of a context to a registered
# server signs that context in first (bootstrap_browser_context), exactly as the
# launcher's token URL does, and then navigates where the test asked.
#
# A server started some other way (its own Popen) has a token this process never
# saw: pass STUDYLOOP_WEB_TOKEN in its env and call register_server_token, or
# pass token= to the helpers. They refuse with a RuntimeError otherwise.
#
# Stateless per call: each helper call signs in afresh, so a server restarted on
# the same port (new process, new token, re-registered by start_web_server) is
# never answered with a stale cookie. Hold the returned opener/session for a
# series of calls to one server.

#: Sign-in token of every server this process started, by origin.
_SERVER_TOKENS: dict[str, str] = {}


def _origin(url: str) -> str:
    parts = urllib.parse.urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}".lower()


def register_server_token(port: int, token: str) -> None:
    """Record *token* as the sign-in token of the server listening on *port*."""
    for host in ("127.0.0.1", "localhost"):
        _SERVER_TOKENS[f"http://{host}:{port}"] = token


def give_child_sign_in_token(child_env: dict[str, str], port: int) -> str:
    """Put a sign-in token in *child_env* for the server about to listen on *port*.

    D2: the server hands its cookie only to a client presenting its token. This
    hands the child a token the way the launcher does and registers it, so this
    process knows it and every client here (urllib, requests, websockets, a
    Playwright page) signs in with it through the server's real front door. A
    token already in *child_env* wins. For the few tests that start
    ``studyloop web`` with their own ``Popen`` instead of :func:`start_web_server`.
    """
    from studyloop.web.ws_origin import BOOTSTRAP_TOKEN_ENV

    token = child_env.get(BOOTSTRAP_TOKEN_ENV) or secrets.token_urlsafe(32)
    child_env[BOOTSTRAP_TOKEN_ENV] = token
    register_server_token(port, token)
    return token


def server_token(base_url: str) -> str:
    """The sign-in token of the server at *base_url*; RuntimeError when unknown."""
    token = _SERVER_TOKENS.get(_origin(base_url))
    if token is None:
        msg = (
            f"no sign-in token is known for {_origin(base_url)}: start it with "
            "start_web_server (which registers one), or give the child "
            "STUDYLOOP_WEB_TOKEN and call register_server_token(port, token), or "
            "pass token= (D2: a bare GET / no longer hands out the server cookie)"
        )
        raise RuntimeError(msg)
    return token


def sign_in_url(base_url: str, *, token: str | None = None, path: str = "/") -> str:
    """The URL a browser opens to sign in, as ``studyloop web`` prints it."""
    from studyloop.web.ws_origin import BOOTSTRAP_QUERY

    token = token or server_token(base_url)
    query = urllib.parse.urlencode({BOOTSTRAP_QUERY: token})
    return f"{_origin(base_url)}{path}?{query}"


def _basic_auth_value(username: str, password: str) -> str:
    import base64

    return "Basic " + base64.b64encode(f"{username}:{password}".encode()).decode()


def server_cookie_header(
    base_url: str,
    *,
    basic_auth: tuple[str, str] | None = None,
    timeout: float = 10.0,
    token: str | None = None,
) -> str:
    """Sign in to the server at *base_url*; return its auth ``Cookie`` value.

    Loads the sign-in URL (``/?token=<token>``) and keeps the cookie the 303
    sets. *token* defaults to the one :func:`start_web_server` registered.

    The result is ``"studyloop_auth=<secret>"``: the value for a ``Cookie``
    header on a urllib ``Request``, a requests call, or
    ``websockets`` ``connect(additional_headers=...)``.

    *basic_auth* is ``(username, password)`` for a server running with LAN
    password protection, which answers 401 and sets no cookie without it.

    Raises ``RuntimeError`` when the sign-in sets no cookie. Every real
    ``studyloop web`` sets it for its own token, so its absence is a server
    regression and is reported as one here, rather than as a 403 on some later
    ``/api`` call.
    """
    import http.cookiejar

    from studyloop.web.ws_origin import AUTH_COOKIE

    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    request = urllib.request.Request(sign_in_url(base_url, token=token))
    if basic_auth is not None:
        request.add_header("Authorization", _basic_auth_value(*basic_auth))
    with opener.open(request, timeout=timeout) as response:
        response.read()
    for cookie in jar:
        if cookie.name == AUTH_COOKIE and cookie.value:
            return f"{AUTH_COOKIE}={cookie.value}"
    msg = (
        f"signing in at {_origin(base_url)}/?token=... set no {AUTH_COOKIE} cookie; a "
        "real `studyloop web` always sets it for its own token (BootstrapTokenMiddleware)"
    )
    raise RuntimeError(msg)


def server_opener(
    base_url: str,
    *,
    basic_auth: tuple[str, str] | None = None,
    timeout: float = 10.0,
    token: str | None = None,
) -> urllib.request.OpenerDirector:
    """A urllib opener that presents *base_url*'s server cookie on every request.

    Use ``server_opener(base).open(request, timeout=...)`` where a test would
    call ``urllib.request.urlopen(request, timeout=...)``; errors behave the same
    (``HTTPError`` on a 4xx/5xx). The headers go to every URL the opener opens,
    so use it only against the server it was built for.
    """
    opener = urllib.request.build_opener()
    cookie = server_cookie_header(base_url, basic_auth=basic_auth, timeout=timeout, token=token)
    headers = [("Cookie", cookie)]
    if basic_auth is not None:
        headers.append(("Authorization", _basic_auth_value(*basic_auth)))
    opener.addheaders = [*opener.addheaders, *headers]
    return opener


def server_session(
    base_url: str,
    *,
    basic_auth: tuple[str, str] | None = None,
    timeout: float = 10.0,
    token: str | None = None,
) -> requests.Session:
    """A ``requests.Session`` that presents *base_url*'s server cookie on every call."""
    import requests

    session = requests.Session()
    session.headers["Cookie"] = server_cookie_header(
        base_url, basic_auth=basic_auth, timeout=timeout, token=token
    )
    if basic_auth is not None:
        session.auth = basic_auth
    return session


def bootstrap_browser_context(
    context: BrowserContext, base_url: str, *, token: str | None = None
) -> None:
    """Sign a Playwright *context* in to the server at *base_url*.

    Requests the sign-in URL through ``context.request``, which shares the
    context's cookie store and HTTP credentials, so the server's own 303 sets
    the cookie in the browser exactly as following the launcher's URL does. A
    no-op when the context already holds this server's cookie.
    """
    from studyloop.web.ws_origin import AUTH_COOKIE

    origin = _origin(base_url)
    token = token or server_token(origin)

    def _signed_in() -> bool:
        return any(
            c.get("name") == AUTH_COOKIE and c.get("value") == token
            for c in context.cookies(origin)
        )

    if _signed_in():
        return
    response = context.request.get(sign_in_url(origin, token=token), max_redirects=0)
    try:
        status = response.status
    finally:
        response.dispose()
    if status != 303 or not _signed_in():
        msg = (
            f"signing a browser context in at {origin} answered {status} and set no "
            f"{AUTH_COOKIE} cookie (expected 303 + Set-Cookie). A 401 means the "
            "context needs http_credentials for a password-protected server."
        )
        raise RuntimeError(msg)


#: True inside :func:`browser_sign_in_paused`.
_SIGN_IN_PAUSED = False


@contextlib.contextmanager
def browser_sign_in_paused() -> Iterator[None]:
    """Let ``page.goto`` reach a registered server without signing in first.

    For tests of the sign-in itself: the bare page, the form, a wrong token.
    """
    global _SIGN_IN_PAUSED
    previous, _SIGN_IN_PAUSED = _SIGN_IN_PAUSED, True
    try:
        yield
    finally:
        _SIGN_IN_PAUSED = previous


def _install_page_goto_sign_in() -> None:
    """Wrap Playwright's ``Page.goto`` once per process (see the section comment).

    Only navigations to a server :func:`start_web_server` registered are touched,
    and only when the URL does not carry a token of its own.
    """
    try:
        from playwright.sync_api import Page as _Page
    except ImportError:  # pragma: no cover - playwright is a dev dependency
        return
    if getattr(_Page.goto, "_studyloop_sign_in", False):
        return
    original_goto = _Page.goto

    @functools.wraps(original_goto)
    def goto(self: Any, url: str, *args: Any, **kwargs: Any) -> Any:
        from studyloop.web.ws_origin import BOOTSTRAP_QUERY

        query = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
        if not _SIGN_IN_PAUSED and _origin(url) in _SERVER_TOKENS and BOOTSTRAP_QUERY not in query:
            bootstrap_browser_context(self.context, url)
        return original_goto(self, url, *args, **kwargs)

    goto._studyloop_sign_in = True  # type: ignore[attr-defined]
    _Page.goto = goto  # type: ignore[method-assign]


_install_page_goto_sign_in()


# ---------------------------------------------------------------------------
# Server-side failure detection
# ---------------------------------------------------------------------------

#: Captured log of every studyloop server started during this pytest run, mapped
#: to the offset already scanned. Registered by ``start_web_server`` itself,
#: which every start path funnels through: the fixture factories here, the e2e
#: world builder, the journey tests, and test classes that roll their own server
#: wrapper. Registering at the chokepoint rather than in each teardown means a
#: test cannot opt out of the check by bringing its own client or its own
#: process -- which is the point. The failure that motivated this scanned clean
#: through the browser-attached watcher because it drove the server with urllib.
_SERVER_LOGS: dict[str, int] = {}

#: uvicorn logs an unhandled route exception under this banner at ERROR level.
#: The servers run with log_level="warning", so access-log lines are absent and
#: a response status cannot be recovered from the log at all; ConsoleWatch
#: covers status codes for browser traffic, and the two are complementary
#: rather than redundant.
_ASGI_EXCEPTION_BANNER = "Exception in ASGI application"


def _register_server_log(path: str) -> None:
    _SERVER_LOGS.setdefault(path, 0)


def _summarise_asgi_failure(block: str, log_path: str) -> str:
    """One line naming the exception and the deepest studyloop frame."""
    lines = [ln for ln in block.splitlines() if ln.strip()]
    exception = "<no exception line found>"
    for line in lines:
        stripped = line.strip()
        # The traceback's final line is the exception; it is the only
        # non-indented, non-"File"/"Traceback" line in the block.
        if (
            stripped
            and not line.startswith((" ", "\t"))
            and not stripped.startswith(("File ", "Traceback"))
        ):
            exception = stripped
    frame = ""
    for line in lines:
        if 'File "' in line and "/studyloop/" in line and "site-packages" not in line:
            frame = line.strip()
    where = f" at {frame}" if frame else ""
    return f"server raised {exception}{where} (log: {log_path})"


def new_server_log_failures() -> list[str]:
    """Server-side failures logged since the previous call.

    Reads each log incrementally so a module- or session-scoped server is
    attributed to the test during which it actually failed, rather than to the
    first test that happened to touch it.
    """
    found: list[str] = []
    for path, offset in list(_SERVER_LOGS.items()):
        try:
            text = Path(path).read_text(errors="replace")
        except OSError:  # pragma: no cover - log removed under us
            continue
        _SERVER_LOGS[path] = len(text)
        fresh = text[offset:]
        if _ASGI_EXCEPTION_BANNER not in fresh:
            continue
        found.extend(
            _summarise_asgi_failure(block, path)
            for block in fresh.split(_ASGI_EXCEPTION_BANNER)[1:]
        )
    return found


def reset_server_log_tracking() -> None:
    """Forget every registered log. For tests of this mechanism itself."""
    _SERVER_LOGS.clear()


def _read_log_tail(log_path: str, limit: int = 4000) -> str:
    """Last ``limit`` characters of a captured server log, for error messages."""
    try:
        text = Path(log_path).read_text(errors="replace")
    except OSError as exc:  # pragma: no cover - defensive
        return f"<could not read {log_path}: {exc}>"
    if not text.strip():
        return "<server produced no output>"
    return text[-limit:]


def effective_credentials() -> tuple[str, str]:
    """Return (username, password) the CLI will use from config."""
    try:
        from studyloop.settings import load_settings

        settings = load_settings()
        return (settings.lan_username or "study", settings.lan_password or "")
    except Exception:
        return ("study", "")


def clean_ipc() -> None:
    """No-op kept for the ~35 existing call sites (C13/R-49g).

    This used to unlink ``session-state.json`` / ``session-topics.md`` /
    ``session-parking.md`` under the developer's REAL ``~/.config/studyloop``
    -- a leftover from when spawned servers inherited the real environment
    and shared that directory with the test process, so "stale IPC from an
    earlier run" was a real thing to clean up before asserting against a
    fresh server.

    Every server this helper module starts now gets its own hermetic,
    freshly-``mkdtemp``'d session directory (see ``_isolated_child_env``),
    so there is no shared real-directory IPC state left to go stale, and
    deleting the developer's real session files was never something a test
    should do. Kept as a callable no-op -- rather than deleted -- so none of
    the existing call sites need to change.
    """


# ---------------------------------------------------------------------------
# Pytest fixtures — import and use via e.g. ``from _playwright_helpers import
# web_server_fixture_factory; web_server = web_server_fixture_factory(19000)``.
# ---------------------------------------------------------------------------


def web_server_fixture_factory(port: int):
    """Return a pytest fixture that brings up a studyloop server on ``port``.

    Each test file typically uses a unique port to avoid conflicts when
    ``pytest -n`` is used. Wraps the lifecycle: clean IPC, start, yield,
    terminate, clean IPC.
    """

    @pytest.fixture()
    def _fixture() -> Generator[subprocess.Popen, None, None]:
        clean_ipc()
        proc = start_web_server(port)
        try:
            yield proc
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except Exception:
                proc.kill()
                proc.wait(timeout=5)
            clean_ipc()

    return _fixture


def auth_context_fixture_factory():
    """Return a pytest fixture that wraps browser in an auth-aware context."""

    @pytest.fixture()
    def _fixture(browser: Browser) -> Generator[BrowserContext, None, None]:
        user, password = effective_credentials()
        ctx_args = {}
        if password:
            ctx_args["http_credentials"] = {"username": user, "password": password}
        context = browser.new_context(**ctx_args)
        try:
            yield context
        finally:
            context.close()

    return _fixture


def web_page_fixture_factory(web_server_fixture_name: str, auth_fixture_name: str):
    """Return a pytest fixture that yields a Page backed by the given server.

    Parametrised by fixture names so each test file can wire the
    server+context pair it needs.
    """

    @pytest.fixture()
    def _fixture(request: pytest.FixtureRequest) -> Generator[Page, None, None]:
        request.getfixturevalue(web_server_fixture_name)
        context: BrowserContext = request.getfixturevalue(auth_fixture_name)
        page = context.new_page()
        try:
            yield page
        finally:
            page.close()

    return _fixture
