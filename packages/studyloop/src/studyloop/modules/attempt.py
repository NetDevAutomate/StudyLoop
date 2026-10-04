"""Attempt identity, phases and exit classes for module drills (proposal §5.5, §5.7).

This module is the leaf of the ``attempt <- consent <- runner`` import chain: the types
every other runner module shares, the attempt directory lifecycle (:class:`AttemptStore`),
and the one write path a drill has -- :func:`record_phase`, the transient
``practice_check_events`` row (§5.7, wave-1 ruling 6). It stays free of ``subprocess``.

**Where the table lives and why the DDL is here.** The sessions database's schema is
versioned by ``agent_session_tools.migrations`` (``PRAGMA user_version``, ``CURRENT_VERSION``
48 at the time of writing, one ``@migration(n, ...)`` per step). That file is owned by
another lane (``lane_ownership.yaml`` m3: ``packages/agent-session-tools/**``), and a table
created from outside it cannot bump ``user_version`` without ``migrate()`` refusing the
database as "newer than supported". The repo already has a pattern for a StudyLoop-owned
table in the same database that does not touch ``user_version``:
``planning/index.py`` (``study_plans`` / ``study_plan_checkpoints``) connects through
``history._connection._connect`` -- which applies the base schema and every pending
migration first -- and then runs its own idempotent ``CREATE TABLE IF NOT EXISTS``.
:func:`ensure_schema` follows that pattern exactly; the coordinator may fold the DDL into a
numbered migration at merge, and ``IF NOT EXISTS`` makes that fold a no-op here.

Contract rows these types carry (proposal §5.5):

Contract rows these types carry (proposal §5.5):

- *Snapshot and identity*: drill identity is ``(module id, module digest, deck id, task
  id)``; ``STUDYLOOP_DRILL_ID`` is ``<deck id>/<task id>``.
- *Working directory*: a core-created per-attempt directory (``Attempt.attempt_dir``).
- *Exit codes*: ``check`` ``0`` = passed, ``1`` = failed (task not complete), ``>= 2`` =
  error; ``setup`` any non-zero = error; a timeout is always an error.
- §5.7: a completed check records a **transient** ``practice_check`` event on the attempt
  and never an observation, mastery row, learning record or review item. The row holds
  identity, phase, exit class and code, duration, truncation flags and the delivery
  outcome -- **no output text**: redacted stdout/stderr tails are kept only as the
  attempt's own evidence in its sidecar record (:meth:`AttemptStore.record_evidence`).
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import stat
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, Protocol

if TYPE_CHECKING:
    import sqlite3

logger = logging.getLogger(__name__)


class Phase(StrEnum):
    """The three phases of a drill; each is one consented execution (§5.5)."""

    SETUP = "setup"
    CHECK = "check"
    CLEANUP = "cleanup"


class TargetKind(StrEnum):
    """``target.kind`` of a drill (§5.3 / §5.5 *Working directory* and *Kubernetes identity*)."""

    WORKDIR = "workdir"
    KUBECONFIG_CONTEXT = "kubeconfig-context"


class ExitClass(StrEnum):
    """How a finished phase is classified (§5.5 *Exit codes*).

    ``FAILED`` means *task not complete* -- the learner's work did not satisfy the check.
    ``ERROR`` means the check could not run (script error, unreachable target, timeout).
    """

    PASSED = "passed"
    FAILED = "failed"
    ERROR = "error"


class SidecarError(RuntimeError):
    """The attempt's sidecar record path is not what the store wrote (symlink, foreign file)."""


class RefusalError(Exception):
    """Base of every refusal raised **before** a child process is spawned.

    When a ``RefusalError`` propagates nothing ran, nothing was written to the attempt
    directory by a module script, and nothing was recorded.
    """


@dataclass(frozen=True)
class DrillIdentity:
    """``(module id, module digest, deck id, task id)`` -- proposal §5.5 *Snapshot and identity*."""

    module_id: str
    module_digest: str
    deck_id: str
    task_id: str

    @property
    def drill_id(self) -> str:
        """``STUDYLOOP_DRILL_ID``: ``<deck id>/<task id>`` (§5.5)."""
        return f"{self.deck_id}/{self.task_id}"


