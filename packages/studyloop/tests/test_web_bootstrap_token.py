"""The launcher-minted bootstrap token (D2, council pass 3, 2026-10-22).

Before D2 any process that could ``GET /`` was handed the server cookie, so the
cookie gate on ``/api/*`` and the terminal WebSocket stopped cross-site pages but
not a local process (lane-3 log of the 2026-10-21 review). Now, Jupyter-style:

- ``studyloop web`` mints the per-process secret (or takes it from the launcher
  through ``STUDYLOOP_WEB_TOKEN``) and prints the sign-in URL carrying it.
- ``GET /`` and ``GET /session`` set the cookie only when ``?token=<secret>`` is
  presented, then 303 to the same path without the token; a bare ``GET /`` from a
  browser without the cookie renders a small page asking for the token, whose
  form posts to the same acceptance.
- ``/api/*`` and both WebSockets keep requiring the cookie; the ``practice_check``
  hop keeps its own capability (pinned in ``test_web_security.py``).

Threat-model note (the ruling's): this closes "any process that can ``GET /``",
not "a process already running as the learner", which can read the launcher's
environment or the terminal.
"""

from __future__ import annotations

import logging
import re
import secrets
import socket
import threading
import time
import urllib.error
import urllib.request
from typing import TYPE_CHECKING, Any

import pytest
from fastapi.testclient import TestClient

from studyloop.web.app import create_app
from studyloop.web.ws_origin import AUTH_COOKIE, BOOTSTRAP_TOKEN_ENV

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

#: A well-formed secret, as ``secrets.token_urlsafe(32)`` mints it (43 chars).
SECRET = "k" * 43


def _client(**kwargs: Any) -> TestClient:
    return TestClient(create_app(server_secret=SECRET, **kwargs), follow_redirects=False)


def _is_token_page(response: Any) -> bool:
    return 'name="token"' in response.text and "<title>StudyLoop</title>" not in response.text


def _is_app_index(response: Any) -> bool:
    return "<title>StudyLoop</title>" in response.text


# ---------------------------------------------------------------------------
# The front door: GET /, GET /session, POST /
# ---------------------------------------------------------------------------


class TestBareFrontDoorIssuesNoCookie:
    def test_bare_get_slash_sets_no_cookie_and_asks_for_the_token(self) -> None:
        response = _client().get("/")

        assert "set-cookie" not in response.headers
        assert response.status_code == 200
        assert _is_token_page(response), response.text[:400]
        assert "no-store" in response.headers["cache-control"]

    def test_the_token_page_says_where_the_token_is_and_what_a_restart_does(self) -> None:
        text = _client().get("/").text
        assert "terminal" in text
        assert "restarted" in text
        # The form posts to the same acceptance; no script is needed (CSP has no inline).
        assert re.search(r'<form[^>]*method="post"[^>]*action="/"', text)
        assert "<script" not in text
        assert '<label for="token"' in text

    def test_a_cookied_browser_gets_the_app_and_no_new_cookie(self) -> None:
        client = _client()
        client.cookies.set(AUTH_COOKIE, SECRET)
        response = client.get("/")
        assert response.status_code == 200
        assert _is_app_index(response)
        assert "set-cookie" not in response.headers

    def test_a_stale_cookie_gets_the_token_page_not_the_app(self) -> None:
        client = _client()
        client.cookies.set(AUTH_COOKIE, "s" * 43)
        response = client.get("/")
        assert _is_token_page(response)
        assert "set-cookie" not in response.headers


