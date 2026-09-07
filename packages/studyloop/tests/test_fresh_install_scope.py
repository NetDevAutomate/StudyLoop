"""Fresh-install scope: one structured diagnostic everywhere ScopeError can surface.

TDD for SessionWeaver Phase 2 retrofit Task B1 ("Fresh-install scope"):
``openspec/changes/sessionweaver-phase2-retrofit/design.md`` and the
``configuration-and-secrets``/``mcp-server`` delta specs.

A virgin HOME has no ``~/.config/studyloop/config.yaml`` and no session
database. Before this fix:

- ``studyloop study`` exited 1 with a generic ``click.ClickException`` (or,
  for other call paths, an unhandled traceback).
- Each of the seven unguarded ``request_scope()`` MCP tool sites raised a
  bare ``ScopeError`` that FastMCP wrapped in ad-hoc text.
- ``session-db-mcp``'s ``open_context()``/``_get_connection()`` let a raw
  ``sqlite3.OperationalError`` ("unable to open database file") leak through
  a *different* generic wrapper.

Every check below runs as a real subprocess against a from-scratch HOME this
test builds (no ``STUDYLOOP_CONFIG``, no ``SESSION_CONTEXT_SCOPE``), so it
cannot be hidden by this suite's own autouse config-isolation fixtures.
``packages/studyloop/tests/conftest.py``'s ``_isolate_memory_policy`` forces
``SESSION_CONTEXT_SCOPE=unclassified`` for every *in-process* test, and
``packages/agent-session-tools/tests/conftest.py``'s
``_isolated_studyloop_config`` writes ``default_scope: unclassified`` for
every in-process agent-session-tools test -- exactly the fixture shape the
task brief says a regression test for this bug must not reuse. A real
subprocess never imports either conftest, so this suite proves the fix
independently of those fixtures. It mirrors an established pattern in this
package (see ``test_studyloop_stdio_history_keeps_scope_across_requests`` in
``test_context_consumer_scope.py`` and ``test_mcp_stdio_smoke.py``).

See also ``test_fresh_install_scope_installed.py`` for the package-installed
(built-wheel) variant of the same checks (plan ruling R10).
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

pytest.importorskip("mcp")

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

STUDYLOOP_TOOLS_TO_CHECK: tuple[tuple[str, dict], ...] = (
    ("log_struggle", {"question": "test question"}),
    ("get_study_backlog", {}),
    ("get_active_topics", {}),
    ("get_next_action", {}),
    ("record_topic_progress", {"topic_id": 1, "priority": 3}),
    ("get_concept_context", {"topic": "test"}),
    ("get_study_history", {"topic": "test"}),
)


def _usable_path() -> str:
    """This venv's own bin dir first, then the real PATH.

    ``studyloop study`` shells out to real system tools (tmux) whose install
    location is not predictable across machines/CI, so -- unlike the fully
    hermetic PATH some e2e fixtures build -- this inherits the calling
    shell's PATH rather than reconstructing a minimal one. HOME (not PATH) is
    what isolates this test from the learner's real config/database.
    """
    venv_bin = str(Path(sys.executable).parent)
    real_path = os.environ.get("PATH", os.defpath)
    return os.pathsep.join(dict.fromkeys((venv_bin, *real_path.split(os.pathsep))))


def _virgin_env(home: Path) -> dict[str, str]:
    """A from-scratch HOME with no config, no DB, no scope override.

    Deliberately omits STUDYLOOP_CONFIG, STUDYLOOP_DB, STUDYLOOP_STATE_DIR
    and SESSION_CONTEXT_SCOPE -- the exact absence this bug needs to
    reproduce, and the one the suite's own autouse fixtures paper over.
    """
    home.mkdir(parents=True, exist_ok=True)
    return {
        "HOME": str(home),
        "PATH": _usable_path(),
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


def _run_cli(env: dict[str, str], *args: str, timeout: int = 30) -> subprocess.CompletedProcess:
    # Deliberately NOT .resolve() -- a uv-managed venv's python is a symlink
    # into a shared toolchain install; resolving it would look for the
    # console script beside that shared binary instead of beside this
    # project's own .venv/bin, where it actually lives.
    studyloop = Path(sys.executable).parent / "studyloop"
    assert studyloop.exists(), f"console script not found: {studyloop}"
    return subprocess.run(
        [str(studyloop), *args],
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


async def _call_tool(env: dict[str, str], module: str, tool: str, arguments: dict):
    params = StdioServerParameters(command=sys.executable, args=["-m", module], env=env)
    async with (
        stdio_client(params) as (read, write),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        return await session.call_tool(tool, arguments)


def _diagnostic_payload(result) -> dict:
    """Extract the {code, message, remediation} dict from a tool's isError text.

    Both MCP stacks in this repo add their own generic prefix around a raised
    ToolError's message (studyloop-mcp: "Error executing tool X: ..."; the
    standalone fastmcp package used by session-db-mcp: none, for a re-raised
    FastMCPError) -- so the assertion locates the embedded JSON object rather
    than requiring an exact string match to either prefix.
    """
    text = "".join(block.text for block in result.content if block.type == "text")
    assert "{" in text, f"no JSON payload found in isError text: {text!r}"
    return json.loads(text[text.index("{") :])


# ---------------------------------------------------------------------------
# studyloop CLI
# ---------------------------------------------------------------------------


def test_studyloop_study_exits_2_with_the_diagnostic_on_a_virgin_home(tmp_path):
    env = _virgin_env(tmp_path / "home")

    result = _run_cli(env, "study", "Test Topic")

    assert result.returncode == 2, (result.stdout, result.stderr)
    assert "Traceback" not in result.stderr
    assert "No context scope configured" in result.stderr
    assert "memory.default_scope" in result.stderr


# ---------------------------------------------------------------------------
# studyloop-mcp: each of the seven previously-unguarded request_scope() sites
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("tool_name,arguments", STUDYLOOP_TOOLS_TO_CHECK)
def test_studyloop_mcp_tool_reports_the_diagnostic_on_a_virgin_home(tmp_path, tool_name, arguments):
    env = _virgin_env(tmp_path / "home")

    result = asyncio.run(_call_tool(env, "studyloop.mcp.server", tool_name, arguments))

    assert result.isError, f"{tool_name} did not fail on an unconfigured scope"
    payload = _diagnostic_payload(result)
    assert payload["code"] == "scope_unconfigured"
    assert payload["message"]
    assert payload["remediation"]
    text = "".join(block.text for block in result.content if block.type == "text")
    assert "Traceback" not in text


# ---------------------------------------------------------------------------
# session-db-mcp: session_search, plus open_context()'s missing-DB path via
# a memory_* tool
# ---------------------------------------------------------------------------


def test_session_search_reports_the_diagnostic_on_a_virgin_home(tmp_path):
    env = _virgin_env(tmp_path / "home")

    result = asyncio.run(
        _call_tool(env, "agent_session_tools.mcp_server", "session_search", {"query": "test"})
    )

    assert result.isError
    payload = _diagnostic_payload(result)
    assert payload["code"] == "scope_unconfigured"
    assert payload["remediation"]


def test_memory_search_reports_the_diagnostic_on_a_virgin_home(tmp_path):
    """open_context()'s missing-DB branch, exercised through the real server."""
    env = _virgin_env(tmp_path / "home")

    result = asyncio.run(
        _call_tool(env, "agent_session_tools.mcp_server", "memory_search", {"query": "test"})
    )

    assert result.isError
    payload = _diagnostic_payload(result)
    assert payload["code"] == "scope_unconfigured"
    assert "No session database found" in payload["message"]


