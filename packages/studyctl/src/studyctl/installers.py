"""Install helpers for studyctl tools, agents, and config bootstrap."""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from studyctl.settings import _CONFIG_PATH, generate_default_config, load_settings


class InstallError(RuntimeError):
    """Raised when an install action cannot be completed."""


@dataclass(frozen=True, slots=True)
class LinkSpec:
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
    "gemini": (
        LinkSpec(
            "agents/gemini/study-mentor.md",
            str(_HOME / ".gemini/agents/study-mentor.md"),
        ),
        LinkSpec("agents/gemini/GEMINI.md", "{repo_root}/GEMINI.md"),
    ),
    "opencode": (
        LinkSpec(
            "agents/opencode/study-mentor.md",
            str(_HOME / ".config/opencode/agents/study-mentor.md"),
        ),
    ),
    "codex": (LinkSpec("agents/codex/AGENTS.md", "{repo_root}/AGENTS.md"),),
    "amp": (),
}

_SHARED_LINKS: tuple[LinkSpec, ...] = (LinkSpec("agents/shared", str(_HOME / ".agents/shared")),)

_AGENT_CHOICES = ("kiro", "claude", "gemini", "opencode", "codex", "amp")


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
                and (path / "packages" / "studyctl").exists()
                and (path / "scripts" / "install.sh").exists()
            ):
                return path
    return None


def require_repo_root(start: Path | None = None) -> Path:
    """Return the repo root or raise an install error."""
    repo_root = find_repo_root(start)
    if repo_root is None:
        msg = "This command requires a source checkout of socratic-study-mentor."
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
        _run(["uv", "sync"], cwd=repo_root)

    packages_dir = repo_root / "packages"
    for pkg_dir in sorted(p for p in packages_dir.iterdir() if p.is_dir()):
        package_name = pkg_dir.name
        cmd = ["uv", "tool", "install"]
        if package_name == "agent-session-tools":
            cmd.append(f"{pkg_dir}[tts]")
        elif package_name == "studyctl":
            cmd.append(f"{pkg_dir}[tui,web]")
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


def _link_paths(repo_root: Path, specs: tuple[LinkSpec, ...], *, uninstall: bool) -> int:
    changed = 0
    for spec in specs:
        source = repo_root / spec.source
        target = _render_target(spec.target, repo_root)
        target.parent.mkdir(parents=True, exist_ok=True)
        if uninstall:
            if target.is_symlink():
                current = Path(os.readlink(target))
                if current == source:
                    target.unlink()
                    changed += 1
            continue

        if not source.exists():
            raise InstallError(f"Missing install asset: {source}")

        if target.is_symlink():
            current = Path(os.readlink(target))
            if current == source:
                continue
            target.unlink()
        elif target.exists():
            backup = target.with_name(f"{target.name}.bak")
            shutil.move(str(target), str(backup))

        target.symlink_to(source)
        changed += 1
    return changed


def detect_available_agent_tools() -> list[str]:
    """Detect agent environments available on this machine."""
    available: list[str] = []
    if (_HOME / ".kiro").is_dir():
        available.append("kiro")
    if (_HOME / ".claude").is_dir():
        available.append("claude")
    if (_HOME / ".gemini").is_dir():
        available.append("gemini")
    if shutil.which("opencode"):
        available.append("opencode")
    if shutil.which("codex"):
        available.append("codex")
    if shutil.which("amp"):
        available.append("amp")
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


def _configure_gemini(*, uninstall: bool) -> int:
    gemini_home = _HOME / ".gemini"
    settings = gemini_home / "settings.json"
    changed = 0

    if uninstall:
        return 0

    if settings.exists() and '"enableAgents"' in settings.read_text():
        return 0

    gemini_home.mkdir(parents=True, exist_ok=True)
    settings.write_text('{\n  "experimental": {\n    "enableAgents": true\n  }\n}\n')
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
            "Install Claude Code, Kiro, Gemini, OpenCode, Codex, or Amp first."
        )

    invalid = [tool for tool in selected if tool not in _AGENT_CHOICES]
    if invalid:
        raise InstallError(f"Unsupported agent tool(s): {', '.join(sorted(invalid))}")

    summary: dict[str, int] = {"shared": _link_paths(repo_root, _SHARED_LINKS, uninstall=uninstall)}

    for tool in selected:
        summary[tool] = _link_paths(repo_root, _TOOL_LINKS[tool], uninstall=uninstall)
        if tool == "claude":
            summary[tool] += _configure_claude(repo_root, uninstall=uninstall)
        elif tool == "gemini":
            summary[tool] += _configure_gemini(uninstall=uninstall)

    return summary


def ensure_default_config() -> Path:
    """Create a default config file if it does not already exist."""
    _CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not _CONFIG_PATH.exists():
        _CONFIG_PATH.write_text(generate_default_config())
    return _CONFIG_PATH


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
    from studyctl.review_db import ensure_tables, get_db_path

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
