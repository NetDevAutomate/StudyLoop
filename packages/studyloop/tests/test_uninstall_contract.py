"""``studyloop install agents --uninstall`` removes what install added, and only that.

Install wires each harness three ways beyond its agent-definition links: a
session-export steering mandate, a native session-end hook (Claude Stop, Codex
and Grok SessionEnd) and both StudyLoop MCP servers. Uninstall used to skip all
three (``installers.install_agent_definitions`` wrapped them in
``if not uninstall``), so after a "clean removal" every harness still ran
``session-export`` at session end and still launched StudyLoop's MCP servers
(review F-OPS-02).

Every test runs against a sandbox HOME and a sandbox copy of the repository's
``agents/`` tree: Codex and Grok install a ``{repo_root}/AGENTS.md`` link, and
uninstall would delete the real repository's tracked one. A guard refuses to
run the installer at all if any path it would write is outside ``tmp_path``.
"""

from __future__ import annotations

import json
import os
import shutil
import tomllib
from dataclasses import dataclass
from pathlib import Path

import pytest

import studyloop.installers as installers
from studyloop.harnesses import RELEASE_HARNESSES

_OWNED_MCP = ("session-db", "studyloop")
_EXPORT_HOOK_MARKERS = (
    "session-export --claude-only",
    "session-export --codex-only",
    "session-export --grok-only",
)

# What the learner had before StudyLoop arrived. JSON hook files are planted in
# the shape install itself writes back (``json.dumps(indent=2)``), so a correct
# uninstall returns each to these exact bytes. The MCP configs are planted in
# hand-tuned shapes install's byte-preserving merge keeps, including a
# non-ASCII key a reserialising writer would escape.
_USER_STOP_GROUP = {"matcher": "", "hooks": [{"type": "command", "command": "echo user-stop"}]}
_USER_CODEX_GROUP = {"hooks": [{"type": "command", "command": "echo user-end", "timeout": 5}]}
_USER_CLAUDE_SETTINGS = (
    json.dumps({"theme": "dark", "hooks": {"Stop": [_USER_STOP_GROUP]}}, indent=2) + "\n"
)
_USER_CODEX_HOOKS = json.dumps({"hooks": {"SessionEnd": [_USER_CODEX_GROUP]}}, indent=2) + "\n"
_USER_GROK_HOOKS = json.dumps({"hooks": {"SessionEnd": [_USER_CODEX_GROUP]}}, indent=2) + "\n"
_USER_CLAUDE_MCP_ENTRY = '"user-server": {"command": "user-mcp", "args": ["--flag"]}'
_USER_CLAUDE_JSON = (
    "{\n"
    '    "numStartups": 3,\n'
    '    "mcpServers": {\n'
    f"        {_USER_CLAUDE_MCP_ENTRY}\n"
    "    },\n"
    '    "projects": {"/Users/l\u00e9a/notes": {"allowedTools": []}}\n'
    "}\n"
)
_USER_OPENCODE_JSON = (
    json.dumps(
        {
            "theme": "keep",
            "mcp": {"user-server": {"command": ["user-mcp"], "enabled": True, "type": "local"}},
        },
        indent=2,
    )
    + "\n"
)
_USER_CODEX_TOML = 'model = "o3"\n\n[mcp_servers.user-server]\ncommand = "user-mcp"\nargs = []\n'
_USER_STEERING = "# my own steering\n"

# A stand-in for the `grok` CLI: `mcp add ... <name> <command>` and
# `mcp remove <name>` against a one-name-per-line registry. Exits 1 for an add
# that already exists or a remove that does not, as a real CLI would.
_FAKE_GROK = """#!/bin/sh
reg="{registry}"
touch "$reg"
if [ "$1" = mcp ] && [ "$2" = add ]; then
  name="$7"
  if grep -qx "$name" "$reg"; then exit 1; fi
  echo "$name" >> "$reg"
  exit 0
fi
if [ "$1" = mcp ] && [ "$2" = remove ]; then
  name="$3"
  if ! grep -qx "$name" "$reg"; then exit 1; fi
  grep -vx "$name" "$reg" > "$reg.tmp" || true
  mv "$reg.tmp" "$reg"
  exit 0
fi
exit 2
"""


def _repo_root() -> Path:
    root = Path(__file__).resolve()
    while root != root.parent and not (root / "agents" / "manifest.json").exists():
        root = root.parent
    assert (root / "agents" / "manifest.json").exists()
    return root


