"""Kiro adapter — persona via ~/.kiro/agents/study-mentor.json.

Kiro loads agents natively from ~/.kiro/agents/. The setup function
writes canonical content to a temp persona file, then updates the
agent JSON's "prompt" field to reference it via file:// URI.
Teardown restores the original JSON from a backup.

Crash recovery: stale backups are restored on next setup to prevent
Kiro from permanently using a studyloop-managed prompt.
"""

from __future__ import annotations

import json
import logging
import os
import shlex
import shutil
import tempfile
from pathlib import Path

from studyloop.adapters._protocol import AgentAdapter

logger = logging.getLogger(__name__)

# Repo root: adapters/kiro.py is at
#   packages/studyloop/src/studyloop/adapters/kiro.py
# So repo root is six levels up.
_REPO_ROOT = Path(__file__).parent.parent.parent.parent.parent.parent

KIRO_AGENTS_DIR = Path(
    os.environ.get("STUDYLOOP_KIRO_AGENTS_DIR", Path.home() / ".kiro" / "agents")
)
KIRO_AGENT_NAME = "study-mentor"
#: StudyLoop's own persona-neutral Kiro agent (``agents/kiro/studyloop.json``),
#: installed by ``studyloop install agents`` and named on every Kiro ACP launch,
#: so the learner's *default* Kiro agent never configures StudyLoop's sessions.
#: The persona reaches an ACP session as its first turn, not from this agent.
KIRO_ACP_AGENT_NAME = "studyloop"
_KIRO_TEMPLATE = _REPO_ROOT / "agents" / "kiro" / "study-mentor.json"
_KIRO_BACKUP_SUFFIX = ".studyloop-backup"


def _template_path() -> Path:
    """Resolve an explicitly selected Kiro profile or the shipped default."""
    configured = os.environ.get("STUDYLOOP_KIRO_AGENT_TEMPLATE", "").strip()
    if not configured:
        return _KIRO_TEMPLATE
    path = Path(configured).expanduser()
    if not path.is_file():
        raise FileNotFoundError(f"Kiro agent template not found: {path}")
    return path


def _is_studyloop_swap(target: Path) -> bool:
    """True when ``target`` is the agent file a session's setup swapped in.

    Setup writes a regular file whose ``prompt`` is ``file://`` plus a persona
    temp file named ``studyloop-…``; the installer places a symlink into the
    repo, and anything the learner writes by hand has neither property. A
    backup only has meaning while this file sits on the target: restoring it
    over anything else (teardown after an ACP session that never swapped,
    crash recovery after the learner reinstalled) would overwrite the
    learner's current agent with an old copy -- seen 2026-10-12 with a 17 Sep
    backup lined up against an 11 Oct installer symlink.
    """
    if target.is_symlink() or not target.is_file():
        return False
    try:
        prompt = json.loads(target.read_text()).get("prompt", "")
    except (OSError, ValueError, AttributeError):
        return False
    if not isinstance(prompt, str) or not prompt.startswith("file://"):
        return False
    return Path(prompt[len("file://") :]).name.startswith("studyloop-")


def _discard_obsolete_backup(backup: Path, target: Path) -> None:
    logger.warning(
        "Kiro agent backup %s does not belong to the current %s (reinstalled since a "
        "crashed session?); discarding the backup and leaving the agent file alone",
        backup,
        target,
    )
    backup.unlink(missing_ok=True)


def _kiro_setup(
    canonical_content: str, _session_dir: Path, *, agents_dir: Path | None = None
) -> Path:
    """Write persona temp file and update Kiro agent JSON atomically.

    ``agents_dir`` overrides the module's ``KIRO_AGENTS_DIR`` (the
    ``agent_launcher`` wrappers pass theirs so tests patching that module's
    constant keep reaching the one implementation).
    """
    kiro_agents_dir = agents_dir if agents_dir is not None else KIRO_AGENTS_DIR
    # 1. Write canonical content to a temp persona file
    fd, persona_path = tempfile.mkstemp(
        prefix="studyloop-kiro-persona-",
        suffix=".md",
        dir=tempfile.gettempdir(),
    )
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(canonical_content)

    # 2. Load the base agent template
    template_path = _template_path()
    if template_path.exists():
        agent_def = json.loads(template_path.read_text())
    else:
        agent_def = {
            "name": KIRO_AGENT_NAME,
            "description": "Socratic study mentor",
        }

    # 3. Update prompt to reference the temp persona file
    agent_def["prompt"] = f"file://{persona_path}"

    # 4. Ensure target directory exists
    kiro_agents_dir.mkdir(parents=True, exist_ok=True)
    target = kiro_agents_dir / f"{KIRO_AGENT_NAME}.json"
    backup = target.with_suffix(target.suffix + _KIRO_BACKUP_SUFFIX)

    # 4a. Recover from crash: if a backup exists, the previous session's
    # teardown never ran. Restore the user's original config first -- but
    # only over StudyLoop's own leftover (or an empty slot); see
    # _is_studyloop_swap for why anything else keeps what is there now.
    if os.path.lexists(backup):
        if not os.path.lexists(target) or _is_studyloop_swap(target):
            logger.warning(
                "Stale Kiro backup detected (previous session crashed?) — restoring %s",
                backup,
            )
            os.replace(backup, target)
        else:
            _discard_obsolete_backup(backup, target)

    # 5. Backup existing agent JSON if present. A symlink (the installer's
    # layout) is backed up AS a symlink, so teardown hands the link back
    # rather than a regular-file copy of whatever it pointed at.
    if os.path.lexists(target):
        shutil.copy2(target, backup, follow_symlinks=False)

    # 6. Atomic write: temp file in same dir → os.replace()
    fd2, tmp_json = tempfile.mkstemp(
        prefix=f"{KIRO_AGENT_NAME}-",
        suffix=".json",
        dir=str(kiro_agents_dir),
    )
    with os.fdopen(fd2, "w") as f:
        json.dump(agent_def, f, indent=2)
    os.replace(tmp_json, target)

    return Path(persona_path)


def _kiro_launch(_persona_path: Path, resume: bool) -> str:
    """Build Kiro launch command."""
    # Quoted: the launch string runs under `/bin/sh -c` and in a tmux pane (F-CLI-23).
    binary = shlex.quote(shutil.which("kiro-cli") or shutil.which("kiro") or "kiro-cli")
    if resume:
        return f"{binary} chat --agent {KIRO_AGENT_NAME} --resume"
    return f"{binary} chat --agent {KIRO_AGENT_NAME}"


def _kiro_teardown(_session_dir: Path, *, agents_dir: Path | None = None) -> None:
    """Restore the backed-up Kiro agent JSON -- if this adapter's swap is what
    sits on the target. Teardown runs for every Kiro session end, including
    ACP sessions that launch the separate ``studyloop`` agent and never ran
    ``_kiro_setup``; a backup found then is a crashed session's leftover and
    is discarded, not restored over the learner's current file."""
    kiro_agents_dir = agents_dir if agents_dir is not None else KIRO_AGENTS_DIR
    target = kiro_agents_dir / f"{KIRO_AGENT_NAME}.json"
    backup = target.with_suffix(target.suffix + _KIRO_BACKUP_SUFFIX)
    if not os.path.lexists(backup):
        return
    if not os.path.lexists(target) or _is_studyloop_swap(target):
        os.replace(backup, target)
    else:
        _discard_obsolete_backup(backup, target)


ADAPTER = AgentAdapter(
    name="kiro",
    binary="kiro-cli",
    setup=_kiro_setup,
    launch_cmd=_kiro_launch,
    teardown=_kiro_teardown,
)
