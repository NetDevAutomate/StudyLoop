"""Practice-task verification and attempt recording."""

from __future__ import annotations

import json
import subprocess
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from studyloop.content.schemas import PracticeDeck, PracticeTask
from studyloop.history import _connection, record_progress


@dataclass(frozen=True)
class PracticeVerificationResult:
    practice_path: str
    task_index: int
    task_prompt: str
    verification_kind: str
    passed: bool
    notes: str
    command: str | None = None
    exit_code: int | None = None
    stdout: str = ""
    stderr: str = ""
    duration_seconds: float = 0.0
    expected_artifacts: list[str] | None = None
    missing_artifacts: list[str] | None = None
    rubric: list[str] | None = None
    evidence_prompts: list[str] | None = None
    setup_command: str = ""
    timeout_seconds: int = 60
    progress_recorded: bool = False

    def to_json_dict(self) -> dict:
        return asdict(self)


def load_practice_deck(path: Path) -> PracticeDeck:
    """Load and validate a practice deck JSON file."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        msg = f"Invalid practice JSON: {exc}"
        raise ValueError(msg) from exc
    return PracticeDeck.model_validate(raw)


def _task_at(deck: PracticeDeck, task_index: int) -> PracticeTask:
    if task_index < 1 or task_index > len(deck.tasks):
        msg = f"--task must be between 1 and {len(deck.tasks)}"
        raise ValueError(msg)
    return deck.tasks[task_index - 1]


def _expected_artifacts(task: PracticeTask) -> list[str]:
    if task.verification and task.verification.expected_artifacts:
        return list(task.verification.expected_artifacts)
    return []


def _missing_artifacts(artifacts: list[str], workdir: Path) -> list[str]:
    missing: list[str] = []
    for artifact in artifacts:
        candidate = (workdir / artifact).expanduser()
        if not candidate.exists():
            missing.append(artifact)
    return missing


def _verification_kind(task: PracticeTask) -> str:
    if task.verification:
        return task.verification.kind
    return "checklist"


def _verification_command(task: PracticeTask) -> str | None:
    if task.verification and task.verification.command:
        return task.verification.command
    return None


def peek_verification_command(practice_path: Path, *, task_index: int) -> tuple[str, str | None]:
    """Return ``(kind, command)`` for a task WITHOUT running or recording anything.

    A CLI (or any other caller) uses this to show the resolved command and
    obtain confirmation BEFORE :func:`verify_practice_task` -- which does the
    actual ``shell=True`` execution -- is ever invoked. The command comes
    from a practice-deck JSON file that may itself be LLM-authored (R-15);
    showing it before it runs is the human-in-the-loop gate the security
    review asked for.
    """
    resolved = practice_path.expanduser().resolve()
    deck = load_practice_deck(resolved)
    task = _task_at(deck, task_index)
    return _verification_kind(task), _verification_command(task)


def _verification_rubric(task: PracticeTask) -> list[str]:
    if task.verification and task.verification.rubric:
        return list(task.verification.rubric)
    return []


def _verification_evidence_prompts(task: PracticeTask) -> list[str]:
    if task.verification and task.verification.evidence_prompts:
        return list(task.verification.evidence_prompts)
    return []


def _verification_setup_command(task: PracticeTask) -> str:
    if task.verification and task.verification.setup_command:
        return task.verification.setup_command
    return ""


def _verification_timeout(task: PracticeTask, override: int | None) -> int:
    if override is not None:
        return override
    if task.verification:
        return task.verification.timeout_seconds
    return 60


def _record_attempt(result: PracticeVerificationResult, workdir: Path) -> None:
    conn = _connection._connect()
    if not conn:
        return
    try:
        conn.execute(
            """
            INSERT INTO practice_attempts
                (id, practice_path, task_index, task_prompt, verification_kind,
                 passed, notes, command, exit_code, stdout, stderr,
                 duration_seconds, expected_artifacts, missing_artifacts, workdir,
                 created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(uuid.uuid4()),
                result.practice_path,
                result.task_index,
                result.task_prompt,
                result.verification_kind,
                1 if result.passed else 0,
                result.notes,
                result.command,
                result.exit_code,
                result.stdout[-8000:],
                result.stderr[-8000:],
                result.duration_seconds,
                json.dumps(result.expected_artifacts or []),
                json.dumps(result.missing_artifacts or []),
                str(workdir),
                datetime.now(UTC).isoformat(),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def verify_practice_task(
    practice_path: Path,
    *,
    task_index: int,
    workdir: Path | None = None,
    run_command: bool = False,
    confirmed: bool = False,
    notes: str = "",
    timeout_seconds: int | None = None,
) -> PracticeVerificationResult:
    """Verify one practice task and record the attempt.

    ``confirmed`` is the human-in-the-loop gate for R-15: a practice deck is
    JSON a user pointed the CLI at, which may itself be LLM-authored, so
    ``verification.command`` is data the deck's author chose, not an
    instruction this function trusts blindly. ``run_command`` alone (the
    original gate) only asked "is command verification allowed at all";
    ``confirmed`` additionally asks "has THIS resolved command been shown to
    a human and approved" -- enforced here, independent of whatever a caller
    (the CLI's ``--yes``/interactive-prompt dance, see ``cli/_practice.py``)
    did upstream, so this function can never be made to run a command
    silently just because some other caller forgot to ask.
    """
    resolved = practice_path.expanduser().resolve()
    deck = load_practice_deck(resolved)
    task = _task_at(deck, task_index)
    wd = (workdir or Path.cwd()).expanduser().resolve()
    kind = _verification_kind(task)
    command = _verification_command(task)
    artifacts = _expected_artifacts(task)
    rubric = _verification_rubric(task)
    evidence_prompts = _verification_evidence_prompts(task)
    setup_command = _verification_setup_command(task)
    effective_timeout = _verification_timeout(task, timeout_seconds)
    missing = _missing_artifacts(artifacts, wd)
    started = time.monotonic()
    stdout = ""
    stderr = ""
    exit_code: int | None = None

    if kind == "command":
        if not run_command:
            msg = "Command verification requires --run-command."
            raise PermissionError(msg)
        if not command:
            msg = "Practice task verification.kind is command but no command is configured."
            raise ValueError(msg)
        if not confirmed:
            msg = (
                "Command verification requires confirmation before it runs "
                "(--yes, or an interactive y at the prompt)."
            )
            raise PermissionError(msg)
        try:
            completed = subprocess.run(
                command,
                shell=True,  # nosec B602 -- deck author's command, confirmed by a human just above
                cwd=wd,
                text=True,
                capture_output=True,
                timeout=effective_timeout,
                check=False,
            )
            exit_code = completed.returncode
            stdout = completed.stdout
            stderr = completed.stderr
        except subprocess.TimeoutExpired as exc:
            exit_code = -1
            stdout = exc.stdout if isinstance(exc.stdout, str) else ""
            stderr = exc.stderr if isinstance(exc.stderr, str) else "command timed out"
        passed = exit_code == 0 and not missing
    else:
        passed = bool(notes.strip()) and not missing

    duration = time.monotonic() - started
    confidence = "confident" if passed else "struggling"
    progress_recorded = record_progress(
        topic=deck.title.lower(),
        concept=task.expected_learning_outcome.lower(),
        confidence=confidence,
        notes=notes or f"Practice verification {'passed' if passed else 'failed'}",
        created_by="practice-verify",
    )

    result = PracticeVerificationResult(
        practice_path=str(resolved),
        task_index=task_index,
        task_prompt=task.prompt,
        verification_kind=kind,
        passed=passed,
        notes=notes,
        command=command,
        exit_code=exit_code,
        stdout=stdout,
        stderr=stderr,
        duration_seconds=round(duration, 3),
        expected_artifacts=artifacts,
        missing_artifacts=missing,
        rubric=rubric,
        evidence_prompts=evidence_prompts,
        setup_command=setup_command,
        timeout_seconds=effective_timeout,
        progress_recorded=progress_recorded,
    )
    _record_attempt(result, wd)
    return result