@dataclass(frozen=True)
class Sandbox:
    root: Path
    home: Path
    repo: Path
    grok_home: Path
    grok_registry: Path

    @property
    def planted(self) -> dict[Path, str]:
        return {
            self.home / ".claude/settings.json": _USER_CLAUDE_SETTINGS,
            self.home / ".codex/hooks.json": _USER_CODEX_HOOKS,
            self.grok_home / "hooks/user.json": _USER_GROK_HOOKS,
            self.home / ".claude.json": _USER_CLAUDE_JSON,
            self.home / ".config/opencode/opencode.json": _USER_OPENCODE_JSON,
            self.home / ".codex/config.toml": _USER_CODEX_TOML,
            self.home / ".kiro/steering/user.md": _USER_STEERING,
            self.grok_registry: "user-server\n",
        }

    def install(self) -> dict[str, int]:
        return installers.install_agent_definitions(self.repo, tools=list(RELEASE_HARNESSES))

    def uninstall(self) -> dict[str, int]:
        return installers.install_agent_definitions(
            self.repo, tools=list(RELEASE_HARNESSES), uninstall=True
        )

    def snapshot(self) -> dict[str, bytes | str]:
        """Every file and link under the sandbox, by relative path."""
        state: dict[str, bytes | str] = {}
        for path in sorted(self.root.rglob("*")):
            rel = str(path.relative_to(self.root))
            if path.is_symlink():
                state[rel] = "-> " + os.readlink(path)
            elif path.is_file():
                state[rel] = path.read_bytes()
        return state


@pytest.fixture
def sandbox(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Sandbox:
    real_home = str(installers._HOME)
    home = tmp_path / "home"
    repo = tmp_path / "repo"
    grok_home = home / ".grok"
    home.mkdir()
    shutil.copytree(_repo_root() / "agents", repo / "agents", symlinks=True)

    def rebase(value: str) -> str:
        return str(home) + value[len(real_home) :] if value.startswith(real_home) else value

    def rebase_spec(spec: installers.LinkSpec) -> installers.LinkSpec:
        return installers.LinkSpec(rebase(spec.source), rebase(spec.target), copy=spec.copy)

    monkeypatch.setattr(installers, "_HOME", home)
    monkeypatch.setenv("GROK_HOME", str(grok_home))
    monkeypatch.setattr(
        installers,
        "_TOOL_LINKS",
        {
            tool: tuple(rebase_spec(spec) for spec in specs)
            for tool, specs in installers._TOOL_LINKS.items()
        },
    )
    monkeypatch.setattr(
        installers, "_SHARED_LINKS", tuple(rebase_spec(s) for s in installers._SHARED_LINKS)
    )
    for table in ("XTILES_SKILL_LINKS", "SESSION_MEMORY_SKILL_LINKS"):
        monkeypatch.setattr(
            installers,
            table,
            {tool: rebase_spec(spec) for tool, spec in getattr(installers, table).items()},
        )
    # Grok's steering path was resolved from $GROK_HOME at import, not from _HOME.
    exports = {
        tool: installers._HarnessExport(Path(rebase(str(spec.steering_path))), spec.export_flag)
        for tool, spec in installers._HARNESS_EXPORT.items()
    }
    exports["grok"] = installers._HarnessExport(grok_home / "rules/session-db.md", "grok-only")
    monkeypatch.setattr(installers, "_HARNESS_EXPORT", exports)
    monkeypatch.setattr(installers, "uv_tool_bin_dir", lambda: None)

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    registry = tmp_path / "grok-mcp.txt"
    fake_grok = bin_dir / "grok"
    fake_grok.write_text(_FAKE_GROK.format(registry=registry), encoding="utf-8")
    fake_grok.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}/usr/bin{os.pathsep}/bin")

    # Sandbox-escape guard: every path the installer writes must be ours.
    written = [
        installers._render_target(spec.target, repo)
        for specs in (
            installers._SHARED_LINKS,
            *installers._TOOL_LINKS.values(),
            tuple(installers.XTILES_SKILL_LINKS.values()),
            tuple(installers.SESSION_MEMORY_SKILL_LINKS.values()),
        )
        for spec in specs
    ]
    written += [spec.steering_path for spec in installers._HARNESS_EXPORT.values()]
    written += [installers._mcp_config_path(t) for t in ("claude", "kiro", "codex", "opencode")]
    written += [installers._codex_hooks_path(), installers._grok_hooks_path()]
    written += [home / ".claude/settings.json", home / ".claude/study-statusline.sh"]
    assert shutil.which("grok") == str(fake_grok)
    escaping = sorted(str(p) for p in written if not Path(p).resolve().is_relative_to(tmp_path))
    assert escaping == [], f"installer would write outside the sandbox: {escaping}"

    box = Sandbox(tmp_path, home, repo, grok_home, registry)
    for path, text in box.planted.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return box


