"""Kiro adapter — persona via ~/.kiro/agents/study-mentor.json.

Kiro loads agents natively from ~/.kiro/agents/. The setup function
writes canonical content to a temp persona file, then updates the
agent JSON's "prompt" field to reference it via file:// URI.
Teardown restores the original JSON from a backup.

Crash recovery: stale backups are restored on next setup to prevent
Kiro from permanently using a studyctl-managed prompt.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import tempfile
from pathlib import Path

from studyctl.adapters._protocol import AgentAdapter

logger = logging.getLogger(__name__)

# Repo root: adapters/kiro.py is at
#   packages/studyctl/src/studyctl/adapters/kiro.py
# So repo root is six levels up.
_REPO_ROOT = Path(__file__).parent.parent.parent.parent.parent.parent

KIRO_AGENTS_DIR = Path(os.environ.get("STUDYCTL_KIRO_AGENTS_DIR", Path.home() / ".kiro" / "agents"))
KIRO_AGENT_NAME = "study-mentor"
_KIRO_TEMPLATE = _REPO_ROOT / "agents" / "kiro" / "study-mentor.json"
_KIRO_BACKUP_SUFFIX = ".studyctl-backup"


def _kiro_setup(canonical_content: str, _session_dir: Path) -> Path:
    """Write persona temp file and update Kiro agent JSON atomically."""
    # 1. Write canonical content to a temp persona file
    fd, persona_path = tempfile.mkstemp(
        prefix="studyctl-kiro-persona-",
        suffix=".md",
        dir=tempfile.gettempdir(),
    )
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(canonical_content)

    # 2. Load the base agent template
    if _KIRO_TEMPLATE.exists():
        agent_def = json.loads(_KIRO_TEMPLATE.read_text())
    else:
        agent_def = {
            "name": KIRO_AGENT_NAME,
            "description": "Socratic study mentor",
        }

    # 3. Update prompt to reference the temp persona file
    agent_def["prompt"] = f"file://{persona_path}"

    # 4. Ensure target directory exists
    KIRO_AGENTS_DIR.mkdir(parents=True, exist_ok=True)
    target = KIRO_AGENTS_DIR / f"{KIRO_AGENT_NAME}.json"
    backup = target.with_suffix(target.suffix + _KIRO_BACKUP_SUFFIX)

    # 4a. Recover from crash: if a backup exists, the previous session's
    # teardown never ran. Restore the user's original config first.
    if backup.exists():
        logger.warning(
            "Stale Kiro backup detected (previous session crashed?) — restoring %s",
            backup,
        )
        os.replace(backup, target)

    # 5. Backup existing agent JSON if present
    if target.exists():
        shutil.copy2(target, backup)

    # 6. Atomic write: temp file in same dir → os.replace()
    fd2, tmp_json = tempfile.mkstemp(
        prefix=f"{KIRO_AGENT_NAME}-",
        suffix=".json",
        dir=str(KIRO_AGENTS_DIR),
    )
    with os.fdopen(fd2, "w") as f:
        json.dump(agent_def, f, indent=2)
    os.replace(tmp_json, target)

    return Path(persona_path)


def _kiro_launch(_persona_path: Path, resume: bool) -> str:
    """Build Kiro launch command."""
    binary = shutil.which("kiro-cli") or shutil.which("kiro") or "kiro-cli"
    if resume:
        return f"{binary} chat --agent {KIRO_AGENT_NAME} --resume"
    return f"{binary} chat --agent {KIRO_AGENT_NAME}"


def _kiro_teardown(_session_dir: Path) -> None:
    """Restore the backed-up Kiro agent JSON."""
    target = KIRO_AGENTS_DIR / f"{KIRO_AGENT_NAME}.json"
    backup = target.with_suffix(target.suffix + _KIRO_BACKUP_SUFFIX)
    if backup.exists():
        os.replace(backup, target)


ADAPTER = AgentAdapter(
    name="kiro",
    binary="kiro-cli",
    setup=_kiro_setup,
    launch_cmd=_kiro_launch,
    teardown=_kiro_teardown,
)
