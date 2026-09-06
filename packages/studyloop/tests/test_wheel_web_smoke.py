"""Installed-wheel web smoke: the launcher must work from what users install.

The Second Brain launcher (resolver, `/api/second-brain/launch-target` route,
Today/Settings modules) is exercised everywhere else from the source checkout.
Nothing in those suites would notice a packaging defect -- a module missing
from the wheel, a static file excluded by a build rule, an app that cannot even
start outside the uv workspace. This smoke closes that gap the way a user
would hit it: build the wheel with ``--no-sources``, install ``studyloop[web]``
into an isolated venv OUTSIDE the checkout, start the installed application,
request launch state over real HTTP, and load every launcher asset the page
loads.

Slow: one wheel build, one venv, one server start. Marked ``integration`` so
it does not run in the default unit sweep; invoked from ``just smoke-web``
(called from ``just release-check``), mirroring test_wheel_extras_smoke.py.
"""

from __future__ import annotations

import json
import os
import posixpath
import re
import shutil
import socket
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]

# timeout(300): the module's first test pays for the wheel build plus a cold
# `uv pip install` of the web extra, which can exceed the suite's 60s default.
pytestmark = [pytest.mark.integration, pytest.mark.timeout(300)]

LAUNCH_TARGET_PATH = "/api/second-brain/launch-target"

#: The launcher's own modules: the walk over main.js's import graph must reach
#: both, or the packaged page renders without the launcher behavior.
LAUNCHER_MODULES = frozenset(
    {
        "/js/components/today-panel.js",
        "/js/components/settings-panel.js",
    }
)