# ---------------------------------------------------------------------------
# Round trip: after the config generator runs, every check above succeeds.
# ---------------------------------------------------------------------------


def test_generated_config_resolves_the_scope_and_every_surface_then_succeeds(tmp_path):
    """The other side of this bug: a fresh install that *did* run setup.

    Runs both packages' fresh-config writers, then re-drives the CLI and one
    MCP tool from each server against that generated file and asserts they
    no longer hit the diagnostic at all.
    """
    home = tmp_path / "home"
    env = _virgin_env(home)
    config_dir = home / ".config" / "studyloop"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / "config.yaml"

    from studyloop.settings import generate_default_config

    generated = generate_default_config()
    parsed = yaml.safe_load(generated)
    assert parsed["memory"]["default_scope"] == "unclassified"
    config_path.write_text(generated, encoding="utf-8")

    # generate_default_config()'s own `session_db: ~/.config/studyloop/
    # sessions.db` line already resolves to the same path as
    # agent-session-tools' independent DEFAULT_CONFIG database.path (the
    # packages deliberately don't share a config parser -- see
    # config_loader.py's module docstring) under this fake HOME, so both
    # loaders and both MCP servers agree on one database file without this
    # test having to force it.

    cli_result = _run_cli(env, "resume")
    assert cli_result.returncode == 0, (cli_result.stdout, cli_result.stderr)
    assert "No context scope configured" not in cli_result.stdout
    assert "No context scope configured" not in cli_result.stderr

    tool_result = asyncio.run(_call_tool(env, "studyloop.mcp.server", "get_active_topics", {}))
    assert not tool_result.isError, tool_result.content

    search_result = asyncio.run(
        _call_tool(env, "agent_session_tools.mcp_server", "session_search", {"query": "test"})
    )
    assert not search_result.isError, search_result.content
