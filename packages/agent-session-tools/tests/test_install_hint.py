"""The missing-runtime hint names the venv that raised it (issue #46 item 1).

``embedding_store.INSTALL_HINT`` was the literal
``uv tool install 'agent-session-tools[semantic]'`` wherever it was printed:
the warm's failure detail (the web header chip's tooltip), ``session-maint
embed`` and ``doctor``. That command installs into agent-session-tools' own
tool venv. The interpreter that raised the error is almost never that one --
``studyloop web`` runs in the ``studyloop`` tool venv, a developer's
``session-maint`` runs in the workspace ``.venv`` -- so following the hint
changed nothing the learner could see, and on one machine it sent the learner
to reinstall a tool venv that was already correct.

The hint is now computed from the interpreter's prefix and from where this
package's own source lives (an editable install points back at the checkout):
it names that prefix and a command, anchored to the checkout, that fixes it.
Council review 9 (A2) added the negative cases: a ``.venv`` beside a
non-workspace ``pyproject.toml`` is not the workspace, an unrelated or nested
venv under the uv tool dir is not an installer-managed tool, and the fallback
must target the named prefix rather than promise the tool installer repairs it.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from agent_session_tools import embedding_store

WORKSPACE_PYPROJECT = "[tool.uv.workspace]\nmembers = ['packages/*']\n"


def _checkout(root: Path) -> Path:
    """A directory shaped like a StudyLoop checkout, with its source tree."""
    (root / "packages" / "agent-session-tools" / "src" / "agent_session_tools").mkdir(
        parents=True
    )
    (root / "packages" / "agent-session-tools" / "pyproject.toml").write_text(
        "[project]\nname = 'agent-session-tools'\n"
    )
    (root / "pyproject.toml").write_text(WORKSPACE_PYPROJECT)
    (root / ".venv").mkdir()
    return root


@pytest.fixture
def uv_tool_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    tool_dir = tmp_path / "uv" / "tools"
    tool_dir.mkdir(parents=True)
    monkeypatch.setenv("UV_TOOL_DIR", str(tool_dir))
    return tool_dir


@pytest.fixture
def checkout(tmp_path: Path) -> Path:
    return _checkout(tmp_path / "studyloop")


def _hint(prefix: Path, checkout: Path | None) -> str:
    source = (
        checkout
        / "packages"
        / "agent-session-tools"
        / "src"
        / "agent_session_tools"
        / "x.py"
        if checkout
        else Path("/site-packages/agent_session_tools/x.py")
    )
    return embedding_store.install_hint(prefix, package_file=source)


class TestInstallerManagedToolVenvs:
    @pytest.mark.parametrize("tool", ["studyloop", "agent-session-tools"])
    def test_the_two_tool_venvs_get_the_tool_installer_anchored_to_the_checkout(
        self, uv_tool_dir: Path, checkout: Path, tool: str
    ):
        prefix = uv_tool_dir / tool
        prefix.mkdir()
        hint = _hint(prefix, checkout)
        assert str(prefix) in hint
        assert f"cd {checkout} && ./scripts/install.sh --tools-only" in hint
        assert "uv tool install 'agent-session-tools[semantic]'" not in hint

    def test_an_unrelated_tool_venv_is_not_claimed_by_the_installer(
        self, uv_tool_dir: Path, checkout: Path
    ):
        prefix = uv_tool_dir / "ruff"
        prefix.mkdir()
        hint = _hint(prefix, checkout)
        assert "install.sh --tools-only" not in hint
        assert str(prefix) in hint

    def test_a_nested_venv_under_the_tool_dir_is_not_claimed_either(
        self, uv_tool_dir: Path, checkout: Path
    ):
        prefix = uv_tool_dir / "studyloop" / "nested" / ".venv"
        prefix.mkdir(parents=True)
        hint = _hint(prefix, checkout)
        assert "install.sh --tools-only" not in hint
        assert str(prefix) in hint


class TestTheWorkspaceVenv:
    def test_the_checkouts_own_venv_gets_uv_sync_anchored_to_the_checkout(
        self, checkout: Path
    ):
        hint = _hint(checkout / ".venv", checkout)
        assert (
            f"cd {checkout} && uv sync --all-packages --group dev --extra semantic"
            in hint
        )
        assert str(checkout / ".venv") in hint
        assert "uv tool install" not in hint

    def test_a_venv_beside_a_non_workspace_pyproject_is_not_the_workspace(
        self, tmp_path: Path, checkout: Path
    ):
        other = tmp_path / "other-project"
        (other / ".venv").mkdir(parents=True)
        (other / "pyproject.toml").write_text("[project]\nname = 'other'\n")
        hint = _hint(other / ".venv", checkout)
        assert "uv sync" not in hint
        assert str(other / ".venv") in hint

    def test_a_venv_beside_some_other_uv_workspace_is_not_this_workspace(
        self, tmp_path: Path, checkout: Path
    ):
        other = tmp_path / "other-workspace"
        (other / ".venv").mkdir(parents=True)
        (other / "pyproject.toml").write_text(WORKSPACE_PYPROJECT)
        hint = _hint(other / ".venv", checkout)
        assert "uv sync" not in hint

    def test_the_workspace_is_recognised_by_shape_when_the_package_is_not_editable(
        self, checkout: Path
    ):
        """A wheel install in the workspace venv still gets the sync line: the
        venv's parent IS a StudyLoop checkout by shape (workspace table +
        packages/agent-session-tools)."""
        hint = _hint(checkout / ".venv", None)
        assert (
            f"cd {checkout} && uv sync --all-packages --group dev --extra semantic"
            in hint
        )


class TestAnyOtherInterpreter:
    def test_is_targeted_with_the_checkouts_package_path(
        self, tmp_path: Path, checkout: Path
    ):
        prefix = tmp_path / "somewhere" / "else"
        prefix.mkdir(parents=True)
        hint = _hint(prefix, checkout)
        assert (
            f"uv pip install --python {prefix} "
            f"'{checkout / 'packages' / 'agent-session-tools'}[semantic]'"
        ) in hint

    def test_without_a_known_checkout_the_path_is_an_explicit_placeholder(
        self, tmp_path: Path
    ):
        prefix = tmp_path / "somewhere" / "else"
        prefix.mkdir(parents=True)
        hint = _hint(prefix, None)
        assert f"uv pip install --python {prefix}" in hint
        assert "<StudyLoop checkout>/packages/agent-session-tools[semantic]" in hint
        assert "not published" in hint


def test_the_module_constant_is_the_hint_for_the_running_interpreter():
    assert embedding_store.INSTALL_HINT == embedding_store.install_hint(sys.prefix)
    assert sys.prefix in embedding_store.INSTALL_HINT


def test_this_checkout_is_found_from_the_installed_package():
    """The real package in this test run is an editable install from this checkout."""
    root = embedding_store._checkout_root(Path(embedding_store.__file__))
    assert root is not None
    assert (root / "packages" / "agent-session-tools" / "pyproject.toml").exists()
    assert (root / "scripts" / "install.sh").exists()


def test_uv_tool_dir_defaults_follow_uv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Without UV_TOOL_DIR, uv uses $XDG_DATA_HOME/uv/tools, else ~/.local/share/uv/tools."""
    monkeypatch.delenv("UV_TOOL_DIR", raising=False)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    assert embedding_store._uv_tool_dir() == tmp_path / "data" / "uv" / "tools"
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    assert (
        embedding_store._uv_tool_dir()
        == tmp_path / "home" / ".local" / "share" / "uv" / "tools"
    )