class TestTokenAcceptance:
    def test_valid_token_sets_the_cookie_and_redirects_without_the_query(self) -> None:
        response = _client().get(f"/?token={SECRET}")

        assert response.status_code == 303
        assert response.headers["location"] == "/"
        set_cookie = response.headers["set-cookie"]
        assert set_cookie.startswith(f"{AUTH_COOKIE}={SECRET};")
        assert "httponly" in set_cookie.lower()
        assert "samesite=strict" in set_cookie.lower()
        assert "path=/" in set_cookie.lower()
        assert "no-store" in response.headers["cache-control"]

    def test_other_query_parameters_survive_the_redirect(self) -> None:
        response = _client().get(f"/?view=today&token={SECRET}&x=1")
        assert response.status_code == 303
        assert response.headers["location"] == "/?view=today&x=1"

    def test_the_launcher_path_session_is_accepted_and_keeps_its_path(self) -> None:
        response = _client().get(f"/session?token={SECRET}")
        assert response.status_code == 303
        assert response.headers["location"] == "/session"
        assert response.headers["set-cookie"].startswith(f"{AUTH_COOKIE}={SECRET};")

    @pytest.mark.parametrize("token", ["wrong", "", "k" * 42, "k" * 44, "caf%C3%A9"])
    def test_wrong_token_is_403_with_no_cookie_and_is_not_echoed(self, token: str) -> None:
        response = _client().get(f"/?token={token}")

        assert response.status_code == 403
        assert "set-cookie" not in response.headers
        assert _is_token_page(response)
        assert "no-store" in response.headers["cache-control"]
        if token:
            assert token not in response.text

    def test_a_repeated_token_parameter_is_refused(self) -> None:
        response = _client().get(f"/?token={SECRET}&token={SECRET}")
        assert response.status_code == 403
        assert "set-cookie" not in response.headers

    def test_the_form_post_accepts_the_token(self) -> None:
        response = _client().post("/", data={"token": SECRET})
        assert response.status_code == 303
        assert response.headers["location"] == "/"
        assert response.headers["set-cookie"].startswith(f"{AUTH_COOKIE}={SECRET};")
        assert "no-store" in response.headers["cache-control"]

    def test_the_form_post_accepts_the_whole_printed_url_pasted_in(self) -> None:
        pasted = f"  http://127.0.0.1:8567/?token={SECRET}\n"
        response = _client().post("/", data={"token": pasted})
        assert response.status_code == 303
        assert response.headers["set-cookie"].startswith(f"{AUTH_COOKIE}={SECRET};")

    def test_the_form_post_refuses_a_wrong_token(self) -> None:
        response = _client().post("/", data={"token": "wrong"})
        assert response.status_code == 403
        assert "set-cookie" not in response.headers
        assert _is_token_page(response)

    def test_an_oversized_form_post_is_refused_without_a_cookie(self) -> None:
        response = _client().post("/", data={"token": "x" * 10_000})
        assert response.status_code == 413
        assert "set-cookie" not in response.headers

    def test_the_cookie_from_the_token_opens_the_api_and_the_app(self) -> None:
        client = _client()
        client.get(f"/?token={SECRET}")
        assert client.get("/api/session/state").status_code == 200
        assert _is_app_index(client.get("/"))


class TestApiStillNeedsTheCookie:
    def test_uncookied_api_is_still_403(self) -> None:
        response = _client().get("/api/session/state")
        assert response.status_code == 403
        assert response.json()["code"] == "server_secret_required"

    def test_the_token_is_not_an_api_credential(self) -> None:
        """Only the front door accepts it; ``/api/*`` still wants the cookie."""
        response = _client().get(f"/api/session/state?token={SECRET}")
        assert response.status_code == 403
        assert "set-cookie" not in response.headers

    def test_in_process_create_app_without_a_secret_serves_the_app(self) -> None:
        """Embedding / in-process tests keep today's behaviour: no gate, no token page."""
        response = TestClient(create_app()).get("/")
        assert response.status_code == 200
        assert _is_app_index(response)


class TestBasicAuthStillComesFirst:
    """With a LAN password the token never stands in for it."""

    def test_token_without_basic_auth_is_401_and_issues_no_cookie(self) -> None:
        response = _client(password="pw").get(f"/?token={SECRET}")
        assert response.status_code == 401
        assert "set-cookie" not in response.headers

    def test_token_with_basic_auth_issues_the_cookie(self) -> None:
        response = _client(password="pw").get(f"/?token={SECRET}", auth=("study", "pw"))
        assert response.status_code == 303
        assert response.headers["set-cookie"].startswith(f"{AUTH_COOKIE}={SECRET};")


# ---------------------------------------------------------------------------
# The real command: env hand-off, printing, logging
# ---------------------------------------------------------------------------