def _owned_residue(box: Sandbox) -> list[str]:
    """Every StudyLoop-owned hook, mandate, MCP entry or link still present."""
    found: list[str] = []
    for path in sorted(box.home.rglob("*")):
        rel = path.relative_to(box.home)
        if path.is_symlink():
            if Path(os.readlink(path)).is_relative_to(box.root):
                found.append(f"link {rel}")
            continue
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if installers._MANDATE_SENTINEL in text:
            found.append(f"mandate {rel}")
        found += [f"hook {rel}: {m}" for m in _EXPORT_HOOK_MARKERS if m in text]
    for tool, key in (("claude", "mcpServers"), ("kiro", "mcpServers"), ("opencode", "mcp")):
        path = installers._mcp_config_path(tool)
        if path.exists():
            servers = json.loads(path.read_text(encoding="utf-8")).get(key, {})
            found += [f"mcp {tool}: {name}" for name in _OWNED_MCP if name in servers]
    codex = installers._mcp_config_path("codex")
    if codex.exists():
        servers = tomllib.loads(codex.read_text(encoding="utf-8")).get("mcp_servers", {})
        found += [f"mcp codex: {name}" for name in _OWNED_MCP if name in servers]
    registered = box.grok_registry.read_text(encoding="utf-8").split()
    found += [f"mcp grok: {name}" for name in _OWNED_MCP if name in registered]
    claude_settings = box.home / ".claude/settings.json"
    if claude_settings.exists():
        status_line = json.loads(claude_settings.read_text(encoding="utf-8")).get("statusLine")
        if isinstance(status_line, dict) and "study-statusline.sh" in str(
            status_line.get("command", "")
        ):
            found.append(f"statusLine claude: {status_line['command']}")
    return found


def _assert_installed_once(box: Sandbox) -> None:
    """Positive control: install really wired every surface, exactly once each."""
    home = box.home
    claude_stop = json.loads((home / ".claude/settings.json").read_text())["hooks"]["Stop"]
    codex_end = json.loads((home / ".codex/hooks.json").read_text())["hooks"]["SessionEnd"]
    grok_end = json.loads((box.grok_home / "hooks/studyloop.json").read_text())["hooks"][
        "SessionEnd"
    ]
    for groups, marker in (
        (claude_stop, "session-export --claude-only"),
        (codex_end, "session-export --codex-only"),
        (grok_end, "session-export --grok-only"),
    ):
        commands = [h["command"] for g in groups for h in g["hooks"]]
        assert sum(marker in c for c in commands) == 1, commands
    for spec in installers._HARNESS_EXPORT.values():
        text = spec.steering_path.read_text(encoding="utf-8")
        assert text.count(installers._MANDATE_SENTINEL) == 1, spec.steering_path
    for tool in ("claude", "kiro", "opencode"):
        raw = installers._mcp_config_path(tool).read_text(encoding="utf-8")
        for name in _OWNED_MCP:
            assert raw.count(json.dumps(name) + ":") == 1, (tool, name)
    toml_raw = installers._mcp_config_path("codex").read_text(encoding="utf-8")
    for name in _OWNED_MCP:
        assert toml_raw.count(f"[mcp_servers.{name}]") == 1, name
    registered = box.grok_registry.read_text(encoding="utf-8").split()
    assert sorted(registered) == sorted(["user-server", *_OWNED_MCP])


def _assert_user_state_restored(box: Sandbox) -> None:
    changed = sorted(
        str(path.relative_to(box.root))
        for path, text in box.planted.items()
        if not path.exists() or path.read_text(encoding="utf-8") != text
    )
    assert changed == [], f"uninstall did not return these to the learner's bytes: {changed}"
    assert _USER_CLAUDE_MCP_ENTRY in (box.home / ".claude.json").read_text(encoding="utf-8")


def test_uninstall_removes_every_owned_hook_mandate_and_mcp_entry(sandbox: Sandbox) -> None:
    sandbox.install()
    _assert_installed_once(sandbox)

    sandbox.uninstall()

    assert _owned_residue(sandbox) == []
    _assert_user_state_restored(sandbox)
    # StudyLoop's own Grok hook file goes with its hook; the learner's beside it stays.
    assert not (sandbox.grok_home / "hooks/studyloop.json").exists()


def test_uninstall_is_idempotent_and_reinstall_has_no_duplicates(sandbox: Sandbox) -> None:
    sandbox.install()
    sandbox.uninstall()
    after_first = sandbox.snapshot()

    second = sandbox.uninstall()

    assert set(second.values()) == {0}, second
    assert sandbox.snapshot() == after_first

    sandbox.install()
    sandbox.install()
    _assert_installed_once(sandbox)

    sandbox.uninstall()
    assert _owned_residue(sandbox) == []
    _assert_user_state_restored(sandbox)