@dataclass(frozen=True)
class Attempt:
    """One attempt at one drill, bound to one immutable module snapshot.

    ``snapshot_dir`` is the module snapshot taken at ``module add``; every script a phase
    runs must be a regular file inside it (MC013). ``attempt_dir`` is the core-created
    per-attempt working directory, which also hosts the child's scratch ``HOME``/XDG dirs.
    ``kubeconfig`` is set only for ``TargetKind.KUBECONFIG_CONTEXT`` and is the
    core-written file containing exactly the disposable cluster's one context.
    """

    attempt_id: str
    drill: DrillIdentity
    snapshot_dir: Path
    attempt_dir: Path
    target: TargetKind = TargetKind.WORKDIR
    kubeconfig: Path | None = None


@dataclass(frozen=True)
class OutputCaps:
    """Streamed-output caps the runner enforces while the child runs (spec, ruling 2).

    ``stdout_bytes`` and ``stderr_bytes`` bound each stream separately; ``lines`` bounds the
    two streams together. Hitting any cap terminates the child, records ``truncated`` and
    classes the phase ``ERROR`` naming the cap (ruling 3) -- a flooding check is not a
    trustworthy pass.
    """

    stdout_bytes: int = 64 * 1024
    stderr_bytes: int = 16 * 1024
    lines: int = 2_000


#: The spec's values: 64 KiB stdout, 16 KiB stderr, 2,000 lines in total.
DEFAULT_CAPS = OutputCaps()


@dataclass(frozen=True)
class PhaseResult:
    """What one phase execution produced, after redaction and truncation.

    ``stdout`` and ``stderr`` are the captured streams, cut at their caps (``truncated``
    records that one was hit and ``cap_hit`` names which: ``"stdout"``, ``"stderr"`` or
    ``"lines"``) and redacted by the secret detector before anything is persisted, shown or
    delivered. ``exit_code`` is ``None`` when the runner stopped the child (timeout or cap)
    before it exited on its own. ``message`` is the one-line human reading of the outcome
    the CLI prints and the mentor hop forwards verbatim.
    """

    phase: Phase
    exit_class: ExitClass
    exit_code: int | None
    stdout: str
    stderr: str
    truncated: bool
    timed_out: bool
    duration_seconds: float
    cap_hit: str | None = None
    message: str = ""
    process_returncode: int | None = None

    @property
    def output(self) -> str:
        """stdout followed by stderr -- the combined transient evidence."""
        return self.stdout + self.stderr


DeliveryStatus = Literal[
    "delivered",
    "no_active_session",
    "transport_closed",
    "timed_out",
    "unsupported_framing",
    "error",
]


@dataclass(frozen=True)
class DeliveryOutcome:
    """What happened when the phase result was handed to the mentor (M0 Q2/Q6: six states).

    ``status`` is one of the six reachable outcomes; ``reason`` is the detail the learner
    sees after ``Mentor not told:`` (empty when delivered). Recorded on the
    ``practice_check_events`` row as ``delivery_status`` / ``delivery_reason``.
    """

    status: DeliveryStatus
    reason: str = ""

    @property
    def delivered(self) -> bool:
        return self.status == "delivered"


# ---------------------------------------------------------------------------
# practice_check_events -- the transient record (§5.7, ruling 6)
# ---------------------------------------------------------------------------

PRACTICE_CHECK_EVENTS_DDL = """
CREATE TABLE IF NOT EXISTS practice_check_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    attempt_id TEXT NOT NULL,
    module_id TEXT NOT NULL,
    module_digest TEXT NOT NULL,
    deck_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    phase TEXT NOT NULL CHECK (phase IN ('setup', 'check', 'cleanup')),
    exit_class TEXT NOT NULL CHECK (exit_class IN ('passed', 'failed', 'error')),
    exit_code INTEGER,
    duration_seconds REAL NOT NULL,
    timed_out INTEGER NOT NULL DEFAULT 0 CHECK (timed_out IN (0, 1)),
    truncated INTEGER NOT NULL DEFAULT 0 CHECK (truncated IN (0, 1)),
    cap_hit TEXT CHECK (cap_hit IS NULL OR cap_hit IN ('stdout', 'stderr', 'lines')),
    delivery_status TEXT NOT NULL CHECK (delivery_status IN (
        'delivered', 'no_active_session', 'transport_closed', 'timed_out',
        'unsupported_framing', 'error')),
    delivery_reason TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
)
"""