def _run_studyloop_web(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, *args: str, token: str | None = None
) -> tuple[dict[str, Any], str]:
    """Run ``studyloop web`` up to the point it would serve; return what it would serve."""
    import uvicorn
    from click.testing import CliRunner

    from studyloop.cli import cli

    monkeypatch.setenv("STUDYLOOP_CONFIG", str(tmp_path / "config.yaml"))
    monkeypatch.delenv("STUDYLOOP_WEB_PASSWORD", raising=False)
    if token is None:
        monkeypatch.delenv(BOOTSTRAP_TOKEN_ENV, raising=False)
    else:
        monkeypatch.setenv(BOOTSTRAP_TOKEN_ENV, token)
    monkeypatch.setattr("studyloop.cli._web._candidate_lan_hosts", lambda: ("192.168.1.42",))
    captured: dict[str, Any] = {}

    def capture(server: Any, *_args: Any, **_kwargs: Any) -> None:
        import os

        captured["app"] = server.config.app
        captured["host"] = server.config.host
        captured["log_level"] = server.config.log_level
        captured["env_token_left"] = os.environ.get(BOOTSTRAP_TOKEN_ENV)

    monkeypatch.setattr(uvicorn.Server, "run", capture)
    result = CliRunner().invoke(cli, ["web", *args])
    captured["exit_code"] = result.exit_code
    return captured, result.output


