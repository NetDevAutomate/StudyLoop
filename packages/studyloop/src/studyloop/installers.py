"""Install helpers for studyloop tools, agents, and config bootstrap."""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from studyloop.harnesses import RELEASE_HARNESSES
from studyloop.settings import generate_default_config, get_config_path, load_settings


class InstallError(RuntimeError):
    """Raised when an install action cannot be completed."""


@dataclass(frozen=True, slots=True)
class LinkSpec:
    """One symlink to create: ``target`` -> ``source``.

    ``source`` is normally a repository-relative path. It may instead be an
    absolute path or one starting with ``~``, which means "link to this location on
    disk, wherever it came from". That form exists for the skills hub: a skill is
    installed once into ``~/.agents/skills/`` and each harness's own skills
    directory then links to THAT, not back to the repository.

    Two links in a chain rather than several in parallel, because the alternative
    drifts. With parallel links, adding a harness means another repo-relative row,
    and Codex -- which reads ``~/.agents/skills`` natively -- would get a redundant
    second path to the same skill. With a hub, Codex is served by the hub alone and
    every other harness is one link away from the same bytes.
    """

    source: str
    target: str


_HOME = Path.home()

_TOOL_LINKS: dict[str, tuple[LinkSpec, ...]] = {
    "kiro": (
        LinkSpec("agents/kiro/study-mentor.json", str(_HOME / ".kiro/agents/study-mentor.json")),
        LinkSpec("agents/kiro/study-mentor", str(_HOME / ".kiro/agents/study-mentor")),
        LinkSpec("agents/kiro/skills/study-mentor", str(_HOME / ".kiro/skills/study-mentor")),
        LinkSpec(
            "agents/kiro/skills/audhd-socratic-mentor",
            str(_HOME / ".kiro/skills/audhd-socratic-mentor"),
        ),
        LinkSpec(
            "agents/kiro/skills/tutor-progress-tracker",
            str(_HOME / ".kiro/skills/tutor-progress-tracker"),
        ),
        LinkSpec("agents/kiro/skills/study-speak", str(_HOME / ".kiro/skills/study-speak")),
        LinkSpec(
            "agents/mcp/study-speak-server.py",
            str(_HOME / ".kiro/agents/mcp/study-speak-server.py"),
        ),
    ),
    "claude": (
        LinkSpec(
            "agents/claude/socratic-mentor.md",
            str(_HOME / ".claude/agents/socratic-mentor.md"),
        ),
    ),
    "opencode": (
        LinkSpec(
            "agents/opencode/study-mentor.md",
            str(_HOME / ".config/opencode/agents/study-mentor.md"),
        ),
    ),
    "codex": (LinkSpec("agents/codex/AGENTS.md", "{repo_root}/AGENTS.md"),),
    "pi": (LinkSpec("agents/pi/AGENTS.md", str(_HOME / ".pi/agent/AGENTS.md")),),
}

#: The canonical location of the xTiles wind-down skill, and the name every
#: harness link points at. Not a StudyLoop invention: Codex reads
#: ``~/.agents/skills`` as its USER scope and OpenCode lists it as a global search
#: path, so the hub is a directory those two already look in.
XTILES_SKILL_NAME = "studyloop-xtiles-wind-down"
XTILES_SKILL_HUB = _HOME / ".agents/skills" / XTILES_SKILL_NAME

_SHARED_LINKS: tuple[LinkSpec, ...] = (
    LinkSpec("agents/shared", str(_HOME / ".agents/shared")),
    # The skill itself, installed once. Opt-in and self-gating: inert unless the
    # learner's provider is xtiles AND an `xtiles` MCP server is connected, so
    # installing it unconditionally costs a silent file rather than an unwanted
    # offer (T5 C5 / DECISIONS §F18). Codex needs no further link -- this IS its
    # user-scope skills directory.
    LinkSpec(f"agents/skills/{XTILES_SKILL_NAME}", str(XTILES_SKILL_HUB)),
)

