"""R10: the fresh-install scope diagnostic survives a real wheel install.

``test_fresh_install_scope.py`` proves the fix against the source tree (the
editable dev venv's console scripts). Plan ruling R10 requires the same
virgin-HOME checks against an *installed build* -- ``uv build`` both
packages into a temp venv and run their real console scripts -- so a fix
that only patches a source-tree-only code path (or that a source-tree
test's own import machinery accidentally papers over) cannot hide the
defect again.

Mirrors ``test_wheel_extras_smoke.py``'s established wheel-build fixture and
venv-install pattern in this same package.

Slow (one wheel build for each package, one fresh venv, one dependency
resolve/install). Marked ``integration`` so it is not part of the default
unit sweep; run explicitly with:
    uv run pytest packages/studyloop/tests/test_fresh_install_scope_installed.py -m integration
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

pytest.importorskip("mcp")

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

REPO_ROOT = Path(__file__).resolve().parents[3]

pytestmark = pytest.mark.integration

SEVEN_TOOLS: tuple[tuple[str, dict], ...] = (
    ("log_struggle", {"question": "test question"}),
    ("get_study_backlog", {}),
    ("get_active_topics", {}),
    ("get_next_action", {}),
    ("record_topic_progress", {"topic_id": 1, "priority": 3}),
    ("get_concept_context", {"topic": "test"}),
    ("get_study_history", {"topic": "test"}),
)


@pytest.fixture(scope="module")
def installed_env(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A fresh venv with both release wheels installed (studyloop[mcp])."""
    if shutil.which("uv") is None:
        pytest.skip("uv is not on PATH, so the wheel cannot be built here")

    build_dir = tmp_path_factory.mktemp("fresh-install-scope-wheels")
    for package in ("studyloop", "agent-session-tools"):
        proc = subprocess.run(
            ["uv", "build", "--package", package, "--no-sources", "--wheel", "-o", str(build_dir)],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=300,
        )
        if proc.returncode != 0:
            pytest.fail(f"wheel build failed for {package}:\n{proc.stdout}\n{proc.stderr}")

    studyloop_wheels = list(build_dir.glob("studyloop-*.whl"))
    session_tools_wheels = list(build_dir.glob("agent_session_tools-*.whl"))
    assert len(studyloop_wheels) == 1, studyloop_wheels
    assert len(session_tools_wheels) == 1, session_tools_wheels

    venv_dir = tmp_path_factory.mktemp("fresh-install-scope-venv") / "venv"
    venv_proc = subprocess.run(
        ["uv", "venv", str(venv_dir)], capture_output=True, text=True, timeout=60
    )
    assert venv_proc.returncode == 0, f"uv venv failed:\n{venv_proc.stdout}\n{venv_proc.stderr}"
    python = venv_dir / "bin" / "python"

    install = subprocess.run(
        [
            "uv",
            "pip",
            "install",
            "--python",
            str(python),
            str(session_tools_wheels[0]),
            # tui: `studyloop study` drives a Textual sidebar even when a
            # topic is given on the command line, before it can reach the
            # scope check this test exists to prove.
            f"{studyloop_wheels[0]}[mcp,tui]",
        ],
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert install.returncode == 0, (
        f"installing the release wheel pair failed:\n{install.stdout}\n{install.stderr}"
    )
    return venv_dir


def _usable_path(venv_bin: Path, agent_bin: Path | None = None) -> str:
    real_path = os.environ.get("PATH", os.defpath)
    parts = (
        (str(agent_bin), str(venv_bin), *real_path.split(os.pathsep))
        if agent_bin
        else (str(venv_bin), *real_path.split(os.pathsep))
    )
    return os.pathsep.join(dict.fromkeys(parts))


def _fake_agent_bin(bin_dir: Path) -> Path:
    """Write a no-op executable named ``claude`` and return its containing dir.

    Mirrors ``test_fresh_install_scope.py``'s helper of the same name: the CLI
    refuses to start at all ("No AI agent found") unless ``detect_agents()``
    resolves a known agent binary via ``shutil.which`` on the subprocess's
    PATH, before the fresh-install scope check this suite exists to prove --
    so this must not depend on a real agent CLI being installed on whatever
    machine runs the test. The script is never actually executed.
    """
    bin_dir.mkdir(parents=True, exist_ok=True)
    fake_claude = bin_dir / "claude"
    fake_claude.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    fake_claude.chmod(0o755)
    return bin_dir


def _virgin_env(venv_dir: Path, home: Path, *, agent_bin: Path | None = None) -> dict[str, str]:
    home.mkdir(parents=True, exist_ok=True)
    return {
        "HOME": str(home),
        "PATH": _usable_path(venv_dir / "bin", agent_bin),
        "XDG_CONFIG_HOME": str(home / ".config"),
        "XDG_STATE_HOME": str(home / ".local" / "state"),
        "XDG_CACHE_HOME": str(home / ".cache"),
        "LANG": "C",
        "LC_ALL": "C",
        "NO_COLOR": "1",
        "TERM": "dumb",
        "TZ": "UTC",
        "PYTHONHASHSEED": "0",
    }


def _run_cli(venv_dir: Path, env: dict[str, str], *args: str) -> subprocess.CompletedProcess:
    studyloop = venv_dir / "bin" / "studyloop"
    assert studyloop.exists(), f"console script not found: {studyloop}"
    return subprocess.run(
        [str(studyloop), *args], env=env, capture_output=True, text=True, timeout=60
    )


async def _call_tool(venv_dir: Path, env: dict[str, str], module: str, tool: str, arguments: dict):
    python = venv_dir / "bin" / "python"
    params = StdioServerParameters(command=str(python), args=["-m", module], env=env)
    async with (
        stdio_client(params) as (read, write),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        return await session.call_tool(tool, arguments)


def _diagnostic_payload(result) -> dict:
    text = "".join(block.text for block in result.content if block.type == "text")
    assert "{" in text, f"no JSON payload found in isError text: {text!r}"
    return json.loads(text[text.index("{") :])


def test_installed_studyloop_study_exits_2_with_the_diagnostic(installed_env, tmp_path):
    agent_bin = _fake_agent_bin(tmp_path / "fake-agent-bin")
    env = _virgin_env(installed_env, tmp_path / "home", agent_bin=agent_bin)

    result = _run_cli(installed_env, env, "study", "Test Topic")

    assert result.returncode == 2, (result.stdout, result.stderr)
    assert "Traceback" not in result.stderr
    assert "No context scope configured" in result.stderr


@pytest.mark.parametrize("tool_name,arguments", SEVEN_TOOLS)
def test_installed_studyloop_mcp_tool_reports_the_diagnostic(
    installed_env, tmp_path, tool_name, arguments
):
    env = _virgin_env(installed_env, tmp_path / "home")

    result = asyncio.run(
        _call_tool(installed_env, env, "studyloop.mcp.server", tool_name, arguments)
    )

    assert result.isError, f"{tool_name} did not fail on an unconfigured scope"
    payload = _diagnostic_payload(result)
    assert payload["code"] == "scope_unconfigured"
    assert payload["remediation"]


def test_installed_session_search_reports_the_diagnostic(installed_env, tmp_path):
    env = _virgin_env(installed_env, tmp_path / "home")

    result = asyncio.run(
        _call_tool(
            installed_env, env, "agent_session_tools.mcp_server", "session_search", {"query": "x"}
        )
    )

    assert result.isError
    payload = _diagnostic_payload(result)
    assert payload["code"] == "scope_unconfigured"


def test_installed_generated_config_then_every_surface_succeeds(installed_env, tmp_path):
    home = tmp_path / "home"
    env = _virgin_env(installed_env, home)
    python = installed_env / "bin" / "python"

    generate_snippet = (
        "from studyloop.settings import generate_default_config; print(generate_default_config())"
    )
    generate = subprocess.run(
        [str(python), "-c", generate_snippet],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert generate.returncode == 0, (generate.stdout, generate.stderr)
    config_dir = home / ".config" / "studyloop"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "config.yaml").write_text(generate.stdout, encoding="utf-8")

    cli_result = _run_cli(installed_env, env, "resume")
    assert cli_result.returncode == 0, (cli_result.stdout, cli_result.stderr)
    assert "No context scope configured" not in cli_result.stderr

    tool_result = asyncio.run(
        _call_tool(installed_env, env, "studyloop.mcp.server", "get_active_topics", {})
    )
    assert not tool_result.isError, tool_result.content
