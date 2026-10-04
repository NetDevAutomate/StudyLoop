"""Runner, consent and attempt tests for the module drill runner (module-contract-v1, lane R).

Born as R1's adversarial red suite, grown through R2-R5. Two kinds of test live here:

* **The two (a) reds** -- :func:`test_drill_writes_no_observation` and
  :func:`test_runner_never_shell` -- were first run against the only verification path
  StudyLoop had (``learning/practice.py``) and failed on their *assertion* there: a check
  wrote a ``confident``/``struggling`` observation into learner history (``_record_attempt``,
  ~lines 179-188) and the confirmed command string went through ``shell=True`` (~282-290).
  Those transcripts are ``evidence/R/no-observation.red.txt`` and ``never-shell.red.txt``.
  Both now drive the runner's own path with the same assertions.
* **Boundary tests against the runner** -- the attacks the M1 council reads (``design.md``
  §7, §9) plus the wave-1 rulings: shell tokens, MC013 at runtime, the clean environment,
  digest race, consent replay/forgery/expiry, timeouts, streamed caps, redaction, the exit
  table, and the transient ``practice_check_events`` record.

Every target script a test writes is a real ``#!/bin/sh`` file inside a temporary module
snapshot. The runner under test must never pass a *string* to a shell; the scripts
themselves may use any shell construct they like -- they are the untrusted module content
the boundary exists to contain.
"""

from __future__ import annotations

import contextlib
import hashlib
import os
import sqlite3
import subprocess
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from test_practice_verify import _attempt_db, _patch_db

