"""R-30 guard: the ``mcp[cli]`` dependency must carry an upper bound.

``mcp`` 2.x renamed ``FastMCP`` -- inspecting a real ``mcp-2.1.1`` wheel showed
``mcp/server/fastmcp.py`` is a stub whose only content is
``raise ModuleNotFoundError(...)``. ``uv.lock`` pins 1.29.1 today, so locked
installs are unaffected, but any *unlocked* resolution (a fresh
``uv tool install studyloop[mcp]`` once this is published, or a plain
``pip install``) could select 2.x and break the ``studyloop-mcp`` console
script at import. See agents/04-cli-settings.md F-03 / REPORT.md R-30.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]

_BOUND_RE = re.compile(r"^mcp\[cli\]>=1\.0\.0,<2$")


def test_package_mcp_extra_has_an_upper_bound() -> None:
    path = REPO_ROOT / "packages" / "studyloop" / "pyproject.toml"
    with path.open("rb") as pyproject_file:
        pyproject = tomllib.load(pyproject_file)
    specs = pyproject.get("project", {}).get("optional-dependencies", {}).get("mcp", [])
    assert any(_BOUND_RE.match(spec) for spec in specs), (
        f"expected 'mcp[cli]>=1.0.0,<2' in {path}'s [mcp] extra; got {specs}"
    )


def test_root_dev_group_mcp_dependency_has_an_upper_bound() -> None:
    path = REPO_ROOT / "pyproject.toml"
    with path.open("rb") as pyproject_file:
        pyproject = tomllib.load(pyproject_file)
    dev_group = pyproject.get("dependency-groups", {}).get("dev", [])
    assert any(_BOUND_RE.match(spec) for spec in dev_group if isinstance(spec, str)), (
        f"expected 'mcp[cli]>=1.0.0,<2' in {path}'s dev dependency group; got {dev_group}"
    )


def test_agent_session_tools_tts_extra_has_an_upper_bound() -> None:
    """Same defect class as the two above, in the sibling workspace package.

    Not named in REPORT.md's R-30 (which only cites packages/studyloop and the
    root), but this file is M5-owned per fixtures/lane_ownership.yaml and an
    unbounded ``mcp[cli]`` here would break the same way under an unlocked
    resolution of ``agent-session-tools[tts]``.
    """
    path = REPO_ROOT / "packages" / "agent-session-tools" / "pyproject.toml"
    with path.open("rb") as pyproject_file:
        pyproject = tomllib.load(pyproject_file)
    specs = pyproject.get("project", {}).get("optional-dependencies", {}).get("tts", [])
    assert any(_BOUND_RE.match(spec) for spec in specs), (
        f"expected 'mcp[cli]>=1.0.0,<2' in {path}'s [tts] extra; got {specs}"
    )
