"""The core-owned drill runner (proposal §5.5) -- the runtime half of MC013 and MC015.

Spec: ``openspec/changes/module-contract-v1/specs/drill-runner/spec.md``. What
:func:`run_phase` guarantees, each row a contract item (§5.5):

- *Invocation*: ``argv[0]`` is one executable **directly under** ``scripts/`` in the
  snapshot plus literal arguments, spawned as a **list** with ``shell=False``. A shell
  operator or substitution in any argument -- ``;`` ``|`` ``&`` ``&&`` ``||`` ``$(``
  backtick ``>`` ``<`` newline -- is a :class:`ShellTokenError` **before** spawn (MC015);
  more than :data:`ARGV_MAX` arguments is an :class:`ArgvLengthError`.
- *MC013 at runtime*: the resolved script must be a regular file directly inside the
  snapshot's ``scripts/`` -- no symlink, no hardlink (``st_nlink > 1``), no device/FIFO/
  directory, no ``..`` escape, no absolute path, no regular file elsewhere in the snapshot
  (``decks/helper.sh``) -- else :class:`ScriptPathError` naming the path.
- *Environment*: built from scratch, never inherited: a scratch ``HOME`` and the XDG base
  directories under ``Attempt.attempt_dir``, a minimal ``PATH`` (:data:`MINIMAL_PATH`),
  ``STUDYLOOP_MODULE_ID``, ``STUDYLOOP_DRILL_ID``, ``STUDYLOOP_ATTEMPT_ID``,
  ``STUDYLOOP_ATTEMPT_DIR`` and ``KUBECONFIG`` only when the target is a kubeconfig
  context. Nothing from ``os.environ`` is copied.
- *Consent*: the script digest is recomputed and ``ConsentLedger.redeem`` is called
  **immediately before** ``subprocess.Popen`` -- never earlier (R3 owns the ledger).
- *Timeouts*: ``timeout_seconds`` applies to this phase alone; on expiry the child is
  terminated and the result is ``ExitClass.ERROR`` with ``timed_out=True``.
- *Output*: stdout+stderr streamed with caps (R4 owns the caps, the exit-class table and
  redaction; R2 captures and classifies ``0`` as passed, anything else as error).

Spawning goes through ``subprocess.Popen`` looked up on the module at call time (not a
``from subprocess import Popen``) so that tests can observe the exact spawn arguments by
patching ``subprocess.Popen``.
"""

from __future__ import annotations

import hashlib
import os
import stat
import subprocess
import time
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