@pytest.fixture(scope="module")
def built_wheel(tmp_path_factory: pytest.TempPathFactory) -> Path:
    if shutil.which("uv") is None:
        pytest.skip("uv is not on PATH, so the wheel cannot be built here")
    out = tmp_path_factory.mktemp("web-smoke-wheel")
    # --no-sources: build exactly what a real distribution would ship, same as
    # scripts/build-release.sh and test_wheel_extras_smoke.py.
    proc = subprocess.run(
        ["uv", "build", "--package", "studyloop", "--no-sources", "--wheel", "-o", str(out)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=300,
    )
    if proc.returncode != 0:
        pytest.fail(f"wheel build failed:\n{proc.stdout}\n{proc.stderr}")
    wheels = list(out.glob("studyloop-*.whl"))
    assert len(wheels) == 1, f"expected one wheel, got {wheels}"
    return wheels[0]


@pytest.fixture(scope="module")
def web_venv(built_wheel: Path, tmp_path_factory: pytest.TempPathFactory) -> Path:
    venv_dir = tmp_path_factory.mktemp("web-smoke-env") / "venv"
    assert not venv_dir.resolve().is_relative_to(REPO_ROOT), (
        "the smoke's venv must live outside the repository checkout; "
        f"got {venv_dir} under {REPO_ROOT}"
    )
    venv_proc = subprocess.run(
        ["uv", "venv", str(venv_dir)], capture_output=True, text=True, timeout=60
    )
    assert venv_proc.returncode == 0, f"uv venv failed:\n{venv_proc.stdout}\n{venv_proc.stderr}"
    python = venv_dir / "bin" / "python"
    install = subprocess.run(
        ["uv", "pip", "install", "--python", str(python), f"{built_wheel}[web]"],
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert install.returncode == 0, (
        f"installing studyloop[web] from the bare wheel failed:\n{install.stdout}\n{install.stderr}"
    )
    return venv_dir


@pytest.fixture(scope="module")
def web_app(web_venv: Path, tmp_path_factory: pytest.TempPathFactory):
    """The installed application, started the way a user starts it.

    ``<venv>/bin/studyloop web`` binds localhost on a free port with its
    config, session DB and state dir pointed at throwaway temp paths, so the
    smoke can never read or write real user state.
    """
    state_root = tmp_path_factory.mktemp("web-smoke-state")
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    env = {
        **os.environ,
        "STUDYLOOP_CONFIG": str(state_root / "config.yaml"),
        "STUDYLOOP_DB": str(state_root / "sessions.db"),
        "STUDYLOOP_STATE_DIR": str(state_root / "state"),
    }
    log_path = state_root / "server.log"
    with log_path.open("wb") as log:
        server = subprocess.Popen(
            [str(web_venv / "bin" / "studyloop"), "web", "--port", str(port)],
            cwd=state_root,
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
    base_url = f"http://127.0.0.1:{port}"
    try:
        deadline = time.monotonic() + 60
        while True:
            try:
                with urllib.request.urlopen(base_url + LAUNCH_TARGET_PATH, timeout=5):
                    break
            except (urllib.error.URLError, OSError):
                if server.poll() is not None or time.monotonic() > deadline:
                    pytest.fail(
                        "the installed web app did not start serving within 60s:\n"
                        + log_path.read_text(errors="replace")
                    )
                time.sleep(0.25)
        yield base_url
    finally:
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait(timeout=10)


def _get(base_url: str, path: str):
    """(status, case-insensitive headers, body) for one localhost GET."""
    with urllib.request.urlopen(base_url + path, timeout=10) as response:
        return response.status, response.headers, response.read()


def test_installed_studyloop_does_not_import_from_the_checkout(web_venv: Path) -> None:
    python = web_venv / "bin" / "python"
    check = subprocess.run(
        [str(python), "-c", "import studyloop; print(studyloop.__file__)"],
        capture_output=True,
        text=True,
        timeout=30,
        cwd=web_venv.parent,
    )
    assert check.returncode == 0, (
        f"import studyloop failed in the isolated venv:\n{check.stdout}\n{check.stderr}"
    )
    module_path = Path(check.stdout.strip()).resolve()
    assert module_path.is_relative_to(web_venv.resolve()), (
        f"studyloop imported from {module_path}, not from the isolated venv {web_venv}"
    )
    assert not module_path.is_relative_to(REPO_ROOT), (
        f"studyloop imported from the source checkout: {module_path}"
    )


def test_launch_target_route_responds_from_the_installed_app(web_app: str) -> None:
    status, headers, body = _get(web_app, LAUNCH_TARGET_PATH)

    assert status == 200
    assert headers.get("Cache-Control") == "no-store"
    target = json.loads(body)
    assert set(target) == {
        "provider",
        "label",
        "href",
        "enabled",
        "disabled_reason",
        "device_locality",
    }
    assert target["provider"] == "none"
    assert target["enabled"] is False


_IMPORT_SPECIFIER_RE = re.compile(r"^import\s+(?:[^'\"]*?from\s+)?['\"]([^'\"]+)['\"]", re.M)


def _module_imports(module_path: str, source: str) -> set[str]:
    """Absolute static-asset paths of a served module's relative imports."""
    base = posixpath.dirname(module_path)
    return {
        posixpath.normpath(posixpath.join(base, specifier))
        for specifier in _IMPORT_SPECIFIER_RE.findall(source)
        if specifier.startswith(".")
    }


def test_every_launcher_asset_is_served_from_the_wheel(web_app: str) -> None:
    status, _headers, body = _get(web_app, "/index.html")
    assert status == 200
    page = body.decode("utf-8")
    assert '<script type="module" src="/js/main.js">' in page, (
        "the packaged index.html no longer loads the module entry point"
    )

    served: dict[str, str] = {}
    pending = {"/js/main.js"}
    while pending:
        module_path = pending.pop()
        module_status, _module_headers, module_body = _get(web_app, module_path)
        assert module_status == 200, f"launcher module {module_path} is not served"
        assert module_body, f"launcher module {module_path} is served empty"
        served[module_path] = module_body.decode("utf-8")
        pending |= _module_imports(module_path, served[module_path]) - served.keys()

    missing = LAUNCHER_MODULES - served.keys()
    assert not missing, (
        f"main.js's import graph never reaches the launcher module(s) {sorted(missing)}; "
        f"served modules: {sorted(served)}"
    )
    for launcher_module in sorted(LAUNCHER_MODULES):
        assert LAUNCH_TARGET_PATH in served[launcher_module], (
            f"{launcher_module} no longer consumes {LAUNCH_TARGET_PATH}: "
            "the packaged page would render without launcher behavior"
        )