#: Each harness's own skills directory, for the ones whose location is documented.
#: pi is absent on purpose: no pi skills directory is documented, so it gets a
#: self-gated paragraph in its AGENTS.md instead of a link to a guessed path.
XTILES_SKILL_LINKS: dict[str, LinkSpec] = {
    "kiro": LinkSpec(str(XTILES_SKILL_HUB), str(_HOME / ".kiro/skills" / XTILES_SKILL_NAME)),
    "claude": LinkSpec(str(XTILES_SKILL_HUB), str(_HOME / ".claude/skills" / XTILES_SKILL_NAME)),
    "opencode": LinkSpec(
        str(XTILES_SKILL_HUB), str(_HOME / ".config/opencode/skills" / XTILES_SKILL_NAME)
    ),
}

_AGENT_CHOICES = RELEASE_HARNESSES

# ---------------------------------------------------------------------------
# Cross-harness session-export wiring (W4)
# ---------------------------------------------------------------------------
#
# The session DB is the single source of truth for cross-harness struggle
# tracking. Each harness needs a steering-file mandate telling its agent to
# run `session-export` at session end; Claude Code additionally gets a Stop
# hook so export happens automatically. Codex carries the same mandate directly
# in its installed ``AGENTS.md``, so it does not need a second steering file.


@dataclass(frozen=True, slots=True)
class _HarnessExport:
    """Where a harness's steering file lives + the session-export flag to use."""

    steering_path: Path
    export_flag: str  # the `session-export --<flag>` argument


_HARNESS_EXPORT: dict[str, _HarnessExport] = {
    "claude": _HarnessExport(_HOME / ".claude/rules/session-db.md", "claude-only"),
    "kiro": _HarnessExport(_HOME / ".kiro/steering/session-db.md", "kiro-only"),
    "opencode": _HarnessExport(_HOME / ".config/opencode/session-db.md", "opencode-only"),
    "pi": _HarnessExport(_HOME / ".pi/agent/session-db.md", "pi-only"),
}

# Sentinel marking a steering file as carrying the export mandate (idempotency
# + the doctor harness check both key on this).
_MANDATE_SENTINEL = "studyloop:session-export-mandate"
# Sentinel inside the Claude Stop hook command (idempotent merge + doctor check).
_HOOK_SENTINEL = "session-export --claude-only"


def _render_mandate(repo_root: Path, export_flag: str) -> str:
    """Load the shared mandate template and substitute the harness flag."""
    template = (repo_root / "agents/shared/session-db-mandate.md").read_text(encoding="utf-8")
    return template.replace("SESSION_EXPORT_FLAG", export_flag)


def install_session_db_mandate(repo_root: Path, tools: list[str] | None = None) -> dict[str, int]:
    """Write the session-export steering mandate into each harness's file.

    Idempotent: a file already containing the sentinel is left untouched.
    A file without it is overwritten with the rendered mandate (these
    session-db.md files are StudyLoop-managed, single-purpose). Returns a
    per-tool count of files written.
    """
    selected = tools or detect_available_agent_tools()
    written: dict[str, int] = {}
    for tool in selected:
        spec = _HARNESS_EXPORT.get(tool)
        if spec is None:
            continue
        if spec.steering_path.exists() and _MANDATE_SENTINEL in spec.steering_path.read_text(
            encoding="utf-8"
        ):
            written[tool] = 0
            continue
        spec.steering_path.parent.mkdir(parents=True, exist_ok=True)
        spec.steering_path.write_text(
            _render_mandate(repo_root, spec.export_flag), encoding="utf-8"
        )
        written[tool] = 1
    return written