class TestStudyloopWebCommand:
    def test_hand_run_prints_the_sign_in_url_with_the_token(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        captured, output = _run_studyloop_web(monkeypatch, tmp_path)
        assert captured["exit_code"] == 0, output
        match = re.search(r"http://127\.0\.0\.1:8567/\?token=([A-Za-z0-9_-]{32,})", output)
        assert match, output
        token = match.group(1)
        # Exactly once, and only inside the URL.
        assert output.count(token) == 1
        # The printed token is the one the server accepts.
        client = TestClient(captured["app"], follow_redirects=False)
        assert client.get(f"/?token={token}").status_code == 303
        assert client.cookies[AUTH_COOKIE] == token

    def test_each_process_mints_its_own_token(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        seen = set()
        for _ in range(2):
            _, output = _run_studyloop_web(monkeypatch, tmp_path)
            match = re.search(r"\?token=([A-Za-z0-9_-]{32,})", output)
            assert match, output
            seen.add(match.group(1))
        assert len(seen) == 2

    def test_launcher_token_from_env_is_used_and_scrubbed(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        launcher_token = "L" * 43
        captured, output = _run_studyloop_web(monkeypatch, tmp_path, token=launcher_token)
        assert captured["exit_code"] == 0, output
        assert captured["env_token_left"] is None, "the token must not stay in the environment"
        client = TestClient(captured["app"], follow_redirects=False)
        assert client.get(f"/?token={launcher_token}").status_code == 303

    @pytest.mark.parametrize("bad", ["short", "k" * 31, "k" * 40 + ";x=1", "k" * 40 + " sp"])
    def test_a_malformed_launcher_token_is_refused(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, bad: str
    ) -> None:
        captured, output = _run_studyloop_web(monkeypatch, tmp_path, token=bad)
        assert captured["exit_code"] != 0
        assert "app" not in captured, "a refused token must not reach a running server"
        assert BOOTSTRAP_TOKEN_ENV in output
        assert bad not in output

    def test_the_server_logs_at_warning(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """The precondition of the log test below: the real command configures WARNING (V7)."""
        captured, _ = _run_studyloop_web(monkeypatch, tmp_path)
        assert captured["log_level"] == "warning"


class _RecordingHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.NOTSET)
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


@pytest.fixture()
def real_server() -> Generator[Any, None, None]:
    """Serve ``create_app(server_secret=SECRET)`` over loopback with uvicorn's own logging."""
    import uvicorn

    running: list[tuple[uvicorn.Server, threading.Thread]] = []
    saved_root = logging.getLogger().level

    def _serve(*, log_level: str) -> tuple[str, _RecordingHandler]:
        app = create_app(server_secret=SECRET)
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        # Config() applies uvicorn's logging config, as the real command's does.
        config = uvicorn.Config(app, log_level=log_level, lifespan="off")
        handler = _RecordingHandler()
        logging.getLogger().setLevel(logging.WARNING)  # the CLI configures no root level
        for name in ("", "uvicorn", "uvicorn.error", "uvicorn.access", "uvicorn.asgi"):
            logging.getLogger(name).addHandler(handler)
        server = uvicorn.Server(config)
        thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
        thread.start()
        running.append((server, thread))
        deadline = time.monotonic() + 10
        while not server.started:
            if time.monotonic() > deadline:
                raise RuntimeError("uvicorn did not start within 10s")
            time.sleep(0.02)
        return f"http://127.0.0.1:{port}", handler

    try:
        yield _serve
    finally:
        for server, thread in running:
            server.should_exit = True
            thread.join(timeout=10)
        for name in ("", "uvicorn", "uvicorn.error", "uvicorn.access", "uvicorn.asgi"):
            logger = logging.getLogger(name)
            for handler in list(logger.handlers):
                if isinstance(handler, _RecordingHandler):
                    logger.removeHandler(handler)
        logging.getLogger().setLevel(saved_root)


def _bootstrap_over_the_wire(base: str) -> int:
    class _NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *_args: Any, **_kwargs: Any) -> None:
            return None

    opener = urllib.request.build_opener(_NoRedirect())
    try:
        with opener.open(f"{base}/?token={SECRET}", timeout=5) as response:
            return response.status
    except urllib.error.HTTPError as exc:
        return exc.code


class TestTokenNeverLogged:
    def test_a_bootstrap_request_leaves_no_trace_of_the_token_at_warning(
        self, real_server: Any
    ) -> None:
        base, handler = real_server(log_level="warning")
        assert _bootstrap_over_the_wire(base) == 303
        assert not [m for m in handler.messages if SECRET in m], handler.messages

    def test_positive_control_the_capture_would_see_an_access_log_line(
        self, real_server: Any
    ) -> None:
        """At INFO uvicorn logs the request line, query string included: the capture works,
        so the WARNING test above is not passing vacuously."""
        base, handler = real_server(log_level="info")
        assert _bootstrap_over_the_wire(base) == 303
        assert [m for m in handler.messages if SECRET in m], handler.messages


# ---------------------------------------------------------------------------
# The launcher
# ---------------------------------------------------------------------------


class TestLauncherHandsOffTheToken:
    def _launch(self, monkeypatch: pytest.MonkeyPatch, **kwargs: Any) -> dict[str, Any]:
        from studyloop.session import orchestrator

        seen: dict[str, Any] = {}

        class _Proc:
            pid = 4242

        def fake_popen(cmd: list[str], **popen_kwargs: Any) -> _Proc:
            seen["cmd"] = [str(part) for part in cmd]
            seen["env"] = popen_kwargs.get("env")
            return _Proc()

        def fake_open_browser(url: str, **open_kwargs: Any) -> None:
            seen["url"] = url
            seen["ready_url"] = open_kwargs.get("ready_url")

        monkeypatch.setattr(orchestrator, "_kill_port_occupant", lambda *a, **k: None)
        monkeypatch.setattr(orchestrator, "_get_web_port", lambda: 8567)
        monkeypatch.setattr(orchestrator.subprocess, "Popen", fake_popen)
        monkeypatch.setattr(orchestrator, "_open_browser", fake_open_browser)
        monkeypatch.setattr("studyloop.session_state.write_session_state", lambda *_a: None)
        orchestrator.start_web_background("study-test", **kwargs)
        return seen

    def test_token_goes_by_environment_and_the_browser_opens_the_token_url(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen = self._launch(monkeypatch)
        token = seen["env"][BOOTSTRAP_TOKEN_ENV]
        assert re.fullmatch(r"[A-Za-z0-9_-]{32,}", token)
        assert all(token not in part for part in seen["cmd"]), seen["cmd"]
        assert seen["url"] == f"http://127.0.0.1:8567/session?token={token}"
        # Readiness is polled on a token-free URL.
        assert seen["ready_url"] == "http://127.0.0.1:8567/"

    def test_each_launch_mints_a_new_token(self, monkeypatch: pytest.MonkeyPatch) -> None:
        first = self._launch(monkeypatch)["env"][BOOTSTRAP_TOKEN_ENV]
        second = self._launch(monkeypatch)["env"][BOOTSTRAP_TOKEN_ENV]
        assert first != second

    def test_password_still_goes_by_environment_beside_the_token(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        credential = secrets.token_urlsafe(12)
        seen = self._launch(monkeypatch, lan=True, password=credential)
        assert seen["env"]["STUDYLOOP_WEB_PASSWORD"] == credential
        assert BOOTSTRAP_TOKEN_ENV in seen["env"]

    def test_the_sign_in_url_is_printed_so_a_closed_tab_can_be_reopened(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        printed: list[str] = []

        class _Console:
            def print(self, *args: Any, **_kwargs: Any) -> None:
                printed.append(" ".join(str(a) for a in args))

        monkeypatch.setattr("studyloop.output.console", _Console())
        seen = self._launch(monkeypatch)
        assert any(seen["url"] in line for line in printed), printed


# ---------------------------------------------------------------------------
# A real `studyloop web` and a real browser (e2e; run by `just e2e`)
# ---------------------------------------------------------------------------


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


@pytest.fixture()
def live_server() -> Generator[str, None, None]:
    from _playwright_helpers import start_web_server

    port = _free_port()
    proc = start_web_server(port)
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.kill()
            proc.wait(timeout=5)
        log = getattr(proc, "studyloop_log_path", None)
        if log:
            from pathlib import Path

            token = getattr(proc, "studyloop_token", "")
            # The server's whole stdout+stderr: the token is there exactly once,
            # in the startup sign-in URL, and in no request log line.
            assert token
            assert Path(log).read_text(errors="replace").count(token) == 1


def _api_status_from_page(page: Any) -> int:
    return page.evaluate(
        "async () => (await fetch('/api/session/state', {cache: 'no-store'})).status"
    )


@pytest.mark.e2e
class TestRealBrowserSignIn:
    def test_the_launcher_url_signs_the_browser_in_and_leaves_no_token_in_the_address(
        self, live_server: str, browser: Any
    ) -> None:
        from _playwright_helpers import browser_sign_in_paused, sign_in_url

        context = browser.new_context()
        try:
            page = context.new_page()
            with browser_sign_in_paused():
                page.goto(sign_in_url(live_server, path="/session"))
            page.wait_for_load_state("load")
            assert "token" not in page.url
            assert page.url.startswith(f"{live_server}/")
            assert page.title() == "StudyLoop"
            assert _api_status_from_page(page) == 200
        finally:
            context.close()

    def test_a_bare_visit_gets_the_sign_in_page_and_the_form_signs_in(
        self, live_server: str, browser: Any
    ) -> None:
        from _playwright_helpers import browser_sign_in_paused, server_token

        context = browser.new_context()
        try:
            page = context.new_page()
            with browser_sign_in_paused():
                page.goto(f"{live_server}/")
            assert page.title() != "StudyLoop"
            assert context.cookies(live_server) == []
            assert _api_status_from_page(page) == 403

            page.fill("#token", "not-the-token")
            page.click("button[type=submit]")
            assert page.locator("[role=alert]").is_visible()
            assert context.cookies(live_server) == []

            page.fill("#token", server_token(live_server))
            page.click("button[type=submit]")
            page.wait_for_load_state("load")
            assert page.title() == "StudyLoop"
            assert _api_status_from_page(page) == 200
        finally:
            context.close()

    def test_the_helpers_page_goto_signs_a_fresh_context_in(
        self, live_server: str, browser: Any
    ) -> None:
        """What every other browser test now relies on: a plain goto just works."""
        context = browser.new_context()
        try:
            page = context.new_page()
            page.goto(f"{live_server}/#today")
            assert page.title() == "StudyLoop"
            assert page.url == f"{live_server}/#today"
            assert _api_status_from_page(page) == 200
        finally:
            context.close()
