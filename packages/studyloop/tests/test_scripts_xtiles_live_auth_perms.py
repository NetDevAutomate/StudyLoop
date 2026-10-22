"""The saved xTiles session is owner-only from its first byte. Plan 2, C5.

``scripts/xtiles-live-auth.py`` saves a signed-in browser session -- a
credential -- for the ``live_xtiles`` checks. It used to let Playwright's
``storage_state(path=...)`` create the file under the process umask (0644 under
the usual 022) and chmod it to 0600 afterwards, inside a parent directory
created 0755. For the moment between the write and the chmod, and for good if
the script died in between, any local user could read the session.

These tests run ``main()`` under umask 022 with Playwright replaced by a fake
whose ``storage_state(path=...)`` writes the file exactly as Playwright 1.58
does (``open(path, "w")``), and record the file's and directory's modes at the
moment credential bytes are written -- so a fix that tightens permissions after
writing still fails (the lane-4 ``test_maintenance_backup_perms.py`` approach).
"""

from __future__ import annotations

import builtins
import importlib.util
import json
import os
import stat
import sys
from contextlib import contextmanager
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

REPO_ROOT = Path(__file__).resolve().parents[3]
AUTH_SCRIPT = REPO_ROOT / "scripts" / "xtiles-live-auth.py"

#: What the fake browser context hands back as its storage state.
FAKE_STORAGE: dict[str, Any] = {
    "cookies": [{"name": "fake-session", "value": "not-a-real-cookie", "domain": "xtiles.app"}],
    "origins": [],
}


@pytest.fixture
def umask_022() -> Iterator[None]:
    previous = os.umask(0o022)
    try:
        yield
    finally:
        os.umask(previous)


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("xtiles_live_auth", AUTH_SCRIPT)
    assert spec and spec.loader, f"cannot load {AUTH_SCRIPT}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _FakePage:
    url = "https://xtiles.app/my/home"  # a SIGNED_IN_HINTS match on the first poll

    def goto(self, url: str, wait_until: str | None = None) -> None:
        pass

    def wait_for_timeout(self, timeout: float) -> None:
        pass


class _FakeContext:
    def new_page(self) -> _FakePage:
        return _FakePage()

    def storage_state(self, path: str | Path | None = None, **_: Any) -> dict[str, Any]:
        # playwright/_impl/_browser_context.py + _helper.async_writefile, 1.58.0
        if path:
            with open(path, "w") as fh:  # mirrors Playwright exactly
                fh.write(json.dumps(FAKE_STORAGE))
        return FAKE_STORAGE


class _FakeBrowser:
    def new_context(self) -> _FakeContext:
        return _FakeContext()

    def close(self) -> None:
        pass


@contextmanager
def _fake_sync_playwright() -> Iterator[SimpleNamespace]:
    yield SimpleNamespace(chromium=SimpleNamespace(launch=lambda **_: _FakeBrowser()))


class _WriteSpy:
    """Record the target's (file mode, parent mode) whenever bytes are written to it."""

    def __init__(self, target: Path) -> None:
        self.target = target
        self.at_write: list[tuple[int, int]] = []

    def note(self, fd: int) -> None:
        written = os.fstat(fd)
        try:
            target = os.stat(self.target)
        except FileNotFoundError:
            return
        if (written.st_dev, written.st_ino) == (target.st_dev, target.st_ino):
            self.at_write.append(
                (stat.S_IMODE(written.st_mode), _mode(self.target.parent)),
            )


class _SpiedFile:
    def __init__(self, fh: Any, spy: _WriteSpy) -> None:
        self._fh = fh
        self._spy = spy

    def write(self, data: Any) -> int:
        self._spy.note(self._fh.fileno())
        return self._fh.write(data)

    def __enter__(self) -> _SpiedFile:
        return self

    def __exit__(self, *exc: object) -> None:
        self._fh.__exit__(*exc)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._fh, name)


def _spied(real: Callable[..., Any], spy: _WriteSpy) -> Callable[..., Any]:
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        return _SpiedFile(real(*args, **kwargs), spy)

    return wrapper


def _run(monkeypatch: pytest.MonkeyPatch, state: Path) -> _WriteSpy:
    """Run the script's main() against the fake browser, spying every write path."""
    monkeypatch.setitem(
        sys.modules,
        "playwright.sync_api",
        SimpleNamespace(sync_playwright=_fake_sync_playwright),
    )
    script = _load_script()
    spy = _WriteSpy(state)
    real_write = os.write

    def spied_write(fd: int, data: bytes) -> int:
        spy.note(fd)
        return real_write(fd, data)

    monkeypatch.setattr(builtins, "open", _spied(builtins.open, spy))
    monkeypatch.setattr(os, "fdopen", _spied(os.fdopen, spy))
    monkeypatch.setattr(os, "write", spied_write)
    rc = script.main(["--state", str(state), "--timeout", "2"])
    monkeypatch.undo()
    assert rc == 0
    assert spy.at_write, "no write to the session file was observed"
    return spy


@pytest.mark.usefixtures("umask_022")
def test_session_file_is_owner_only_when_first_written(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = tmp_path / "cache" / "studyloop-live" / "xtiles-auth.json"
    spy = _run(monkeypatch, state)
    assert {oct(mode) for mode, _ in spy.at_write} == {"0o600"}
    assert _mode(state) == 0o600


@pytest.mark.usefixtures("umask_022")
def test_new_parent_directory_is_owner_only_before_the_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = tmp_path / "cache" / "studyloop-live" / "xtiles-auth.json"
    spy = _run(monkeypatch, state)
    assert {oct(parent) for _, parent in spy.at_write} == {"0o700"}


@pytest.mark.usefixtures("umask_022")
def test_existing_wider_session_file_is_tightened_before_the_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A rerun overwrites the old session; the new one must not land in a 0644 file."""
    state = tmp_path / "xtiles-auth.json"
    state.write_text("{}", encoding="utf-8")
    state.chmod(0o644)
    spy = _run(monkeypatch, state)
    assert {oct(mode) for mode, _ in spy.at_write} == {"0o600"}


@pytest.mark.usefixtures("umask_022")
def test_an_existing_directory_the_learner_chose_is_left_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``--state`` can point into any directory the learner owns; the script must
    not chmod someone's existing folder. The file inside it is still 0600."""
    chosen = tmp_path / "somewhere"
    chosen.mkdir(mode=0o755)
    state = chosen / "xtiles-auth.json"
    _run(monkeypatch, state)
    assert _mode(chosen) == 0o755
    assert _mode(state) == 0o600


@pytest.mark.usefixtures("umask_022")
def test_saved_file_is_the_storage_state_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The live checks load this file as Playwright storage state; a longer old
    session must not leave trailing bytes behind."""
    state = tmp_path / "xtiles-auth.json"
    state.write_text(json.dumps({"cookies": [], "origins": [], "pad": "x" * 4096}))
    _run(monkeypatch, state)
    assert json.loads(state.read_text(encoding="utf-8")) == FAKE_STORAGE
