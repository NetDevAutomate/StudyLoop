"""Git integration for capturing repository context in sessions."""

import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass
class GitContext:
    """Git repository context for session metadata."""

    branch: str | None = None
    commit_hash: str | None = None
    commit_message: str | None = None
    uncommitted_files: list[str] | None = None
    diff_stat: str | None = None
    is_dirty: bool = False
    last_commit_time: str | None = None


def get_git_context(project_path: str | Path) -> GitContext | None:
    """Extract git context from project directory.

    Args:
        project_path: Path to project directory

    Returns:
        GitContext with repository information, or None if not a git repo
    """
    path = Path(project_path)
    if not path.exists():
        return None

    try:
        # Check if this is a git repository
        result = subprocess.run(
            ["git", "rev-parse", "--git-dir"],
            cwd=path,
            capture_output=True,
            text=True,
            timeout=2,
        )
        if result.returncode != 0:
            return None

        context = GitContext()

        # Get current branch
        result = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=path,
            capture_output=True,
            text=True,
            timeout=2,
        )
        if result.returncode == 0 and result.stdout.strip():
            context.branch = result.stdout.strip()

        # Get current commit
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=path,
            capture_output=True,
            text=True,
            timeout=2,
        )
        if result.returncode == 0:
            context.commit_hash = result.stdout.strip()[:8]

        # Get commit message
        result = subprocess.run(
            ["git", "log", "-1", "--pretty=format:%s"],
            cwd=path,
            capture_output=True,
            text=True,
            timeout=2,
        )
        if result.returncode == 0:
            context.commit_message = result.stdout.strip()

        # Get last commit time
        result = subprocess.run(
            ["git", "log", "-1", "--pretty=format:%ci"],
            cwd=path,
            capture_output=True,
            text=True,
            timeout=2,
        )
        if result.returncode == 0:
            context.last_commit_time = result.stdout.strip()

        # Check for uncommitted changes
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=path,
            capture_output=True,
            text=True,
            timeout=2,
        )
        if result.returncode == 0:
            lines = [line for line in result.stdout.strip().split("\n") if line.strip()]
            context.uncommitted_files = [
                line[3:] for line in lines
            ]  # Remove status prefix
            context.is_dirty = bool(context.uncommitted_files)

        # Get diff statistics
        if context.is_dirty:
            result = subprocess.run(
                ["git", "diff", "--stat"],
                cwd=path,
                capture_output=True,
                text=True,
                timeout=2,
            )
            if result.returncode == 0:
                context.diff_stat = result.stdout.strip()

        return context

    except (
        subprocess.TimeoutExpired,
        subprocess.CalledProcessError,
        FileNotFoundError,
    ):
        return None


def format_git_context_for_export(git_context: GitContext) -> str:
    """Format git context for inclusion in session exports.

    Args:
        git_context: Git context information

    Returns:
        Formatted markdown string
    """
    if not git_context:
        return ""

    lines = ["## Git Context"]

    if git_context.branch:
        lines.append(f"**Branch:** `{git_context.branch}`")

    if git_context.commit_hash and git_context.commit_message:
        lines.append(
            f"**Commit:** `{git_context.commit_hash}` - {git_context.commit_message}"
        )

    if git_context.last_commit_time:
        lines.append(f"**Last Commit:** {git_context.last_commit_time}")

    if git_context.is_dirty:
        uncommitted_count = len(git_context.uncommitted_files or [])
        lines.append(f"**Status:** {uncommitted_count} uncommitted files")

        if git_context.diff_stat:
            lines.append("**Changes:**")
            lines.append(f"```\n{git_context.diff_stat}\n```")

    lines.append("")  # Empty line after git context
    return "\n".join(lines)