from studyloop.modules.attempt import (
    Attempt,
    ExitClass,
    Phase,
    PhaseResult,
    RefusalError,
    TargetKind,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from studyloop.modules.consent import Consent, ConsentLedger


class ShellTokenError(RefusalError):
    """A literal argument contained a shell operator/substitution (MC015 at runtime)."""


class ScriptPathError(RefusalError):
    """``argv[0]`` did not resolve to a regular file inside the snapshot's ``scripts/`` (MC013)."""


class ArgvLengthError(RefusalError):
    """The phase's argv exceeds the spec's cap of 64 arguments (drill-runner spec)."""


#: The spec's argv cap: more than this many arguments (``argv[0]`` included) is refused.
ARGV_MAX = 64

#: Shell operators and substitutions refused in any argument (spec, ruling 5). Longest
#: first so the refusal names ``&&`` rather than ``&`` when both would match.
SHELL_TOKENS: tuple[str, ...] = ("&&", "||", "$(", ";", "|", "&", "`", ">", "<", "\n", "\r")

#: The directory under the snapshot that may hold phase executables (§5.1, MC013).
SCRIPTS_DIR = "scripts"

#: "A minimal ``PATH``" (§5.5). The proposal names no contents; this is the smallest set
#: that lets ``#!/bin/sh`` scripts find the POSIX userland and a Homebrew/Linux-installed
#: ``kubectl``. Reported as a contract gap by lane R; change here, not per call.
MINIMAL_PATH = "/usr/local/bin:/usr/bin:/bin"

#: Scratch directories created under the attempt directory for the child's ``HOME``/XDG.
_SCRATCH_HOME = "home"
_XDG_DIRS: tuple[tuple[str, str], ...] = (
    ("XDG_CONFIG_HOME", ".config"),
    ("XDG_CACHE_HOME", ".cache"),
    ("XDG_DATA_HOME", ".local/share"),
    ("XDG_STATE_HOME", ".local/state"),
    ("XDG_RUNTIME_DIR", ".run"),
)

#: Grace period between SIGTERM and SIGKILL when the runner has to stop a child.
_TERMINATE_GRACE_SECONDS = 2.0


def validate_argv(argv: Sequence[str]) -> tuple[str, ...]:
    """MC015 at runtime: refuse shell tokens and over-long argv **before** anything else.

    Returns the argv as a tuple of ``str``. Every element is checked, ``argv[0]``
    included -- a script *name* carrying ``;`` is as refused as an argument.
    """
    if not argv:
        raise ShellTokenError("a phase needs at least one argument: the scripts/ executable")
    if len(argv) > ARGV_MAX:
        raise ArgvLengthError(
            f"argv has {len(argv)} arguments; the runner accepts at most {ARGV_MAX}"
        )
    items: list[str] = []
    for position, raw in enumerate(argv):
        if not isinstance(raw, str):
            raise ShellTokenError(f"argv[{position}] is not a string: {raw!r}")
        for token in SHELL_TOKENS:
            if token in raw:
                raise ShellTokenError(
                    f"argv[{position}] contains the shell token {token!r}; arguments are "
                    f"literal and a phase is one scripts/ executable plus literal arguments "
                    f"(MC015): {raw!r}"
                )
        items.append(raw)
    return tuple(items)


def _refuse(script_arg: str, reason: str) -> ScriptPathError:
    return ScriptPathError(
        f"{script_arg!r} is not a regular file directly under the snapshot's "
        f"{SCRIPTS_DIR}/ ({reason}); refusing to spawn (MC013 at runtime)"
    )


def resolve_script(snapshot_dir: Path, script_arg: str) -> Path:
    """MC013 at runtime: ``argv[0]`` must be ``scripts/<name>`` naming a regular file.

    Checks, in order, without following symlinks: the argument is a relative POSIX path of
    exactly two components whose first is ``scripts`` and whose second is a plain name (no
    ``.``/``..``); the snapshot's ``scripts`` entry is a real directory (not a symlink);
    the file's own ``lstat`` says regular file (so a symlink is refused), ``st_nlink == 1``
    (so a hardlink to anything is refused), and it is executable. Finally the resolved real
    path must still live directly under the resolved ``scripts/`` directory.
    """
    if not script_arg:
        raise _refuse(script_arg, "empty path")
    pure = PurePosixPath(script_arg)
    if pure.is_absolute() or script_arg.startswith(("/", "~")):
        raise _refuse(script_arg, "absolute or home-relative path")
    parts = pure.parts
    if len(parts) != 2 or parts[0] != SCRIPTS_DIR:
        raise _refuse(script_arg, f"path must be exactly {SCRIPTS_DIR}/<name>")
    name = parts[1]
    if name in {".", ".."} or "/" in name or "\\" in name or not name:
        raise _refuse(script_arg, "invalid script name")

    scripts_dir = snapshot_dir / SCRIPTS_DIR
    try:
        dir_st = os.lstat(scripts_dir)
    except OSError as exc:
        raise _refuse(script_arg, f"{SCRIPTS_DIR}/ is missing: {exc.strerror}") from exc
    if not stat.S_ISDIR(dir_st.st_mode):
        raise _refuse(script_arg, f"{SCRIPTS_DIR}/ is not a real directory")

    candidate = scripts_dir / name
    try:
        st = os.lstat(candidate)
    except OSError as exc:
        raise _refuse(script_arg, f"does not exist: {exc.strerror}") from exc
    if stat.S_ISLNK(st.st_mode):
        raise _refuse(script_arg, "symlink")
    if not stat.S_ISREG(st.st_mode):
        raise _refuse(script_arg, "not a regular file")
    if st.st_nlink != 1:
        raise _refuse(script_arg, f"hardlinked (st_nlink={st.st_nlink})")
    if not os.access(candidate, os.X_OK):
        raise _refuse(script_arg, "not executable")

    resolved = candidate.resolve(strict=True)
    scripts_resolved = scripts_dir.resolve(strict=True)
    if resolved.parent != scripts_resolved:
        raise _refuse(script_arg, "resolves outside the snapshot's scripts/")
    return resolved


def script_digest(path: Path) -> str:
    """Hex SHA-256 of the script's bytes -- what consent shows and what spawn re-checks."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_environment(attempt: Attempt) -> dict[str, str]:
    """§5.5 *Environment*: a mapping built from scratch; nothing from ``os.environ``.

    Creates the scratch ``HOME`` and XDG directories under the attempt directory (mode
    ``0o700``) so the child can write to them.
    """
    attempt_dir = attempt.attempt_dir.resolve()
    home = attempt_dir / _SCRATCH_HOME
    env: dict[str, str] = {
        "HOME": str(home),
        "PATH": MINIMAL_PATH,
        "STUDYLOOP_MODULE_ID": attempt.drill.module_id,
        "STUDYLOOP_DRILL_ID": attempt.drill.drill_id,
        "STUDYLOOP_ATTEMPT_ID": attempt.attempt_id,
        "STUDYLOOP_ATTEMPT_DIR": str(attempt_dir),
    }
    home.mkdir(parents=True, exist_ok=True, mode=0o700)
    for key, relative in _XDG_DIRS:
        target = home / relative
        target.mkdir(parents=True, exist_ok=True, mode=0o700)
        env[key] = str(target)
    if attempt.target is TargetKind.KUBECONFIG_CONTEXT:
        if attempt.kubeconfig is None:
            raise RefusalError(
                "target kind kubeconfig-context but the attempt carries no core-written "
                "kubeconfig; refusing to spawn"
            )
        env["KUBECONFIG"] = str(attempt.kubeconfig)
    return env


def _stop(process: subprocess.Popen[bytes]) -> None:
    """Terminate, then kill, the child's whole process group; always reap it."""
    if process.returncode is not None:
        return
    try:
        os.killpg(process.pid, 15)  # SIGTERM to the session the child leads
    except (ProcessLookupError, PermissionError):
        process.terminate()
    try:
        process.wait(timeout=_TERMINATE_GRACE_SECONDS)
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(process.pid, 9)  # SIGKILL
    except (ProcessLookupError, PermissionError):
        process.kill()
    process.wait()


def _classify(phase: Phase, exit_code: int | None) -> ExitClass:
    """R2 interim table: ``0`` passed, anything else error. R4 installs §5.5's full table."""
    if exit_code == 0:
        return ExitClass.PASSED
    return ExitClass.ERROR


def run_phase(
    attempt: Attempt,
    phase: Phase,
    argv: Sequence[str],
    *,
    consent: Consent,
    ledger: ConsentLedger,
    timeout_seconds: int,
    output_byte_cap: int,
) -> PhaseResult:
    """Run one phase of ``attempt`` under the §5.5 execution model and classify the result.

    Order of operations is part of the contract: validate argv (MC015) -> resolve and
    validate the script path (MC013) -> recompute the digest -> ``ledger.redeem`` ->
    build the environment from scratch -> ``subprocess.Popen(list, shell=False, cwd=
    attempt.attempt_dir, env=...)`` -> capture with the phase timeout -> classify. Any
    :class:`~studyloop.modules.attempt.RefusalError` is raised before the spawn step.
    """
    items = validate_argv(argv)
    script = resolve_script(attempt.snapshot_dir, items[0])
    env = build_environment(attempt)
    spawn_argv: list[str] = [str(script), *items[1:]]

    # Re-hash immediately before spawn and hand the fresh digest to the ledger: a script
    # rewritten after consent was shown is refused here, before any process exists.
    digest = script_digest(script)
    ledger.redeem(
        consent,
        attempt=attempt,
        phase=phase,
        argv=items,
        script_digest=digest,
    )

    started = time.monotonic()
    process = subprocess.Popen(
        spawn_argv,
        shell=False,
        cwd=str(attempt.attempt_dir),
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
        close_fds=True,
    )
    timed_out = False
    try:
        stdout_bytes, stderr_bytes = process.communicate(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        timed_out = True
        _stop(process)
        stdout_bytes, stderr_bytes = b"", b""
    duration = time.monotonic() - started

    exit_code: int | None = None if timed_out else process.returncode
    stdout = _bounded_text(stdout_bytes, output_byte_cap)
    stderr = _bounded_text(stderr_bytes, output_byte_cap)
    return PhaseResult(
        phase=phase,
        exit_class=ExitClass.ERROR if timed_out else _classify(phase, exit_code),
        exit_code=exit_code,
        output=stdout + stderr,
        truncated=False,
        timed_out=timed_out,
        duration_seconds=duration,
    )


def _bounded_text(raw: bytes, cap: int) -> str:
    return raw[:cap].decode("utf-8", errors="replace")


def describe_spawn(attempt: Attempt, argv: Sequence[str]) -> Mapping[str, object]:
    """What a consent prompt shows: the exact argv and the script's digest (R3 uses it)."""
    items = validate_argv(argv)
    script = resolve_script(attempt.snapshot_dir, items[0])
    return {"argv": items, "script": str(script), "script_digest": script_digest(script)}