def test_uninstall_keeps_an_edited_mandate_as_a_backup(sandbox: Sandbox) -> None:
    """A mandate that is no longer the shipped text may carry the learner's edits.

    It stops loading (harnesses read ``*.md``) but its bytes are kept beside it,
    so removal never destroys writing StudyLoop did not author.
    """
    sandbox.install()
    steering = installers._HARNESS_EXPORT["kiro"].steering_path
    edited = steering.read_text(encoding="utf-8") + "\nMy own note.\n"
    steering.write_text(edited, encoding="utf-8")

    sandbox.uninstall()

    assert not steering.exists()
    assert steering.with_name("session-db.md.bak").read_text(encoding="utf-8") == edited


# StudyLoop's status line: install points Claude Code's ``statusLine`` at the
# script it copies to ~/.claude/, which uninstall deletes. An entry left behind
# runs a missing command on every render.
_OUR_STATUS_LINE = {"type": "command", "command": "~/.claude/study-statusline.sh"}
_LEARNER_STATUS_LINE = {"type": "command", "command": "~/bin/my-status-line.sh"}


def test_uninstall_removes_the_status_line_install_created(sandbox: Sandbox) -> None:
    settings = sandbox.home / ".claude/settings.json"
    settings.unlink()  # no settings yet: install writes StudyLoop's template
    sandbox.install()
    assert json.loads(settings.read_text(encoding="utf-8"))["statusLine"] == _OUR_STATUS_LINE

    sandbox.uninstall()

    assert not (sandbox.home / ".claude/study-statusline.sh").exists()
    assert "statusLine" not in json.loads(settings.read_text(encoding="utf-8"))
    assert _owned_residue(sandbox) == []


@pytest.mark.parametrize(
    "command",
    ["~/.claude/study-statusline.sh", "$HOME/.claude/study-statusline.sh", "{home}"],
)
def test_uninstall_removes_studyloops_status_line_and_keeps_every_other_member(
    sandbox: Sandbox, command: str
) -> None:
    """Install's template spelling and the two a learner may expand it to."""
    if command == "{home}":
        command = str(sandbox.home / ".claude/study-statusline.sh")
    settings = sandbox.home / ".claude/settings.json"
    learner = {"theme": "dark", "hooks": {"Stop": [_USER_STOP_GROUP]}}
    with_ours = {"statusLine": {**_OUR_STATUS_LINE, "command": command}, **learner}
    settings.write_text(json.dumps(with_ours, indent=2) + "\n", encoding="utf-8")
    sandbox.install()

    sandbox.uninstall()

    assert settings.read_text(encoding="utf-8") == json.dumps(learner, indent=2) + "\n"


def test_uninstall_keeps_a_learners_own_status_line_byte_for_byte(sandbox: Sandbox) -> None:
    settings = sandbox.home / ".claude/settings.json"
    planted = (
        json.dumps(
            {
                "theme": "dark",
                "statusLine": _LEARNER_STATUS_LINE,
                "hooks": {"Stop": [_USER_STOP_GROUP]},
            },
            indent=2,
        )
        + "\n"
    )
    settings.write_text(planted, encoding="utf-8")

    sandbox.install()
    sandbox.uninstall()

    assert settings.read_text(encoding="utf-8") == planted


def test_status_line_removal_keeps_the_learners_formatting(sandbox: Sandbox) -> None:
    """With no Stop hook to rewrite the file, only the statusLine member's bytes go.

    A hand-formatted file with a non-ASCII value: a reserialising writer would
    reflow the indentation and escape the character.
    """
    settings = sandbox.home / ".claude/settings.json"
    ours = json.dumps(_OUR_STATUS_LINE)
    settings.write_text(
        f'{{\n    "theme": "caf\u00e9",\n    "statusLine": {ours},\n    "model": "opus"\n}}\n',
        encoding="utf-8",
    )

    sandbox.uninstall()

    assert settings.read_text(encoding="utf-8") == (
        '{\n    "theme": "caf\u00e9",\n    "model": "opus"\n}\n'
    )


def test_status_line_removal_refuses_an_edit_it_cannot_verify(sandbox: Sandbox) -> None:
    """Duplicate keys: JSON keeps the last, the byte walk would cut the first.

    The parse-back check sees the learner's entry would go instead of
    StudyLoop's and refuses, leaving the file as it was.
    """
    settings = sandbox.home / ".claude/settings.json"
    planted = (
        f'{{"statusLine": {json.dumps(_LEARNER_STATUS_LINE)}, '
        f'"statusLine": {json.dumps(_OUR_STATUS_LINE)}}}\n'
    )
    settings.write_text(planted, encoding="utf-8")

    with pytest.raises(installers.InstallError, match="statusLine"):
        sandbox.uninstall()

    assert settings.read_text(encoding="utf-8") == planted
