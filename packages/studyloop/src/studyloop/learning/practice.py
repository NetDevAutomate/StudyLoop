"""Practice-task verification and attempt recording."""

from __future__ import annotations

import json
import subprocess
import time
import uuid
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from pathlib import Path

from agent_session_tools.context import records
from agent_session_tools.context.scope import ScopeError, active_policy
from studyloop.content.schemas import PracticeDeck, PracticeTask
from studyloop.history import _connection, observations


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


def _record_attempt(
    result: PracticeVerificationResult,
    workdir: Path,
    *,
    topic: str,
    concept: str,
    policy_digest: str,
    scope: str,
) -> bool:
    conn = _connection._connect()
    if not conn:
        return False
    try:
        identity = str(uuid.uuid4())
        with _connection.owned_write(conn):
            policy = active_policy()
            if policy.digest != policy_digest or policy.request_scope().value != scope:
                raise ScopeError("Context policy changed during practice; attempt not recorded")
            conn.execute(
                """
            INSERT INTO practice_attempts
                (id, practice_path, task_index, task_prompt, verification_kind,
                 passed, notes, command, exit_code, stdout, stderr,
                 duration_seconds, expected_artifacts, missing_artifacts, workdir,
                 created_at,topic,concept)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    identity,
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
                    topic,
                    concept,
                ),
            )
            owner_id = records.bind(conn, "practice_attempts", identity, owner_path=workdir)
            observation_id = observations.record(
                conn,
                topic,
                concept,
                "confident" if result.passed else "struggling",
                result.notes or f"Practice verification {'passed' if result.passed else 'failed'}",
                created_by="practice-verify",
                owner_path=workdir,
            )
            records.link_observation(conn, owner_id, observation_id)
            return True
    finally:
        conn.close()


def verify_practice_task(
    practice_path: Path,
    *,
    task_index: int,
    workdir: Path | None = None,
    run_command: bool = False,
    confirmed_command: str | None = None,
    notes: str = "",
    timeout_seconds: int | None = None,
) -> PracticeVerificationResult:
    """Verify one practice task and record the attempt.

    ``confirmed_command`` is the human-in-the-loop gate for R-15: a practice
    deck is JSON a user pointed the CLI at, which may itself be LLM-authored,
    so ``verification.command`` is data the deck's author chose, not an
    instruction this function trusts blindly. ``run_command`` alone (the
    original gate) only asks "is command verification allowed at all";
    ``confirmed_command`` additionally asks "has THIS EXACT resolved command
    been shown to a human and approved" -- enforced here, independent of
    whatever a caller (the CLI's ``--yes``/interactive-prompt dance, see
    ``cli/_practice.py``) did upstream, so this function can never be made
    to run a command silently just because some other caller forgot to ask.

    R-15b (TOCTOU): this takes the confirmed command as a STRING, not a
    bool. ``peek_verification_command`` (what a caller uses to show the
    command and obtain confirmation) and this function each reload the deck
    from disk independently -- a bare ``confirmed: bool`` could not detect
    the deck changing between those two reads, so a caller could be shown
    one command and have a DIFFERENT one executed. Passing the string closes
    that window: below, the freshly-reloaded command is compared against
    ``confirmed_command``, and execution is refused if they no longer match.
    ``None`` means "no confirmation offered" (the old ``confirmed=False``).

    R-15c: the only caller of this function (and of
    ``peek_verification_command``) anywhere in ``packages/studyloop/src`` is
    ``cli/_practice.py``'s ``practice_verify`` command -- confirmed by
    ``rg -n "verify_practice_task|peek_verification_command"
    packages/studyloop/src`` (see ``evidence/M4/R-15b/rg-callers.txt``). The
    CLI is therefore the trust boundary: it is what shows the command and
    obtains ``--yes``/interactive-``y`` confirmation before passing a
    non-``None`` ``confirmed_command`` here. A future MCP tool, web route,
    or other agent-facing caller that reaches this function MUST perform
    the same show-then-confirm step itself; there is no other gate.
    """
    resolved = practice_path.expanduser().resolve()
    wd = (workdir or Path.cwd()).expanduser().resolve()
    policy = active_policy()
    scope = policy.request_scope()
    for path in (resolved, wd):
        project = policy.project_for_path(path)
        if project and project.scope != scope:
            raise ScopeError("Practice content or working directory is outside the requested scope")
    deck = load_practice_deck(resolved)
    task = _task_at(deck, task_index)
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
        if confirmed_command is None:
            msg = (
                "Command verification requires confirmation before it runs "
                "(--yes, or an interactive y at the prompt)."
            )
            raise PermissionError(msg)
        if confirmed_command != command:
            msg = (
                "The practice deck's command changed since it was shown for "
                "confirmation; refusing to run a different command than the "
                "one approved."
            )
            raise PermissionError(msg)
        try:
            completed = subprocess.run(
                confirmed_command,
                cwd=wd,
                shell=True,  # nosec B602 -- deck author's command, confirmed by a human just above
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
        progress_recorded=False,
    )
    recorded = _record_attempt(
        result,
        wd,
        topic=deck.title.lower(),
        concept=task.expected_learning_outcome.lower(),
        policy_digest=policy.digest,
        scope=scope.value,
    )
    return replace(result, progress_recorded=recorded)


def list_practice_attempts(
    *, topic: str | None = None, days: int | None = None, limit: int = 20
) -> list[dict]:
    """Return permitted application check reports; these are not native attestations."""
    if type(limit) is not int or not 1 <= limit <= 200:
        raise ValueError("Practice history limit must be between 1 and 200")
    if days is not None and (type(days) is not int or days < 1):
        raise ValueError("Practice history days must be a positive integer")
    conn = _connection._connect()
    if not conn:
        return []
    try:
        clause, params = records.visible_sql(conn, "practice_attempts", "practice_attempts.id")
        if topic is not None:
            clause += " AND lower(topic) LIKE ?"
            params.append("%" + topic.lower() + "%")
        if days is not None:
            clause += " AND julianday(created_at)>julianday('now',?)"
            params.append(f"-{days} days")
        rows = conn.execute(
            "SELECT * FROM practice_attempts WHERE "
            + clause
            + " ORDER BY created_at DESC,id DESC LIMIT ?",
            [*params, limit],
        ).fetchall()
        return [
            {
                **dict(row),
                "authority": "application_report",
                "validation_of_learning": "not_established",
            }
            for row in rows
        ]
    finally:
        conn.close()