from studyloop.modules import runner
from studyloop.modules.attempt import (
    DEFAULT_CAPS,
    Attempt,
    AttemptStore,
    DeliveryOutcome,
    DrillIdentity,
    ExitClass,
    OutputCaps,
    Phase,
    SidecarError,
    record_phase,
)
from studyloop.modules.consent import (
    CONSENT_TTL_SECONDS,
    Consent,
    ConsentExpiredError,
    ConsentLedger,
    ConsentMismatchError,
    ConsentReplayedError,
    ConsentUnknownError,
    DigestMismatchError,
    describe_consent,
)
from studyloop.modules.runner import (
    ArgvLengthError,
    PrerequisiteError,
    ScriptPathError,
    ShellTokenError,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from studyloop.modules.attempt import PhaseResult

# ---------------------------------------------------------------------------
# Shared world: a temporary module snapshot, one attempt, one consent ledger
# ---------------------------------------------------------------------------

MODULE_ID = "example-module"
DRILL = DrillIdentity(
    module_id=MODULE_ID,
    module_digest="sha256:" + hashlib.sha256(b"snapshot-digest-fixture").hexdigest(),
    deck_id="pods",
    task_id="create-nginx",
)
EXPECTED_DRILL_ID = "pods/create-nginx"

DOCUMENTED_CHILD_VARIABLES = frozenset(
    {
        "STUDYLOOP_MODULE_ID",
        "STUDYLOOP_DRILL_ID",
        "STUDYLOOP_ATTEMPT_ID",
        "STUDYLOOP_ATTEMPT_DIR",
        "KUBECONFIG",
        "PATH",
        "HOME",
    }
)
"""Every non-XDG name the child may see: proposal §5.5 *Environment* names the three
``STUDYLOOP_*`` variables, ``KUBECONFIG`` (when applicable), "a minimal ``PATH``" and "a
scratch ``HOME``/XDG"; the wave-1 brief (R2) adds ``STUDYLOOP_ATTEMPT_DIR``. Which ``XDG_*``
names are set is a contract gap; the test accepts any ``XDG_*`` name whose value lives under
the attempt directory and nothing else."""


def _sha256(path: Path) -> str:
    """Independent digest so the runner's recomputation is checked against, not trusted."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


@dataclass
class SpawnCall:
    """One ``subprocess.Popen`` construction as the runner (or today's path) made it."""

    args: Any
    kwargs: dict[str, Any]
    process: subprocess.Popen[Any]


@pytest.fixture
def spawn_spy(monkeypatch: pytest.MonkeyPatch) -> list[SpawnCall]:
    """Record every ``subprocess.Popen`` construction, then delegate to the real one.

    ``subprocess.run`` resolves ``Popen`` through the module global, so this single patch
    observes today's ``practice.py`` (``subprocess.run``) and tomorrow's runner alike.
    """
    calls: list[SpawnCall] = []
    real_popen = subprocess.Popen

    def recording_popen(args: Any, *rest: Any, **kwargs: Any) -> subprocess.Popen[Any]:
        process = real_popen(args, *rest, **kwargs)
        calls.append(SpawnCall(args=args, kwargs=dict(kwargs), process=process))
        return process

    monkeypatch.setattr(subprocess, "Popen", recording_popen)
    return calls


@dataclass(frozen=True)
class World:
    attempt: Attempt
    ledger: ConsentLedger

    @property
    def scripts(self) -> Path:
        return self.attempt.snapshot_dir / "scripts"

    def script(self, name: str, body: str) -> Path:
        """Write ``scripts/<name>`` into the snapshot as an executable ``#!/bin/sh`` target."""
        path = self.scripts / name
        path.write_text("#!/bin/sh\n" + body.rstrip("\n") + "\n", encoding="utf-8")
        path.chmod(0o755)
        return path

    def consent(self, phase: Phase, argv: Sequence[str]) -> Consent:
        """Issue a consent the way the CLI will: after computing the digest of what was shown."""
        digest = _sha256(self.attempt.snapshot_dir / argv[0])
        return self.ledger.issue(self.attempt, phase, argv, script_digest=digest)

    def forged_consent(self, phase: Phase, argv: Sequence[str], *, digest: str) -> Consent:
        """A consent object that exists but was never issued by the ledger.

        Used where the runner must refuse *before* it ever consults the ledger (argv and
        path validation): if the refusal came from the ledger, the test would be passing
        for the wrong reason.
        """
        return Consent(
            consent_id=f"forged-{uuid.uuid4()}",
            attempt_id=self.attempt.attempt_id,
            phase=phase,
            argv=tuple(argv),
            script_digest=digest,
            target=str(self.attempt.attempt_dir),
        )

    def run(
        self,
        phase: Phase,
        argv: Sequence[str],
        *,
        consent: Consent | None = None,
        timeout_seconds: int = 10,
        caps: OutputCaps = DEFAULT_CAPS,
        prerequisites: Sequence[str] = (),
    ) -> PhaseResult:
        return runner.run_phase(
            self.attempt,
            phase,
            argv,
            consent=consent if consent is not None else self.consent(phase, argv),
            ledger=self.ledger,
            timeout_seconds=timeout_seconds,
            caps=caps,
            prerequisites=prerequisites,
        )

    def ran_marker(self, name: str = "ran.marker") -> bool:
        return (self.attempt.attempt_dir / name).exists()


@pytest.fixture
def world(tmp_path: Path) -> World:
    snapshot = tmp_path / "snapshot"
    (snapshot / "scripts").mkdir(parents=True)
    attempt_dir = tmp_path / "attempts" / "attempt-1"
    attempt_dir.mkdir(parents=True)
    attempt = Attempt(
        attempt_id=f"attempt-{uuid.uuid4()}",
        drill=DRILL,
        snapshot_dir=snapshot,
        attempt_dir=attempt_dir,
    )
    return World(attempt=attempt, ledger=ConsentLedger())


# ---------------------------------------------------------------------------
# (a) Meaningful reds against today's code -- fail on the assertion, not on import
# ---------------------------------------------------------------------------


def _table_rows(db: Path, table: str) -> int:
    with contextlib.closing(sqlite3.connect(db)) as conn:
        return conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]


LEARNER_HISTORY_TABLES = ("context_observations", "study_progress", "practice_attempts")
"""What §5.7 forbids a check from touching: the observation store, mastery, and today's
``practice verify`` attempt table (which binds an observation per row)."""


def test_drill_writes_no_observation(
    world: World, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """§5.7: a completed check records a transient ``practice_check`` event on the attempt and
    never a learning record. R1 drove today's only verification path, ``learning/practice.py``
    ``_record_attempt`` (~179-188), which writes a ``confident``/``struggling`` observation
    after every check, and failed on this assertion (``evidence/R/no-observation.red.txt``).
    The drive is now the runner's own path -- ``runner.run_phase`` then
    ``attempt.record_phase`` into the same sessions database -- and the assertion is the one
    R1 wrote: the observation row count is **unchanged**. The spec scenario adds
    ``study_progress`` unchanged and exactly one ``practice_check`` event."""
    db = _attempt_db(tmp_path)
    _patch_db(monkeypatch, db)
    before = {table: _table_rows(db, table) for table in LEARNER_HISTORY_TABLES}
    world.script("check.sh", "echo all good\nexit 0")
    argv = ("scripts/check.sh",)

    result = world.run(Phase.CHECK, argv)
    row_id = record_phase(
        world.attempt, result, delivery=DeliveryOutcome("no_active_session", "no state file")
    )

    assert result.exit_class is ExitClass.PASSED  # the check passed; what matters is the record
    after = {table: _table_rows(db, table) for table in LEARNER_HISTORY_TABLES}
    assert after["context_observations"] == before["context_observations"], (
        f"a passing check wrote {after['context_observations'] - before['context_observations']} "
        "observation row(s) into learner history; §5.7 forbids any -- a check is transient"
    )
    assert after == before, f"learner history changed: {before} -> {after}"
    assert row_id is not None
    assert _table_rows(db, "practice_check_events") == 1


def test_practice_check_event_row_carries_identity_outcome_and_delivery(
    world: World, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Ruling 6: one row per phase completion in ``practice_check_events`` of the sessions
    database -- identity (module id + digest, deck id, task id), attempt id, phase, exit
    class and code, duration, truncation flags, delivery status and reason. The row holds
    no output text: output is transient evidence of the attempt, not a learning record."""
    db = _attempt_db(tmp_path)
    _patch_db(monkeypatch, db)
    world.script("check.sh", "echo nope >&2\nexit 1")
    argv = ("scripts/check.sh",)

    result = world.run(Phase.CHECK, argv)
    record_phase(world.attempt, result, delivery=DeliveryOutcome("delivered"))

    with contextlib.closing(sqlite3.connect(db)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM practice_check_events").fetchall()
        columns = {row[1] for row in conn.execute("PRAGMA table_info(practice_check_events)")}
    assert len(rows) == 1
    row = rows[0]
    assert row["attempt_id"] == world.attempt.attempt_id
    assert row["module_id"] == MODULE_ID
    assert row["module_digest"] == DRILL.module_digest
    assert row["deck_id"] == DRILL.deck_id
    assert row["task_id"] == DRILL.task_id
    assert row["phase"] == "check"
    assert row["exit_class"] == "failed"
    assert row["exit_code"] == 1
    assert row["duration_seconds"] == pytest.approx(result.duration_seconds)
    assert row["timed_out"] == 0
    assert row["truncated"] == 0
    assert row["cap_hit"] is None
    assert row["delivery_status"] == "delivered"
    assert row["delivery_reason"] == ""
    assert row["created_at"]
    assert not {"stdout", "stderr", "output"} & columns, "output text must not be persisted"


def test_attempt_store_opens_finds_and_closes_one_attempt_per_drill(tmp_path: Path) -> None:
    """R5: an attempt is a core-created directory plus a sidecar record outside the child's
    cwd. ``current`` finds the one open attempt for a drill; ``close`` ends it (with the
    reason the CLI gives, e.g. a failed cleanup) and the next ``open`` is a new attempt."""
    snapshot = tmp_path / "snapshot"
    (snapshot / "scripts").mkdir(parents=True)
    store = AttemptStore(root=tmp_path / "attempts")

    assert store.current(DRILL) is None
    first = store.open(DRILL, snapshot_dir=snapshot)

    assert first.attempt_dir.is_dir()
    assert first.attempt_dir.is_relative_to(store.root)
    assert first.drill == DRILL
    assert first.snapshot_dir == snapshot
    assert store.current(DRILL) == first
    assert not any(first.attempt_dir.iterdir()), "the child's cwd starts empty"

    store.close(first, reason="cleanup failed (exit 3; error) -- the attempt is closed anyway")

    assert store.current(DRILL) is None
    second = store.open(DRILL, snapshot_dir=snapshot)
    assert second.attempt_id != first.attempt_id
    assert second.attempt_dir != first.attempt_dir
    assert store.current(DRILL) == second


def test_runner_never_shell(world: World, spawn_spy: list[SpawnCall]) -> None:
    """§5.5 *Invocation*: a phase is spawned as an argv **list** with ``shell=False`` --
    no shell, ever. R1 drove today's path (``learning/practice.py`` ~282-290), which hands
    the confirmed command *string* to ``subprocess.run(..., shell=True)``, and failed on
    this assertion (``evidence/R/never-shell.red.txt``). The drive is now the runner's
    own path; the assertion is unchanged. The spawn argv is the resolved script followed
    by the literal arguments, each one its own list element."""
    world.script("check.sh", "exit 0")
    argv = ("scripts/check.sh", "literal arg with spaces", "--flag=value")

    result = world.run(Phase.CHECK, argv)

    assert result.exit_class is ExitClass.PASSED
    assert spawn_spy, "no subprocess was spawned, so nothing was verified"
    for call in spawn_spy:
        shell = call.kwargs.get("shell", False)
        assert shell is False, f"verification spawned with shell={shell!r}: {call.args!r}"
        assert isinstance(call.args, list), (
            f"argv was passed as {type(call.args).__name__}, not a list: {call.args!r}"
        )
    spawned = spawn_spy[0].args
    assert spawned[1:] == ["literal arg with spaces", "--flag=value"]
    assert Path(spawned[0]).resolve() == (world.scripts / "check.sh").resolve()
    assert Path(spawned[0]).is_absolute(), "argv[0] must be the resolved script, not a PATH lookup"


def test_pre_planted_symlink_at_the_sidecar_path_is_refused(tmp_path: Path) -> None:
    """M1 Q7: the sidecar is written with ``O_EXCL | O_NOFOLLOW`` into a 0o700 directory. A
    symlink planted where the record lives is refused -- the target it points at is never
    written -- rather than followed."""
    snapshot = tmp_path / "snapshot"
    (snapshot / "scripts").mkdir(parents=True)
    store = AttemptStore(root=tmp_path / "attempts")
    attempt = store.open(DRILL, snapshot_dir=snapshot)
    record_path = store.root / DRILL.module_id / DRILL.deck_id / DRILL.task_id
    record_path = record_path / f"{attempt.attempt_id}.json"
    assert record_path.is_file()
    assert (record_path.parent.stat().st_mode & 0o777) == 0o700
    victim = tmp_path / "victim.txt"
    victim.write_text("untouched", encoding="utf-8")
    record_path.unlink()
    record_path.symlink_to(victim)

    with pytest.raises(SidecarError):
        store.close(attempt, reason="planted")

    assert victim.read_text(encoding="utf-8") == "untouched"
    assert record_path.is_symlink()


# ---------------------------------------------------------------------------
# (b) Boundary reds against the runner -- one per attack, red by NotImplementedError today
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "token",
    [";", "|", "&", "&&", "||", "$(", "`", ">", "<", "\n"],
    ids=[
        "semicolon",
        "pipe",
        "ampersand",
        "double-ampersand",
        "double-pipe",
        "dollar-paren",
        "backtick",
        "redirect-out",
        "redirect-in",
        "newline",
    ],
)
def test_runner_refuses_shell_token_in_literal_argument(
    world: World, spawn_spy: list[SpawnCall], token: str
) -> None:
    """MC015 at runtime: arguments are literal. An argument carrying a shell operator or
    substitution (spec: ``;`` ``|`` ``&`` ``&&`` ``||`` ``$(`` backtick ``>`` ``<`` newline)
    is refused before anything is spawned and the refusal names the token -- even when a
    consent object for that very argv exists, because argv validation precedes the consent
    lookup."""
    world.script("check.sh", "touch ran.marker")
    argv = ("scripts/check.sh", f"literal{token}touch pwned")
    consent = world.forged_consent(Phase.CHECK, argv, digest=_sha256(world.scripts / "check.sh"))

    with pytest.raises(ShellTokenError) as excinfo:
        world.run(Phase.CHECK, argv, consent=consent)

    message = str(excinfo.value)
    assert token in message or repr(token) in message, (
        f"refusal does not name the token {token!r}: {message}"
    )
    assert spawn_spy == []
    assert not world.ran_marker()


def test_runner_refuses_argv_longer_than_64_arguments(
    world: World, spawn_spy: list[SpawnCall]
) -> None:
    """Spec (drill-runner): an argv of more than 64 arguments is refused before any process
    starts. 64 is the last accepted length; 65 is refused."""
    world.script("check.sh", "touch ran.marker")
    argv = ("scripts/check.sh", *(f"arg{i}" for i in range(64)))
    consent = world.forged_consent(Phase.CHECK, argv, digest=_sha256(world.scripts / "check.sh"))

    with pytest.raises(ArgvLengthError):
        world.run(Phase.CHECK, argv, consent=consent)

    assert spawn_spy == []
    assert not world.ran_marker()


@pytest.mark.parametrize(
    ("argument", "expected"),
    [
        ("literal\x00touch pwned", ShellTokenError),
        ("x" * (2 * 1024 * 1024), ArgvLengthError),
        ("${HOME}/pwned", ShellTokenError),
    ],
    ids=["nul-byte", "two-mebibyte-argument", "dollar-brace"],
)
def test_runner_refuses_nul_oversize_and_dollar_brace_arguments(
    world: World, spawn_spy: list[SpawnCall], argument: str, expected: type[Exception]
) -> None:
    """M1 Q1: a NUL byte and a multi-megabyte argument passed the 64-item check and failed
    *after* consent with CPython's own exception; ``${`` is cheap defence in depth. All
    three are refused by ``validate_argv`` -- before consent, before spawn -- with the
    runner's own refusal type, never an uncaught ``ValueError``."""
    world.script("check.sh", "touch ran.marker")
    argv = ("scripts/check.sh", argument)
    consent = world.forged_consent(Phase.CHECK, argv, digest=_sha256(world.scripts / "check.sh"))

    with pytest.raises(expected):
        world.run(Phase.CHECK, argv, consent=consent)

    assert spawn_spy == []
    assert not world.ran_marker()


def test_spawn_failure_is_an_error_result_not_an_exception(world: World) -> None:
    """M1 Q1: every spawn failure becomes ``PhaseResult(ERROR)`` naming the reason. A
    consented script that the kernel refuses to execute (no shebang, not a binary ->
    ``ENOEXEC``) is a phase that could not run, not a traceback."""
    script = world.scripts / "check.sh"
    script.write_bytes(b"this is not a script and has no interpreter line\n")
    script.chmod(0o755)
    argv = ("scripts/check.sh",)

    result = world.run(Phase.CHECK, argv)

    assert result.exit_class is ExitClass.ERROR
    assert result.timed_out is False
    assert "could not be started" in result.message
    assert "Exec format error" in result.message or "errno" in result.message.lower()


def _symlinked_script(world: World, tmp_path: Path) -> str:
    world.script("real.sh", "touch ran.marker")
    (world.scripts / "check.sh").symlink_to(world.scripts / "real.sh")
    return "scripts/check.sh"


def _hardlinked_script(world: World, tmp_path: Path) -> str:
    outside = tmp_path / "outside"
    outside.mkdir()
    twin = outside / "twin.sh"
    twin.write_text("#!/bin/sh\ntouch ran.marker\n", encoding="utf-8")
    twin.chmod(0o755)
    os.link(twin, world.scripts / "check.sh")
    assert (world.scripts / "check.sh").stat().st_nlink == 2
    return "scripts/check.sh"


def _escaping_script(world: World, tmp_path: Path) -> str:
    outside = tmp_path / "outside"
    outside.mkdir()
    escape = outside / "escape.sh"
    escape.write_text("#!/bin/sh\ntouch ran.marker\n", encoding="utf-8")
    escape.chmod(0o755)
    return "scripts/../../outside/escape.sh"


def _absolute_script(world: World, tmp_path: Path) -> str:
    outside = tmp_path / "outside"
    outside.mkdir()
    absolute = outside / "absolute.sh"
    absolute.write_text("#!/bin/sh\ntouch ran.marker\n", encoding="utf-8")
    absolute.chmod(0o755)
    return str(absolute)


def _directory_not_script(world: World, tmp_path: Path) -> str:
    (world.scripts / "check.sh").mkdir()
    return "scripts/check.sh"


def _regular_file_outside_scripts(world: World, tmp_path: Path) -> str:
    """MC013 at runtime (wave-1 ruling 1): a regular file *inside* the snapshot but outside
    ``scripts/`` -- ``decks/helper.sh`` -- is not a phase executable."""
    decks = world.attempt.snapshot_dir / "decks"
    decks.mkdir()
    helper = decks / "helper.sh"
    helper.write_text("#!/bin/sh\ntouch ran.marker\n", encoding="utf-8")
    helper.chmod(0o755)
    return "decks/helper.sh"


def _nested_under_scripts(world: World, tmp_path: Path) -> str:
    """The spec says *directly* under ``scripts/``: a regular file one level down is refused."""
    nested = world.scripts / "sub"
    nested.mkdir()
    script = nested / "check.sh"
    script.write_text("#!/bin/sh\ntouch ran.marker\n", encoding="utf-8")
    script.chmod(0o755)
    return "scripts/sub/check.sh"


@pytest.mark.parametrize(
    "arrange",
    [
        _symlinked_script,
        _hardlinked_script,
        _escaping_script,
        _absolute_script,
        _directory_not_script,
        _regular_file_outside_scripts,
        _nested_under_scripts,
    ],
    ids=[
        "symlink",
        "hardlink",
        "path-escape",
        "absolute-path",
        "directory",
        "regular-file-outside-scripts",
        "nested-under-scripts",
    ],
)
def test_runner_refuses_script_that_is_not_a_regular_file_in_snapshot(
    world: World, spawn_spy: list[SpawnCall], tmp_path: Path, arrange: Any
) -> None:
    """MC013 at runtime: ``argv[0]`` must resolve to a regular file *directly under* the
    snapshot's ``scripts/`` -- not a symlink, not a hardlink to anything, not a path that
    escapes the snapshot, not an absolute path, not a directory, not a regular file elsewhere
    in the snapshot. Refused before spawn, consent or not, and the refusal names the path."""
    script_arg: str = arrange(world, tmp_path)
    candidate = world.attempt.snapshot_dir / script_arg
    digest = _sha256(candidate) if candidate.is_file() else "unavailable"
    argv = (script_arg,)
    consent = world.forged_consent(Phase.CHECK, argv, digest=digest)

    with pytest.raises(ScriptPathError) as excinfo:
        world.run(Phase.CHECK, argv, consent=consent)

    assert script_arg in str(excinfo.value), f"refusal does not name the path: {excinfo.value}"
    assert spawn_spy == []
    assert not world.ran_marker()


def test_runner_builds_environment_from_scratch(
    world: World, spawn_spy: list[SpawnCall], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """§5.5 *Environment*: nothing from the server's process environment reaches a drill.
    A canary set in ``os.environ`` must be invisible to the child; the child sees only the
    documented variables, a minimal ``PATH`` and a scratch ``HOME``/XDG under the attempt
    directory -- never the learner's real ``HOME``.

    The authoritative environment is the ``env=`` mapping the runner hands to ``Popen``
    (``/bin/sh`` adds ``PWD``/``SHLVL``/``_`` of its own, so the script's ``env`` printout
    cannot be the allowlist oracle); the printout proves the canary did not arrive."""
    canary_key = "STUDYLOOP_R1_CANARY"
    canary_value = f"must-not-leak-{uuid.uuid4()}"
    monkeypatch.setenv(canary_key, canary_value)
    learner_home = tmp_path / "learner-home"
    learner_home.mkdir()
    monkeypatch.setenv("HOME", str(learner_home))
    world.script("check.sh", "/usr/bin/env > seen-env.txt")
    argv = ("scripts/check.sh",)

    result = world.run(Phase.CHECK, argv)

    assert result.exit_class is ExitClass.PASSED
    assert len(spawn_spy) == 1
    assert spawn_spy[0].kwargs.get("shell", False) is False
    assert isinstance(spawn_spy[0].args, list)
    child_env = spawn_spy[0].kwargs.get("env")
    assert child_env is not None, "Popen was called without env=, so the child inherited ours"
    assert canary_key not in child_env, f"inherited variable leaked into the child: {canary_key}"
    raw = (world.attempt.attempt_dir / "seen-env.txt").read_text(encoding="utf-8")
    assert canary_value not in raw, "the canary reached the running child"
    attempt_dir = world.attempt.attempt_dir.resolve()
    xdg = {k: v for k, v in child_env.items() if k.startswith("XDG_")}
    extras = set(child_env) - DOCUMENTED_CHILD_VARIABLES - set(xdg)
    assert not extras, f"child saw undocumented variables: {sorted(extras)}"
    for key, value in xdg.items():
        assert Path(value).resolve().is_relative_to(attempt_dir), (
            f"{key}={value} is not a scratch dir under the attempt directory"
        )
    assert child_env["STUDYLOOP_MODULE_ID"] == MODULE_ID
    assert child_env["STUDYLOOP_DRILL_ID"] == EXPECTED_DRILL_ID
    assert child_env["STUDYLOOP_ATTEMPT_ID"] == world.attempt.attempt_id
    assert Path(child_env["STUDYLOOP_ATTEMPT_DIR"]).resolve() == attempt_dir
    assert spawn_spy[0].kwargs.get("cwd") is not None
    assert Path(spawn_spy[0].kwargs["cwd"]).resolve() == attempt_dir, "cwd is not the attempt dir"
    assert "KUBECONFIG" not in child_env, "workdir target must not export KUBECONFIG"
    child_home = Path(child_env["HOME"]).resolve()
    assert child_home != learner_home.resolve()
    assert child_home.is_relative_to(attempt_dir), (
        f"child HOME {child_home} is not a scratch dir under the attempt directory"
    )
    assert child_env["PATH"], "child PATH must be set explicitly, not inherited or empty"
    assert child_env["PATH"] != os.environ["PATH"], "child PATH is the server's PATH, not minimal"


def test_declared_prerequisite_resolves_from_the_learners_path_into_attempt_bin(
    world: World, spawn_spy: list[SpawnCall], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """M1 Q2 PATH ruling: core resolves each declared prerequisite on the *learner's* PATH,
    symlinks exactly those tools into ``<attempt>/bin``, and the child's PATH is
    ``<attempt>/bin:/usr/bin:/bin`` -- kubectl under a Homebrew prefix resolves without
    exposing the rest of the prefix."""
    homebrew_bin = tmp_path / "opt" / "homebrew" / "bin"
    homebrew_bin.mkdir(parents=True)
    fake_kubectl = homebrew_bin / "kubectl"
    fake_kubectl.write_text(
        '#!/bin/sh\necho fake-kubectl "$@" > kubectl.marker\n', encoding="utf-8"
    )
    fake_kubectl.chmod(0o755)
    (homebrew_bin / "brew").write_text("#!/bin/sh\ntouch brew.marker\n", encoding="utf-8")
    (homebrew_bin / "brew").chmod(0o755)
    monkeypatch.setenv("PATH", f"{homebrew_bin}:/usr/bin:/bin")
    world.script("check.sh", "kubectl get pods\nbrew install anything 2>/dev/null || true")
    argv = ("scripts/check.sh",)

    result = world.run(Phase.CHECK, argv, prerequisites=("kubectl",))

    assert result.exit_class is ExitClass.PASSED
    attempt_dir = world.attempt.attempt_dir.resolve()
    env = spawn_spy[0].kwargs["env"]
    assert env["PATH"] == f"{attempt_dir / 'bin'}:/usr/bin:/bin"
    link = attempt_dir / "bin" / "kubectl"
    assert link.is_symlink()
    assert link.resolve() == fake_kubectl.resolve()
    assert (attempt_dir / "kubectl.marker").read_text(encoding="utf-8") == "fake-kubectl get pods\n"
    assert not (attempt_dir / "brew.marker").exists(), "an undeclared tool leaked via PATH"
    assert sorted(p.name for p in (attempt_dir / "bin").iterdir()) == ["kubectl"]


def test_unresolvable_prerequisite_refuses_before_spawn(
    world: World, spawn_spy: list[SpawnCall], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A declared tool that is not on the learner's PATH refuses the phase naming the
    tool; nothing is spawned and the consent is not consumed."""
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    world.script("check.sh", "touch ran.marker")
    argv = ("scripts/check.sh",)
    consent = world.consent(Phase.CHECK, argv)

    with pytest.raises(PrerequisiteError, match="no-such-tool-xyz"):
        world.run(Phase.CHECK, argv, consent=consent, prerequisites=("no-such-tool-xyz",))

    assert spawn_spy == []
    assert not world.ran_marker()
    assert world.run(Phase.CHECK, argv, consent=consent).exit_class is ExitClass.PASSED


def test_runner_refuses_script_changed_after_consent(
    world: World, spawn_spy: list[SpawnCall]
) -> None:
    """§5.5 *Consent*: the script's content digest is shown at consent and re-checked
    immediately before spawn. A script rewritten in that window is refused and never runs."""
    script = world.script("check.sh", "exit 0")
    argv = ("scripts/check.sh",)
    consent = world.consent(Phase.CHECK, argv)  # digest of the content the learner saw

    script.write_text("#!/bin/sh\ntouch swapped.marker\nexit 0\n", encoding="utf-8")

    with pytest.raises(DigestMismatchError):
        world.run(Phase.CHECK, argv, consent=consent)

    assert spawn_spy == []
    assert not world.ran_marker("swapped.marker")


class _RewritingLedger(ConsentLedger):
    """A ledger whose successful ``redeem`` rewrites the script -- the redeem->exec window."""

    def __init__(self, script: Path, body: str) -> None:
        super().__init__()
        self._script = script
        self._body = body

    def redeem(self, consent: Consent, **kwargs: Any) -> None:
        super().redeem(consent, **kwargs)
        self._script.write_text(self._body, encoding="utf-8")


def test_script_rewritten_between_redeem_and_spawn_does_not_run(
    tmp_path: Path, spawn_spy: list[SpawnCall]
) -> None:
    """M1 Q3: the digest is re-verified immediately before ``Popen``; a script swapped in
    the redeem->exec window is refused as an ERROR result naming the mismatch, and the
    swapped content never runs."""
    snapshot = tmp_path / "snapshot"
    (snapshot / "scripts").mkdir(parents=True)
    attempt_dir = tmp_path / "attempt"
    attempt_dir.mkdir()
    attempt = Attempt(
        attempt_id="attempt-race", drill=DRILL, snapshot_dir=snapshot, attempt_dir=attempt_dir
    )
    script = snapshot / "scripts" / "check.sh"
    ledger = _RewritingLedger(script, "#!/bin/sh\ntouch swapped.marker\nexit 0\n")
    world = World(attempt=attempt, ledger=ledger)
    world.script("check.sh", "exit 0")
    argv = ("scripts/check.sh",)
    consent = world.consent(Phase.CHECK, argv)

    result = world.run(Phase.CHECK, argv, consent=consent)

    assert result.exit_class is ExitClass.ERROR
    assert "digest" in result.message
    assert spawn_spy == []
    assert not world.ran_marker("swapped.marker")


def test_runner_refuses_consent_replay(world: World, spawn_spy: list[SpawnCall]) -> None:
    """§5.5 *Consent*: per phase, **per execution**. The same consent presented a second
    time is refused; the script ran exactly once."""
    world.script("check.sh", "echo ran >> runs.log")
    argv = ("scripts/check.sh",)
    consent = world.consent(Phase.CHECK, argv)

    first = world.run(Phase.CHECK, argv, consent=consent)
    assert first.exit_class is ExitClass.PASSED

    with pytest.raises(ConsentReplayedError):
        world.run(Phase.CHECK, argv, consent=consent)

    assert len(spawn_spy) == 1
    runs = (world.attempt.attempt_dir / "runs.log").read_text(encoding="utf-8").splitlines()
    assert runs == ["ran"]


def test_runner_refuses_consent_not_issued_by_the_ledger(
    world: World, spawn_spy: list[SpawnCall]
) -> None:
    """A :class:`Consent` object that passes argv and path validation but was never issued by
    the ledger -- forged in-process, or carried over from another run -- is refused at
    redemption, and nothing is spawned."""
    world.script("check.sh", "touch ran.marker")
    argv = ("scripts/check.sh",)
    forged = world.forged_consent(Phase.CHECK, argv, digest=_sha256(world.scripts / "check.sh"))

    with pytest.raises(ConsentUnknownError):
        world.run(Phase.CHECK, argv, consent=forged)

    assert spawn_spy == []
    assert not world.ran_marker()


@pytest.mark.parametrize(
    ("age_seconds", "expect_run"),
    [(CONSENT_TTL_SECONDS - 1, True), (CONSENT_TTL_SECONDS + 1, False)],
    ids=["one-second-inside-the-ttl", "one-second-past-the-ttl"],
)
def test_cli_consent_expires_ten_minutes_after_it_is_given(
    tmp_path: Path, spawn_spy: list[SpawnCall], age_seconds: int, expect_run: bool
) -> None:
    """Spec (ruling 7): a CLI confirmation is single-use and expires 10 minutes after it is
    given. The ledger's clock is injected so the test does not sleep."""
    now = [1_000.0]
    snapshot = tmp_path / "snapshot"
    (snapshot / "scripts").mkdir(parents=True)
    attempt_dir = tmp_path / "attempt"
    attempt_dir.mkdir()
    attempt = Attempt(
        attempt_id="attempt-ttl", drill=DRILL, snapshot_dir=snapshot, attempt_dir=attempt_dir
    )
    world = World(attempt=attempt, ledger=ConsentLedger(clock=lambda: now[0]))
    world.script("check.sh", "touch ran.marker")
    argv = ("scripts/check.sh",)
    consent = world.consent(Phase.CHECK, argv)

    now[0] += age_seconds

    if expect_run:
        result = world.run(Phase.CHECK, argv, consent=consent)
        assert result.exit_class is ExitClass.PASSED
        assert len(spawn_spy) == 1
        assert world.ran_marker()
    else:
        with pytest.raises(ConsentExpiredError):
            world.run(Phase.CHECK, argv, consent=consent)
        assert spawn_spy == []
        assert not world.ran_marker()


def test_consent_prompt_shows_phase_target_argv_and_digest(world: World) -> None:
    """§5.5 *Consent*: the exact argv and the script's content digest are shown and
    confirmed -- so the text the learner reads names the phase, the target, every argv item
    verbatim and the digest the runner will re-check at spawn."""
    world.script("cleanup.sh", "exit 0")
    argv = ("scripts/cleanup.sh", "--namespace", "drill")
    digest = _sha256(world.scripts / "cleanup.sh")

    text = describe_consent(world.attempt, Phase.CLEANUP, argv, script_digest=digest)

    assert "cleanup" in text
    assert str(world.attempt.attempt_dir) in text, "target (the attempt dir for workdir) missing"
    for item in argv:
        assert item in text, f"argv item {item!r} not shown"
    assert digest in text, "script sha256 not shown"
    assert "--yes" not in text


def test_runner_timeout_is_error_and_child_is_terminated(
    world: World, spawn_spy: list[SpawnCall]
) -> None:
    """§5.5 *Timeouts* / *Exit codes*: ``timeoutSeconds`` applies per phase; on expiry the
    child is terminated and the exit class is *error* -- a timeout is never *failed*."""
    world.script("check.sh", "echo $$ > child.pid\nexec /bin/sleep 30")
    argv = ("scripts/check.sh",)

    started = time.monotonic()
    result = world.run(Phase.CHECK, argv, timeout_seconds=1)
    elapsed = time.monotonic() - started

    assert result.timed_out is True
    assert result.exit_class is ExitClass.ERROR
    assert result.exit_class is not ExitClass.FAILED
    assert result.exit_code is None, "a child the runner stopped has no exit code of its own"
    assert "timed out" in result.message
    assert elapsed < 10, f"runner took {elapsed:.1f}s to honour a 1s timeout"
    pid = int((world.attempt.attempt_dir / "child.pid").read_text(encoding="utf-8").strip())
    assert len(spawn_spy) == 1
    assert spawn_spy[0].process.returncode is not None, "runner did not reap the child"
    assert not _alive(pid), f"child {pid} is still running after the timeout"


def test_runner_kills_a_child_that_ignores_sigterm(
    world: World, spawn_spy: list[SpawnCall]
) -> None:
    """R4: timeout -> terminated **then killed**. A child that traps SIGTERM and keeps
    running must still be gone shortly after the grace period -- the runner never waits
    on a child's goodwill."""
    world.script(
        "check.sh",
        "trap '' TERM\necho $$ > child.pid\n"
        "i=0\nwhile [ $i -lt 300 ]; do /bin/sleep 0.1; i=$((i+1)); done",
    )
    argv = ("scripts/check.sh",)

    started = time.monotonic()
    result = world.run(Phase.CHECK, argv, timeout_seconds=1)
    elapsed = time.monotonic() - started

    assert result.timed_out is True
    assert result.exit_class is ExitClass.ERROR
    assert elapsed < 8, f"runner took {elapsed:.1f}s: SIGTERM was ignored and no SIGKILL followed"
    pid = int((world.attempt.attempt_dir / "child.pid").read_text(encoding="utf-8").strip())
    assert spawn_spy[0].process.returncode is not None, "runner did not reap the child"
    assert not _alive(pid), (
        f"child {pid} survived the timeout: it ignored SIGTERM and was not killed"
    )


FLOOD_SCRIPT = (
    "echo $$ > child.pid\n"
    "i=0\n"
    'while [ $i -lt 20000 ]; do echo "flood line $i"; i=$((i+1)); done\n'
    "exit 0"
)


def test_runner_truncates_output_flood_and_reaps_child(
    world: World, spawn_spy: list[SpawnCall]
) -> None:
    """§5.5 *Output* + spec (rulings 2-3): streamed with caps enforced while the process
    runs. A child that writes far more than the stdout cap gets its output cut at the cap,
    the truncation recorded, the process **terminated** (never left running, nor "handled"
    by waiting for the phase timeout) and the phase classed ``ERROR`` naming the cap -- a
    flooding check is not a trustworthy pass, even though the script would ``exit 0``."""
    world.script("check.sh", FLOOD_SCRIPT)
    argv = ("scripts/check.sh",)
    cap = 4096

    result = world.run(Phase.CHECK, argv, timeout_seconds=10, caps=OutputCaps(stdout_bytes=cap))

    assert result.truncated is True
    assert result.cap_hit == "stdout"
    assert result.exit_class is ExitClass.ERROR, "a flood that exits 0 must not read as passed"
    assert "stdout" in result.message and "cap" in result.message, result.message
    assert len(result.stdout.encode("utf-8")) <= cap, "stdout exceeds the byte cap"
    assert result.stdout.startswith("flood line 0"), "truncation must keep the head of the stream"
    assert result.timed_out is False, "a flood must not be resolved by the phase timeout"
    pid = int((world.attempt.attempt_dir / "child.pid").read_text(encoding="utf-8").strip())
    assert len(spawn_spy) == 1
    assert spawn_spy[0].process.returncode is not None, "runner did not reap the child"
    assert not _alive(pid), f"child {pid} is still running after the output cap"


def test_runner_caps_stderr_separately(world: World, spawn_spy: list[SpawnCall]) -> None:
    """Spec: 16 KiB of stderr is its own cap. A child flooding stderr while stdout stays
    small hits the stderr cap, is terminated, and the phase is an error naming stderr."""
    world.script(
        "check.sh",
        "echo $$ > child.pid\necho small-stdout\n"
        'i=0\nwhile [ $i -lt 20000 ]; do echo "err line $i" >&2; i=$((i+1)); done\nexit 0',
    )
    argv = ("scripts/check.sh",)

    result = world.run(
        Phase.CHECK,
        argv,
        timeout_seconds=10,
        caps=OutputCaps(stdout_bytes=64 * 1024, stderr_bytes=2048),
    )

    assert result.truncated is True
    assert result.cap_hit == "stderr"
    assert result.exit_class is ExitClass.ERROR
    assert len(result.stderr.encode("utf-8")) <= 2048
    assert result.stderr.startswith("err line 0")
    assert result.timed_out is False
    pid = int((world.attempt.attempt_dir / "child.pid").read_text(encoding="utf-8").strip())
    assert not _alive(pid)


def test_runner_caps_total_lines(world: World, spawn_spy: list[SpawnCall]) -> None:
    """Spec: 2,000 lines in total across both streams. Short lines never reach a byte cap,
    so the line cap is what stops them; the phase is an error naming the line cap."""
    world.script("check.sh", FLOOD_SCRIPT)
    argv = ("scripts/check.sh",)

    result = world.run(Phase.CHECK, argv, timeout_seconds=10, caps=OutputCaps(lines=100))

    assert result.truncated is True
    assert result.cap_hit == "lines"
    assert result.exit_class is ExitClass.ERROR
    assert "line" in result.message
    assert result.stdout.count("\n") <= 100
    assert result.timed_out is False
    pid = int((world.attempt.attempt_dir / "child.pid").read_text(encoding="utf-8").strip())
    assert not _alive(pid)


def test_default_caps_are_the_specs_values() -> None:
    """Rulings 2: 64 KiB stdout, 16 KiB stderr, 2,000 lines -- values, not an open knob."""
    assert (DEFAULT_CAPS.stdout_bytes, DEFAULT_CAPS.stderr_bytes, DEFAULT_CAPS.lines) == (
        64 * 1024,
        16 * 1024,
        2_000,
    )


def test_runner_redacts_secrets_before_returning_output(world: World) -> None:
    """§5.5 *Output*: redacted before persistence or delivery, by the existing secret
    detector (``agent_session_tools.scrubber``). A token the script prints on either stream
    never appears in the result; the detector's placeholder does."""
    token = "ghp_" + "a1b2c3d4" * 4 + "e5f6"  # 36 chars after the prefix: the GitHub PAT shape
    assert len(token) == 40
    world.script("check.sh", f"echo 'token is {token}'\necho 'stderr {token}' >&2\nexit 0")
    argv = ("scripts/check.sh",)

    result = world.run(Phase.CHECK, argv)

    assert result.exit_class is ExitClass.PASSED
    assert token not in result.stdout, "the secret reached the result's stdout unredacted"
    assert token not in result.stderr, "the secret reached the result's stderr unredacted"
    assert token not in result.output
    assert "[GITHUB_PAT-001]" in result.stdout
    assert "[GITHUB_PAT-001]" in result.stderr


def test_secret_straddling_the_stdout_cap_leaves_no_fragment(world: World) -> None:
    """M1 Q5: the cap used to cut the stream first and redact the truncated bytes, so a
    token sitting across the boundary half-survived (``ghp_`` + 16 of its 36 chars is no
    longer a GitHub PAT to the detector). The runner now streams past the cap, redacts the
    whole captured buffer, then cuts to the cap: zero bytes of the secret survive."""
    cap = 4096
    token = "ghp_" + "a1b2c3d4" * 4 + "e5f6"
    # The token starts 20 bytes before the cap and crosses it; the space before it is the
    # word boundary the detector's ``\\bghp_`` needs (as in any real ``token=ghp_...`` line).
    filler = "f" * (cap - 21) + " "
    world.script("check.sh", f"printf '%s' '{filler}'\nprintf '%s\\n' '{token}'\nexit 0")
    argv = ("scripts/check.sh",)

    result = world.run(Phase.CHECK, argv, caps=OutputCaps(stdout_bytes=cap))

    assert result.truncated is True
    assert result.cap_hit == "stdout"
    assert len(result.stdout.encode("utf-8")) <= cap
    assert "ghp_" not in result.stdout, "a fragment of the secret survived the cut"
    assert token[4:20] not in result.stdout
    assert token not in result.output


@pytest.mark.parametrize(
    ("phase", "code", "expected"),
    [
        (Phase.CHECK, 0, ExitClass.PASSED),
        (Phase.CHECK, 1, ExitClass.FAILED),
        (Phase.CHECK, 2, ExitClass.ERROR),
        (Phase.CHECK, 7, ExitClass.ERROR),
        (Phase.SETUP, 0, ExitClass.PASSED),
        (Phase.SETUP, 1, ExitClass.ERROR),
        (Phase.CLEANUP, 0, ExitClass.PASSED),
        (Phase.CLEANUP, 1, ExitClass.ERROR),
        (Phase.CLEANUP, 3, ExitClass.ERROR),
    ],
    ids=[
        "check-0-passed",
        "check-1-failed",
        "check-2-error",
        "check-7-error",
        "setup-0-passed",
        "setup-1-error",
        "cleanup-0-passed",
        "cleanup-1-error",
        "cleanup-3-error",
    ],
)
def test_runner_maps_exit_codes_to_exit_classes(
    world: World, phase: Phase, code: int, expected: ExitClass
) -> None:
    """§5.5 *Exit codes* + spec (ruling 4): ``check`` ``0`` = passed, ``1`` = failed (task
    not complete), ``>= 2`` = error; ``setup`` and ``cleanup`` any non-zero = error, logged
    and surfaced (the message names the phase and the code) -- a failed cleanup still
    closes the attempt, which the CLI test proves."""
    world.script(f"{phase}.sh", f"exit {code}")
    argv = (f"scripts/{phase}.sh",)

    result = world.run(phase, argv)

    assert result.exit_class is expected
    assert result.exit_code == code
    assert result.timed_out is False
    assert result.truncated is False
    assert phase.value in result.message
    if expected is not ExitClass.PASSED:
        assert str(code) in result.message, "a non-zero exit must be surfaced with its code"


@pytest.mark.parametrize("phase", [Phase.SETUP, Phase.CLEANUP], ids=["setup", "cleanup"])
def test_runner_requires_fresh_consent_per_phase(
    world: World, spawn_spy: list[SpawnCall], phase: Phase
) -> None:
    """§5.5 *Consent*: ``setup`` and ``cleanup`` each need a fresh consent every time they
    run. A ``check`` consent for the very same script does not cover them; a consent
    issued for the phase runs once and cannot be reused."""
    world.script("same.sh", "echo ran >> runs.log")
    argv = ("scripts/same.sh",)
    check_consent = world.consent(Phase.CHECK, argv)

    with pytest.raises(ConsentMismatchError):
        world.run(phase, argv, consent=check_consent)
    assert spawn_spy == []
    assert not world.ran_marker("runs.log")

    fresh = world.consent(phase, argv)
    result = world.run(phase, argv, consent=fresh)
    assert result.exit_class is ExitClass.PASSED

    with pytest.raises(ConsentReplayedError):
        world.run(phase, argv, consent=fresh)
    assert len(spawn_spy) == 1
    runs = (world.attempt.attempt_dir / "runs.log").read_text(encoding="utf-8").splitlines()
    assert runs == ["ran"]