_PRACTICE_CHECK_EVENTS_INDEXES = (
    "CREATE INDEX IF NOT EXISTS idx_practice_check_events_attempt "
    "ON practice_check_events(attempt_id, phase)",
    "CREATE INDEX IF NOT EXISTS idx_practice_check_events_drill "
    "ON practice_check_events(module_id, deck_id, task_id, created_at DESC)",
)


def ensure_schema(conn: sqlite3.Connection) -> None:
    """Create ``practice_check_events`` and its indexes if missing (idempotent)."""
    conn.execute(PRACTICE_CHECK_EVENTS_DDL)
    for statement in _PRACTICE_CHECK_EVENTS_INDEXES:
        conn.execute(statement)


def _connect() -> sqlite3.Connection | None:
    """The sessions database with the base schema, every migration, and our table applied.

    Goes through ``history._connection._connect`` -- the same door ``planning/index.py``
    uses -- looked up at call time so a test that re-points that module's ``_connect`` at a
    temporary database re-points this one too. ``None`` when the database is unavailable;
    the caller treats that as "not recorded", never as success.
    """
    try:
        from studyloop.history import _connection
    except Exception:  # pragma: no cover - import guard
        logger.debug("history._connection unavailable", exc_info=True)
        return None
    conn = _connection._connect()
    if conn is None:
        return None
    try:
        ensure_schema(conn)
        conn.commit()
    except Exception:
        logger.debug("could not ensure practice_check_events schema", exc_info=True)
        conn.close()
        return None
    return conn