def install_claude_stop_hook() -> int:
    """Merge the session-export Stop hook into ~/.claude/settings.json.

    Read-modify-write that preserves existing hooks; idempotent (a hook
    already containing the sentinel is not duplicated). Returns 1 if a hook
    was added, else 0.
    """
    import json

    settings_path = _HOME / ".claude/settings.json"
    if not settings_path.exists():
        return 0  # no Claude settings to merge into; nothing to do
    try:
        data = json.loads(settings_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0
    if not isinstance(data, dict):
        return 0

    hooks = data.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        return 0
    stop = hooks.setdefault("Stop", [])
    if not isinstance(stop, list):
        return 0

    # Idempotency: bail if any existing Stop hook already runs session-export.
    for group in stop:
        for h in (group or {}).get("hooks", []) if isinstance(group, dict) else []:
            if _HOOK_SENTINEL in str(h.get("command", "")):
                return 0

    stop.append(
        {
            "matcher": "",
            "hooks": [
                {
                    "type": "command",
                    "command": f"{_HOOK_SENTINEL} >/dev/null 2>&1 || true",
                    "timeout": 30,
                    "async": True,
                }
            ],
        }
    )
    settings_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return 1


def find_repo_root(start: Path | None = None) -> Path | None:
    """Locate the repository root when running from a source checkout."""
    candidates = []
    if start is not None:
        candidates.append(start.resolve())
    candidates.extend([Path.cwd().resolve(), Path(__file__).resolve()])

    seen: set[Path] = set()
    for candidate in candidates:
        current = candidate if candidate.is_dir() else candidate.parent
        for path in (current, *current.parents):
            if path in seen:
                continue
            seen.add(path)
            if (
                (path / "pyproject.toml").exists()
                and (path / "packages" / "studyloop").exists()
                and (path / "scripts" / "install.sh").exists()
            ):
                return path
    return None


def require_repo_root(start: Path | None = None) -> Path:
    """Return the repo root or raise an install error."""
    repo_root = find_repo_root(start)
    if repo_root is None:
        msg = "This command requires a source checkout of studyloop."
        raise InstallError(msg)
    return repo_root


def _run(cmd: list[str], *, cwd: Path | None = None) -> None:
    subprocess.run(cmd, cwd=str(cwd) if cwd else None, check=True)


def install_workspace_tools(
    repo_root: Path,
    *,
    sync_workspace: bool = True,
    force: bool = True,
) -> list[str]:
    """Install editable workspace packages as global uv tools."""
    installed: list[str] = []

    if sync_workspace:
        _run(["uv", "sync", "--all-packages"], cwd=repo_root)

    packages_dir = repo_root / "packages"
    for pkg_dir in sorted(p for p in packages_dir.iterdir() if p.is_dir()):
        package_name = pkg_dir.name
        cmd = ["uv", "tool", "install"]
        # Both packages install with their [all] aggregate extra so a single
        # `./scripts/install.sh` yields a fully working tool — web UI, content
        # generation, Bedrock (boto3), MCP server, NotebookLM, TUI, and
        # semantic session search. Partial extras here are how "No module
        # named 'boto3'/'mcp'" surfaced in otherwise-green installs.
        #
        # studyloop's own [all] does NOT include agent-session-tools (R-29):
        # it is not published, so it cannot resolve as a wheel extra outside
        # this workspace. `--with-editable` below is the real, unconditional
        # mechanism that makes it a hard dependency of THIS install path
        # regardless of any extra (DECISIONS.md B1).
        if package_name == "agent-session-tools":
            cmd.append(f"{pkg_dir}[all]")
        elif package_name == "studyloop":
            cmd.append(f"{pkg_dir}[all]")
            cmd.extend(["--with-editable", str(repo_root / "packages" / "agent-session-tools")])
        else:
            cmd.append(str(pkg_dir))
        cmd.append("--editable")
        if force:
            cmd.append("--force")
        _run(cmd, cwd=repo_root)
        installed.append(package_name)

    return installed


def _render_target(template: str, repo_root: Path) -> Path:
    return Path(template.format(repo_root=repo_root)).expanduser()


def _render_source(source: str, repo_root: Path) -> Path:
    """Resolve a :class:`LinkSpec` source to a real path.

    Absolute or ``~``-prefixed sources link to an existing location on disk (the
    skills hub); everything else is repository-relative, as it always was.
    """
    if source.startswith("~") or Path(source).is_absolute():
        return Path(source).expanduser()
    return repo_root / source


def _points_to(target: Path, source: Path) -> bool:
    """True if symlink ``target`` points at ``source`` (relative or absolute form)."""
    current = Path(os.readlink(target))
    if not current.is_absolute():
        current = target.parent / current
    return current.resolve() == source.resolve()


def _link_paths(repo_root: Path, specs: tuple[LinkSpec, ...], *, uninstall: bool) -> int:
    changed = 0
    for spec in specs:
        source = _render_source(spec.source, repo_root)
        target = _render_target(spec.target, repo_root)
        # In-repo targets use relative links so they survive repo moves and
        # syncing between machines with different absolute paths.
        in_repo = "{repo_root}" in spec.target
        link_value = Path(os.path.relpath(source, target.parent)) if in_repo else source
        target.parent.mkdir(parents=True, exist_ok=True)
        if uninstall:
            if target.is_symlink() and _points_to(target, source):
                target.unlink()
                changed += 1
            continue

        if not source.exists():
            raise InstallError(f"Missing install asset: {source}")

        if target.is_symlink():
            if os.readlink(target) == str(link_value):
                continue
            # Legacy absolute (or otherwise stale) link — replace below.
            target.unlink()
        elif target.exists():
            backup = target.with_name(f"{target.name}.bak")
            shutil.move(str(target), str(backup))

        target.symlink_to(link_value)
        changed += 1
    return changed


def detect_available_agent_tools() -> list[str]:
    """Detect agent environments available on this machine."""
    available: list[str] = []
    if (_HOME / ".kiro").is_dir():
        available.append("kiro")
    if (_HOME / ".claude").is_dir():
        available.append("claude")
    if shutil.which("opencode"):
        available.append("opencode")
    if shutil.which("codex"):
        available.append("codex")
    if shutil.which("pi") or (_HOME / ".pi").is_dir():
        available.append("pi")
    return available


def _configure_claude(repo_root: Path, *, uninstall: bool) -> int:
    claude_home = _HOME / ".claude"
    statusline = claude_home / "study-statusline.sh"
    settings = claude_home / "settings.json"
    changed = 0

    if uninstall:
        if statusline.exists():
            statusline.unlink()
            changed += 1
        return changed

    claude_home.mkdir(parents=True, exist_ok=True)
    shutil.copy2(repo_root / "agents/claude/study-statusline.sh", statusline)
    statusline.chmod(0o755)
    changed += 1
    if not settings.exists():
        shutil.copy2(repo_root / "agents/claude/settings.json", settings)
        changed += 1
    return changed


def install_agent_definitions(
    repo_root: Path,
    *,
    tools: list[str] | None = None,
    uninstall: bool = False,
) -> dict[str, int]:
    """Install or remove agent definition links for the requested tools."""
    selected = tools or detect_available_agent_tools()
    if not selected:
        raise InstallError(
            "No supported AI tools detected. "
            "Install Kiro CLI, Codex, Claude Code, OpenCode, or pi first."
        )

    invalid = [tool for tool in selected if tool not in _AGENT_CHOICES]
    if invalid:
        raise InstallError(f"Unsupported agent tool(s): {', '.join(sorted(invalid))}")

    summary: dict[str, int] = {"shared": _link_paths(repo_root, _SHARED_LINKS, uninstall=uninstall)}

    for tool in selected:
        summary[tool] = _link_paths(repo_root, _TOOL_LINKS[tool], uninstall=uninstall)
        # The xTiles skill, linked from the hub the shared pass installed above.
        # Ordering matters and is not incidental: _SHARED_LINKS runs first, so the
        # hub exists before anything points at it.
        if skill_link := XTILES_SKILL_LINKS.get(tool):
            summary[tool] += _link_paths(repo_root, (skill_link,), uninstall=uninstall)
        if tool == "claude":
            summary[tool] += _configure_claude(repo_root, uninstall=uninstall)

    # Cross-harness session-export wiring: steering mandate for every detected
    # harness + a Stop hook for Claude. Skipped on uninstall.
    if not uninstall:
        for tool, count in install_session_db_mandate(repo_root, tools=selected).items():
            summary[tool] = summary.get(tool, 0) + count
        if "claude" in selected:
            summary["claude"] = summary.get("claude", 0) + install_claude_stop_hook()

    return summary


def ensure_default_config() -> Path:
    """Create a default config file if it does not already exist."""
    config_path = get_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    if not config_path.exists():
        config_path.write_text(generate_default_config())
    return config_path


def ensure_review_directories() -> list[Path]:
    """Create any configured topic review directories that do not yet exist."""
    created: list[Path] = []
    for topic in load_settings().topics:
        path = topic.obsidian_path.expanduser()
        if not path.exists():
            path.mkdir(parents=True, exist_ok=True)
            created.append(path)
    return created


def ensure_review_database() -> Path:
    """Bootstrap or migrate the review database."""
    from studyloop.review_db import ensure_tables, get_db_path

    db_path = get_db_path()
    ensure_tables(db_path)
    return db_path


__all__ = [
    "InstallError",
    "detect_available_agent_tools",
    "ensure_default_config",
    "ensure_review_database",
    "ensure_review_directories",
    "find_repo_root",
    "install_agent_definitions",
    "install_workspace_tools",
    "require_repo_root",
]