def record_phase(attempt: Attempt, result: PhaseResult, *, delivery: DeliveryOutcome) -> int | None:
    """Insert one ``practice_check_events`` row for a completed phase (§5.7, ruling 6).

    Writes nothing else: no ``study_progress``, no observation, no learning record, no
    review item, and no output text. Returns the new row id, or ``None`` when the sessions
    database could not be opened (logged; the CLI tells the learner).
    """
    conn = _connect()
    if conn is None:
        return None
    try:
        cursor = conn.execute(
            """
            INSERT INTO practice_check_events (
                attempt_id, module_id, module_digest, deck_id, task_id,
                phase, exit_class, exit_code, duration_seconds,
                timed_out, truncated, cap_hit, delivery_status, delivery_reason
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                attempt.attempt_id,
                attempt.drill.module_id,
                attempt.drill.module_digest,
                attempt.drill.deck_id,
                attempt.drill.task_id,
                result.phase.value,
                result.exit_class.value,
                result.exit_code,
                result.duration_seconds,
                1 if result.timed_out else 0,
                1 if result.truncated else 0,
                result.cap_hit,
                delivery.status,
                delivery.reason,
            ),
        )
        conn.commit()
        return cursor.lastrowid
    except Exception:
        logger.exception("practice_check_events insert failed for attempt %s", attempt.attempt_id)
        return None
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# AttemptStore -- the per-attempt directory and its sidecar record (R5)
# ---------------------------------------------------------------------------


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


@dataclass
class AttemptStore:
    """Opens, finds and closes attempts under ``root``.

    Layout: ``<root>/<module id>/<deck id>/<task id>/<attempt id>/`` is the attempt
    directory -- the child's cwd and the parent of its scratch ``HOME`` -- and
    ``<root>/<module id>/<deck id>/<task id>/<attempt id>.json`` is the sidecar record
    (opened/closed timestamps, close reason, per-phase evidence). The sidecar sits *beside*
    the attempt directory, not inside it, so a module script running in the attempt
    directory cannot rewrite its own record. At most one attempt per drill is open at a
    time: :meth:`current` returns it, :meth:`close` ends it, and :meth:`open` always starts
    a fresh one.
    """

    root: Path

    def _drill_dir(self, drill: DrillIdentity) -> Path:
        return self.root / drill.module_id / drill.deck_id / drill.task_id

    def _record_path(self, attempt: Attempt) -> Path:
        return self._drill_dir(attempt.drill) / f"{attempt.attempt_id}.json"

    @staticmethod
    def _ensure_private_dir(path: Path) -> None:
        """``mkdir -p`` then force ``0o700`` on the leaf (``mkdir(mode=)`` is umask-subject)."""
        path.mkdir(parents=True, exist_ok=True)
        os.chmod(path, 0o700)

    @staticmethod
    def _refuse_if_not_regular(path: Path, *, must_exist: bool) -> None:
        """M1 Q7: the sidecar path must be absent or a regular file -- never a symlink."""
        try:
            st = os.lstat(path)
        except FileNotFoundError:
            if must_exist:
                raise SidecarError(f"attempt record {path.name} is missing") from None
            return
        if not stat.S_ISREG(st.st_mode):
            raise SidecarError(
                f"attempt record {path.name} is not a regular file (symlink or special file "
                "planted at the sidecar path); refusing to read or write it"
            )

    def _read(self, path: Path) -> dict[str, Any] | None:
        self._refuse_if_not_regular(path, must_exist=False)
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise SidecarError(f"attempt record {path.name} unreadable: {exc.strerror}") from exc
        try:
            with os.fdopen(fd, encoding="utf-8") as handle:
                data = json.loads(handle.read())
        except (OSError, json.JSONDecodeError):
            return None
        return data if isinstance(data, dict) else None

    def _write(self, path: Path, record: dict[str, Any]) -> None:
        """Write the sidecar: ``O_EXCL | O_NOFOLLOW`` temp file in a ``0o700`` directory, then
        an atomic rename. Called only after the child has exited (the caller's contract), so
        a running module script cannot race the record it is being judged by."""
        self._ensure_private_dir(path.parent)
        self._refuse_if_not_regular(path, must_exist=False)
        tmp = path.with_suffix(".json.tmp")
        try:
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        except FileExistsError as exc:
            raise SidecarError(
                f"attempt record temp file {tmp.name} already exists (planted or a crashed "
                "earlier write); refusing to write over it"
            ) from exc
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(json.dumps(record, indent=2, sort_keys=True))
                handle.flush()
                os.fsync(handle.fileno())
            # Re-check the destination right before the rename: a symlink planted between the
            # first check and now would be *replaced*, not followed, but we refuse anyway so a
            # tampered path is loud rather than silently rewritten.
            self._refuse_if_not_regular(path, must_exist=False)
            os.replace(tmp, path)
        except BaseException:
            with contextlib.suppress(OSError):
                tmp.unlink()
            raise

    def _attempt_from(self, record: dict[str, Any]) -> Attempt:
        drill = DrillIdentity(**record["drill"])
        kubeconfig = record.get("kubeconfig")
        return Attempt(
            attempt_id=record["attempt_id"],
            drill=drill,
            snapshot_dir=Path(record["snapshot_dir"]),
            attempt_dir=Path(record["attempt_dir"]),
            target=TargetKind(record.get("target", TargetKind.WORKDIR.value)),
            kubeconfig=Path(kubeconfig) if kubeconfig else None,
        )

    def open(
        self,
        drill: DrillIdentity,
        *,
        snapshot_dir: Path,
        target: TargetKind = TargetKind.WORKDIR,
        kubeconfig: Path | None = None,
    ) -> Attempt:
        """Create a new attempt directory (mode ``0o700``) and its sidecar record."""
        attempt_id = str(uuid.uuid4())
        drill_dir = self._drill_dir(drill)
        self._ensure_private_dir(drill_dir)
        attempt_dir = drill_dir / attempt_id
        attempt_dir.mkdir(mode=0o700)
        os.chmod(attempt_dir, 0o700)
        attempt = Attempt(
            attempt_id=attempt_id,
            drill=drill,
            snapshot_dir=snapshot_dir,
            attempt_dir=attempt_dir,
            target=target,
            kubeconfig=kubeconfig,
        )
        record: dict[str, Any] = {
            "attempt_id": attempt_id,
            "drill": asdict(drill),
            "snapshot_dir": str(snapshot_dir),
            "attempt_dir": str(attempt_dir),
            "target": target.value,
            "kubeconfig": str(kubeconfig) if kubeconfig else None,
            "opened_at": _now(),
            "closed_at": None,
            "close_reason": None,
            "phases": [],
        }
        self._write(self._record_path(attempt), record)
        return attempt

    def current(self, drill: DrillIdentity) -> Attempt | None:
        """The one open attempt for ``drill``, or ``None``.

        Newest open record wins if more than one is somehow open (only the CLI opens
        attempts, one at a time, so this is a repair path rather than a feature).
        """
        drill_dir = self._drill_dir(drill)
        if not drill_dir.is_dir():
            return None
        candidates: list[tuple[str, dict[str, Any]]] = []
        for path in drill_dir.glob("*.json"):
            if not stat.S_ISREG(os.lstat(path).st_mode):
                logger.warning("ignoring non-regular file in attempts dir: %s", path.name)
                continue
            record = self._read(path)
            if record is None or record.get("closed_at") is not None:
                continue
            candidates.append((str(record.get("opened_at", "")), record))
        if not candidates:
            return None
        candidates.sort(key=lambda item: item[0])
        return self._attempt_from(candidates[-1][1])

    def close(self, attempt: Attempt, *, reason: str) -> None:
        """Mark the attempt closed with ``reason``; idempotent (a second close is a no-op)."""
        path = self._record_path(attempt)
        record = self._read(path)
        if record is None:
            return
        if record.get("closed_at") is None:
            record["closed_at"] = _now()
            record["close_reason"] = reason
            self._write(path, record)

    def record_evidence(
        self, attempt: Attempt, result: PhaseResult, *, delivery: DeliveryOutcome
    ) -> None:
        """Append the (already redacted) phase outcome to the attempt's sidecar record.

        This is the §5.5 *Output* "kept for the attempt only": the transient evidence a
        learner or the coordinator can read back for this attempt. It is not learner
        history and nothing reads it into the mentor or the dashboard. Called by the CLI
        only after ``run_phase`` has returned -- i.e. after the child has exited and been
        reaped -- so no module process is alive while its record is written (M1 Q7).
        """
        path = self._record_path(attempt)
        record = self._read(path)
        if record is None:
            return
        phases = record.setdefault("phases", [])
        phases.append(
            {
                "at": _now(),
                "phase": result.phase.value,
                "exit_class": result.exit_class.value,
                "exit_code": result.exit_code,
                "duration_seconds": result.duration_seconds,
                "timed_out": result.timed_out,
                "truncated": result.truncated,
                "cap_hit": result.cap_hit,
                "message": result.message,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "delivery_status": delivery.status,
                "delivery_reason": delivery.reason,
            }
        )
        self._write(path, record)


# ---------------------------------------------------------------------------
# What the CLI needs from lane C's store, as a Protocol (R6 cross-lane seam)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class InstalledModule:
    """The three facts ``studyloop drill`` needs about an installed module.

    Lane C's ``modules/store.py`` (``load_lockfile()``, ``LockEntry``, ``snapshot_dir(entry)``)
    is the source of truth once it merges; until then :class:`ModuleLocator` is the seam the
    CLI calls and the coordinator reconciles at merge.
    """

    module_id: str
    module_digest: str
    snapshot_dir: Path


class ModuleNotInstalledError(LookupError):
    """No lockfile entry for the module id (``studyloop module list`` shows what is installed)."""


class ModuleLocator(Protocol):
    """``locator(module_id) -> InstalledModule`` or raise :class:`ModuleNotInstalledError`."""

    def __call__(self, module_id: str) -> InstalledModule: ...
