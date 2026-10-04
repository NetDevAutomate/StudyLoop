"""The core-owned drill runner (proposal §5.5) -- the runtime half of MC013 and MC015.

**What this is, in plain words (M1 council ruling, Q2/Q4/Q7).** v1 is *consent-gated
execution with hygiene*, not a sandbox. A phase script runs **with the learner's own
privileges**, on the learner's machine, as an ordinary child process: it can read and write
anything the learner can. What the runner guarantees is narrower and stated exactly:

- the script is the one the learner saw and confirmed (argv + content digest, re-checked
  immediately before ``Popen``);
- it is spawned as an argv list with ``shell=False`` -- no shell parses anything;
- the ``env=`` mapping handed to ``Popen`` is built from an empty dict (nothing is *copied*
  from ``os.environ``; the only learner-PATH influence is the prerequisite resolution
  below). This keeps the learner's secrets-in-environment out of the child; it does **not**
  stop a script from reading ``~/.aws`` or anything else the learner can read;
- output is capped, redacted and kept as transient evidence;
- on timeout or a cap, the child's **process group** is terminated then killed. A
  descendant that re-parents itself with ``setsid()`` leaves that group and **survives**
  the kill; portable Python cannot close that gap.

OS-level sandboxing (``sandbox-exec`` / ``bwrap``) is a tracked follow-up change, not a
v1 property. The per-phase consent prompt (:func:`studyloop.modules.consent.describe_consent`)
says the same thing to the learner.

Spec: ``openspec/changes/module-contract-v1/specs/drill-runner/spec.md`` and the M1
arbitration (``council/2026-10-04-m1-arbitration.md``). What :func:`run_phase` guarantees,
each row a contract item:

- *Invocation*: ``argv[0]`` is one executable **directly under** ``scripts/`` in the
  snapshot plus literal arguments, spawned as a **list** with ``shell=False``. A shell
  operator or substitution in any argument -- ``;`` ``|`` ``&`` ``&&`` ``||`` ``$(`` ``${``
  backtick ``>`` ``<`` newline -- or a NUL byte is a :class:`ShellTokenError` **before**
  spawn (MC015); more than :data:`ARGV_MAX` arguments or :data:`ARGV_MAX_BYTES` of encoded
  argv in total is an :class:`ArgvLengthError`. Validation is pure and cheap so the CLI
  runs it *before* the consent prompt: a command the runner would refuse is never offered.
- *MC013 at runtime*: the resolved script must be a regular file directly inside the
  snapshot's ``scripts/`` -- no symlink, no hardlink (``st_nlink > 1``), no device/FIFO/
  directory, no ``..`` escape, no absolute path, no regular file elsewhere in the snapshot
  (``decks/helper.sh``) -- else :class:`ScriptPathError` naming the path.
- *Environment*: the ``env=`` mapping is built from an empty dict: a scratch ``HOME`` and
  the XDG base directories under ``Attempt.attempt_dir``, ``PATH`` = ``<attempt>/bin`` +
  :data:`BASE_PATH`, ``STUDYLOOP_MODULE_ID``, ``STUDYLOOP_DRILL_ID``,
  ``STUDYLOOP_ATTEMPT_ID``, ``STUDYLOOP_ATTEMPT_DIR`` and ``KUBECONFIG`` only when the
  target is a kubeconfig context.
- *Prerequisites (M1 PATH ruling)*: "modules declare, core executes" -- each tool name in
  ``prerequisites`` is resolved with ``shutil.which`` on the **learner's** ``PATH`` (from
  ``os.environ``) and symlinked into ``<attempt>/bin/<name>``; the child's PATH holds that
  directory and :data:`BASE_PATH` only, so ``kubectl`` under a Homebrew prefix resolves
  without exposing the rest of the prefix. An unresolvable tool is a
  :class:`PrerequisiteError` naming it, raised before consent is consumed.
- *Consent*: the script digest is recomputed and ``ConsentLedger.redeem`` is called
  before the spawn, and the digest is re-verified **again immediately before**
  ``subprocess.Popen`` (M1 Q3): a script rewritten in the redeem->exec window is an
  ``ERROR`` result and never runs. The residual same-UID race is inside the v1 model.
- *Exit classes*: ``check`` ``0`` passed, ``1`` failed (task not complete), anything else
  error; ``setup``/``cleanup`` any non-zero is an error that is surfaced with its code
  (ruling 4 -- the CLI still closes the attempt after a failed cleanup). A spawn the kernel
  refuses (``ENOEXEC``, ``EACCES``, ...) is an ``ERROR`` result with exit code
  :data:`EXIT_CODE_NOT_STARTED` naming the reason -- never an uncaught exception.
- *Timeouts*: ``timeout_seconds`` applies to this phase alone; on expiry the child's
  process group is terminated, then killed after a short grace, and the result is
  ``ExitClass.ERROR`` with ``timed_out=True`` and ``exit_code=None`` (the real return code
  is kept in ``process_returncode`` for the mentor envelope, which needs an int).
- *Output*: stdout and stderr are streamed through :func:`_stream` with the spec's caps
  (:data:`~studyloop.modules.attempt.DEFAULT_CAPS`: 64 KiB stdout, 16 KiB stderr, 2,000
  lines in total) enforced **while the child runs**; a cap hit terminates the child,
  records ``truncated``/``cap_hit`` and classes the phase ``ERROR`` naming the cap
  (ruling 3). Redaction runs on the whole captured buffer **before** the visible cut (M1
  Q5): the runner keeps :data:`REDACTION_GRACE_BYTES` past each byte cap so a secret that
  straddles the cap is seen whole by the existing secret detector
  (``agent_session_tools.scrubber.Scrubber``) and replaced before the text is cut to the
  cap. Nothing downstream -- the CLI, the ``practice_check_events`` row, the mentor hop --
  ever sees an unredacted byte.

Spawning goes through ``subprocess.Popen`` looked up on the module at call time (not a
``from subprocess import Popen``) so that tests can observe the exact spawn arguments by
patching ``subprocess.Popen``.
"""

from __future__ import annotations

import hashlib
import os
import selectors
import shutil
import stat
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

from agent_session_tools.scrubber import Scrubber
from studyloop.modules.attempt import (
    DEFAULT_CAPS,
    Attempt,
    ExitClass,
    OutputCaps,
    Phase,
    PhaseResult,
    RefusalError,
    TargetKind,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from studyloop.modules.consent import Consent, ConsentLedger


class ShellTokenError(RefusalError):
    """A literal argument contained a shell operator, substitution or NUL (MC015 at runtime)."""


class ScriptPathError(RefusalError):
    """``argv[0]`` did not resolve to a regular file inside the snapshot's ``scripts/`` (MC013)."""


class ArgvLengthError(RefusalError):
    """The phase's argv exceeds the cap: 64 arguments or 64 KiB of encoded bytes in total."""


class PrerequisiteError(RefusalError):
    """A tool the module declares as a prerequisite is not on the learner's PATH (M1 Q2)."""


#: The spec's argv cap: more than this many arguments (``argv[0]`` included) is refused.
ARGV_MAX = 64

#: Total encoded bytes of argv the runner accepts (M1 Q1: a multi-megabyte argument used
#: to pass the 64-item check and fail after consent with CPython's own error).
ARGV_MAX_BYTES = 64 * 1024

#: Shell operators and substitutions refused in any argument (spec, ruling 5; M1 adds
#: ``${``). Longest first so the refusal names ``&&`` rather than ``&`` when both match.
SHELL_TOKENS: tuple[str, ...] = (
    "&&",
    "||",
    "$(",
    "${",
    ";",
    "|",
    "&",
    "`",
    ">",
    "<",
    "\n",
    "\r",
)

#: Exit code recorded when the phase never started: the kernel refused the exec, or the
#: pre-spawn digest re-check failed. ``126`` is the POSIX shell convention for "found but
#: cannot execute"; it is in the ``>= 2`` error band of every phase.
EXIT_CODE_NOT_STARTED = 126

#: Bytes kept past each byte cap so redaction sees a cap-straddling secret whole (M1 Q5).
REDACTION_GRACE_BYTES = 8 * 1024

#: The directory under the snapshot that may hold phase executables (§5.1, MC013).
SCRIPTS_DIR = "scripts"

#: The system half of the child's PATH (M1 PATH ruling): the POSIX userland that
#: ``#!/bin/sh`` scripts need and nothing a package manager installed. Declared tools reach
#: the child only through ``<attempt>/bin`` symlinks.
BASE_PATH = "/usr/bin:/bin"

#: Directory under the attempt that holds one symlink per resolved prerequisite.
_ATTEMPT_BIN = "bin"

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
    """MC015 at runtime: refuse shell tokens, NUL bytes and over-long argv **before**
    anything else -- before consent is shown, before any process exists.

    Returns the argv as a tuple of ``str``. Every element is checked, ``argv[0]``
    included -- a script *name* carrying ``;`` is as refused as an argument. A NUL byte is
    refused here with the runner's own error so it never reaches ``Popen``'s ``ValueError``
    after consent (M1 Q1).
    """
    if not argv:
        raise ShellTokenError("a phase needs at least one argument: the scripts/ executable")
    if len(argv) > ARGV_MAX:
        raise ArgvLengthError(
            f"argv has {len(argv)} arguments; the runner accepts at most {ARGV_MAX}"
        )
    items: list[str] = []
    total = 0
    for position, raw in enumerate(argv):
        if not isinstance(raw, str):
            raise ShellTokenError(f"argv[{position}] is not a string: {raw!r}")
        if "\x00" in raw:
            raise ShellTokenError(
                f"argv[{position}] contains a NUL byte; arguments are literal strings (MC015)"
            )
        total += len(raw.encode("utf-8", errors="surrogateescape")) + 1
        if total > ARGV_MAX_BYTES:
            raise ArgvLengthError(
                f"argv exceeds {ARGV_MAX_BYTES} encoded bytes in total at argv[{position}]; "
                "the runner refuses it before consent"
            )
        for token in SHELL_TOKENS:
            if token in raw:
                raise ShellTokenError(
                    f"argv[{position}] contains the shell token {token!r}; arguments are "
                    f"literal and a phase is one scripts/ executable plus literal arguments "
                    f"(MC015): {raw[:200]!r}"
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


def resolve_prerequisites(
    prerequisites: Sequence[str], *, learner_path: str | None = None
) -> dict[str, Path]:
    """M1 PATH ruling: resolve each declared tool on the *learner's* PATH to one canonical
    executable, or refuse the phase naming the tool.

    ``learner_path`` defaults to ``os.environ["PATH"]`` -- the one deliberate read of the
    caller's environment, because that is where the learner installed the tool. The
    returned paths are fully resolved (symlinks followed) so ``<attempt>/bin/<name>`` points
    at the real binary, not at a shim that would be re-resolved under the child's PATH.
    """
    if learner_path is None:
        learner_path = os.environ.get("PATH", "")
    resolved: dict[str, Path] = {}
    for name in prerequisites:
        if not name or "/" in name or name in {".", ".."} or "\x00" in name:
            raise PrerequisiteError(f"prerequisite {name!r} is not a plain tool name")
        found = shutil.which(name, path=learner_path)
        if found is None:
            raise PrerequisiteError(
                f"prerequisite {name!r} is not on your PATH; install it (or fix PATH) and "
                "run the phase again -- nothing was executed"
            )
        resolved[name] = Path(found).resolve()
    return resolved


def build_environment(
    attempt: Attempt, prerequisites: Sequence[str] = (), *, learner_path: str | None = None
) -> dict[str, str]:
    """§5.5 *Environment*: a mapping built from an empty dict; nothing is copied from
    ``os.environ``. (This is hygiene -- the child still runs with the learner's privileges;
    see the module docstring.)

    Creates the scratch ``HOME`` and XDG directories under the attempt directory (mode
    ``0o700``) so the child can write to them, and ``<attempt>/bin`` holding one symlink per
    resolved prerequisite; the child's ``PATH`` is that directory plus :data:`BASE_PATH`.
    """
    tools = resolve_prerequisites(prerequisites, learner_path=learner_path)
    attempt_dir = attempt.attempt_dir.resolve()
    home = attempt_dir / _SCRATCH_HOME
    bin_dir = attempt_dir / _ATTEMPT_BIN
    env: dict[str, str] = {
        "HOME": str(home),
        "PATH": f"{bin_dir}:{BASE_PATH}",
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
    bin_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    for name, target_path in tools.items():
        link = bin_dir / name
        try:
            if link.is_symlink() or link.exists():
                link.unlink()
            link.symlink_to(target_path)
        except OSError as exc:
            raise PrerequisiteError(
                f"could not expose prerequisite {name!r} in the attempt's bin/: {exc.strerror}"
            ) from exc
    if attempt.target is TargetKind.KUBECONFIG_CONTEXT:
        if attempt.kubeconfig is None:
            raise RefusalError(
                "target kind kubeconfig-context but the attempt carries no core-written "
                "kubeconfig; refusing to spawn"
            )
        env["KUBECONFIG"] = str(attempt.kubeconfig)
    return env


def _stop(process: subprocess.Popen[bytes]) -> None:
    """Terminate, then kill, the child's process group; always reap the child.

    The group is the one ``start_new_session=True`` put the child at the head of. A
    descendant that calls ``setsid()`` has left it and is **not** reached (M1 Q4,
    documented residual).
    """
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


@dataclass
class _Captured:
    """What :func:`_stream` collected: raw bytes per stream and why it stopped."""

    stdout: bytearray
    stderr: bytearray
    cap_hit: str | None
    timed_out: bool


def _stream(
    process: subprocess.Popen[bytes], *, caps: OutputCaps, timeout_seconds: float
) -> _Captured:
    """Read both pipes until EOF, the phase timeout or a cap -- whichever comes first.

    Caps are enforced on every chunk, not after the fact: the moment a stream passes its
    byte cap plus :data:`REDACTION_GRACE_BYTES`, or the two streams pass the line cap
    together, reading stops and the caller terminates the child. The grace bytes are kept
    so redaction can see a cap-straddling secret whole; :func:`run_phase` redacts the whole
    buffer and only then cuts the text to the cap (M1 Q5). A buffer that ends past its cap
    but inside the grace (the child stopped there, or hung until the timeout) is still a
    cap hit. The timeout is a deadline measured from the spawn, checked on every wake-up,
    and also bounds the final wait for the exit status once both pipes have closed (a
    child that closes its pipes and lingers is still a timeout).
    """
    assert process.stdout is not None and process.stderr is not None
    captured = _Captured(bytearray(), bytearray(), None, False)
    limits = {"stdout": caps.stdout_bytes, "stderr": caps.stderr_bytes}
    buffers = {"stdout": captured.stdout, "stderr": captured.stderr}
    lines = 0
    deadline = time.monotonic() + timeout_seconds
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ, "stdout")
    selector.register(process.stderr, selectors.EVENT_READ, "stderr")
    try:
        while selector.get_map() and captured.cap_hit is None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                captured.timed_out = True
                break
            for key, _events in selector.select(timeout=min(remaining, 0.25)):
                name: str = key.data
                chunk = os.read(key.fd, 65536)
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                buffer = buffers[name]
                buffer.extend(chunk)
                lines += chunk.count(b"\n")
                if len(buffer) > limits[name] + REDACTION_GRACE_BYTES:
                    del buffer[limits[name] + REDACTION_GRACE_BYTES :]
                    captured.cap_hit = name
                    break
                if lines > caps.lines:
                    # Every excess line arrived in this chunk; keep this buffer's share of
                    # the cap and drop the rest, so the kept text has at most `caps.lines`
                    # newlines across both streams.
                    _cut_after_newlines(buffer, buffer.count(b"\n") - (lines - caps.lines))
                    captured.cap_hit = "lines"
                    break
    finally:
        selector.close()
    if captured.cap_hit is None and not captured.timed_out:
        try:
            process.wait(timeout=max(deadline - time.monotonic(), 0.0))
        except subprocess.TimeoutExpired:
            captured.timed_out = True
    if captured.cap_hit is None:
        for name, buffer in buffers.items():
            if len(buffer) > limits[name]:
                captured.cap_hit = name
                break
    return captured


def _cut_after_newlines(buffer: bytearray, keep: int) -> None:
    """Truncate ``buffer`` just after its ``keep``-th newline (drop everything if ``keep <= 0``)."""
    if keep <= 0:
        del buffer[:]
        return
    position = -1
    for _ in range(keep):
        position = buffer.find(b"\n", position + 1)
        if position == -1:
            return
    del buffer[position + 1 :]


def _classify(
    phase: Phase, exit_code: int | None, *, timed_out: bool, cap_hit: str | None
) -> ExitClass:
    """§5.5 *Exit codes* and the spec's rulings 3-4, as one table."""
    if timed_out or cap_hit is not None:
        return ExitClass.ERROR
    if exit_code == 0:
        return ExitClass.PASSED
    if phase is Phase.CHECK and exit_code == 1:
        return ExitClass.FAILED
    return ExitClass.ERROR


def _cap_label(cap_hit: str, caps: OutputCaps) -> str:
    if cap_hit == "stdout":
        return f"stdout cap ({caps.stdout_bytes} bytes)"
    if cap_hit == "stderr":
        return f"stderr cap ({caps.stderr_bytes} bytes)"
    return f"line cap ({caps.lines} lines in total)"


def _message(
    phase: Phase,
    exit_class: ExitClass,
    exit_code: int | None,
    *,
    timed_out: bool,
    cap_hit: str | None,
    caps: OutputCaps,
    timeout_seconds: int,
) -> str:
    """The one line the learner reads; every ERROR names its cause and the code if any."""
    name = phase.value
    if timed_out:
        return f"{name} timed out after {timeout_seconds}s; process terminated (error)"
    if cap_hit is not None:
        return (
            f"{name} exceeded the {_cap_label(cap_hit, caps)}; process terminated and output "
            "truncated -- a flooding phase is not a trustworthy result (error)"
        )
    if exit_class is ExitClass.PASSED:
        return f"{name} passed (exit 0)"
    if exit_class is ExitClass.FAILED:
        return f"{name} failed: task not complete (exit {exit_code})"
    if phase is Phase.CHECK:
        return f"{name} could not run (exit {exit_code}; error)"
    if phase is Phase.SETUP:
        return f"{name} failed (exit {exit_code}; error) -- attempt not started"
    return f"{name} failed (exit {exit_code}; error) -- the attempt is closed anyway"


def _redact(raw: bytes, scrubber: Scrubber) -> str:
    return scrubber.scrub(raw.decode("utf-8", errors="replace")).text


def _cut_utf8(text: str, limit: int) -> str:
    """The first ``limit`` bytes of ``text`` as valid UTF-8 (a split trailing char is dropped)."""
    raw = text.encode("utf-8")
    if len(raw) <= limit:
        return text
    return raw[:limit].decode("utf-8", errors="ignore")


def _not_started(phase: Phase, reason: str) -> PhaseResult:
    """An ``ERROR`` result for a phase whose child never ran (M1 Q1/Q3)."""
    return PhaseResult(
        phase=phase,
        exit_class=ExitClass.ERROR,
        exit_code=EXIT_CODE_NOT_STARTED,
        stdout="",
        stderr="",
        truncated=False,
        timed_out=False,
        duration_seconds=0.0,
        message=f"{phase.value} could not be started: {reason} (error)",
        process_returncode=None,
    )


def run_phase(
    attempt: Attempt,
    phase: Phase,
    argv: Sequence[str],
    *,
    consent: Consent,
    ledger: ConsentLedger,
    timeout_seconds: int,
    caps: OutputCaps = DEFAULT_CAPS,
    prerequisites: Sequence[str] = (),
) -> PhaseResult:
    """Run one phase of ``attempt`` under the §5.5 execution model and classify the result.

    Order of operations is part of the contract: validate argv (MC015) -> resolve and
    validate the script path (MC013) -> resolve prerequisites and build the environment
    from scratch -> recompute the digest -> ``ledger.redeem`` -> **re-verify the digest** ->
    ``subprocess.Popen(list, shell=False, cwd=attempt.attempt_dir, env=...)`` -> stream with
    caps and the phase timeout -> stop the child if either tripped -> classify -> redact ->
    cut. Any :class:`~studyloop.modules.attempt.RefusalError` is raised before the consent
    is consumed; anything that goes wrong after redemption is an ``ERROR`` result, never an
    uncaught exception.
    """
    items = validate_argv(argv)
    script = resolve_script(attempt.snapshot_dir, items[0])
    env = build_environment(attempt, prerequisites)
    spawn_argv: list[str] = [str(script), *items[1:]]

    # Re-hash immediately before redemption and hand the fresh digest to the ledger: a
    # script rewritten after consent was shown is refused here, before any process exists.
    digest = script_digest(script)
    ledger.redeem(
        consent,
        attempt=attempt,
        phase=phase,
        argv=items,
        script_digest=digest,
    )

    # M1 Q3: the redeem->exec window. Read the bytes once more right before the spawn; a
    # mismatch is a phase that could not run. (The remaining window is the kernel's own
    # open-and-exec, inside the v1 same-UID threat model.)
    final_digest = script_digest(script)
    if final_digest != consent.script_digest:
        return _not_started(
            phase,
            f"script digest changed between consent and spawn (consented "
            f"{consent.script_digest}, now {final_digest}); the swapped content did not run",
        )

    started = time.monotonic()
    try:
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
    except OSError as exc:
        return _not_started(
            phase, f"{exc.strerror or exc} (errno {exc.errno}) executing {items[0]!r}"
        )
    except ValueError as exc:
        return _not_started(phase, f"invalid spawn arguments: {exc}")
    stopped_by_runner = False
    try:
        captured = _stream(process, caps=caps, timeout_seconds=timeout_seconds)
        if captured.timed_out or captured.cap_hit is not None:
            stopped_by_runner = process.returncode is None
            _stop(process)
    finally:
        for pipe in (process.stdout, process.stderr):
            if pipe is not None:
                pipe.close()
        if process.returncode is None:
            _stop(process)
    duration = time.monotonic() - started

    exit_code: int | None = None if stopped_by_runner else process.returncode
    exit_class = _classify(phase, exit_code, timed_out=captured.timed_out, cap_hit=captured.cap_hit)
    # Redact the WHOLE captured buffer (cap + grace), then cut to the cap (M1 Q5).
    scrubber = Scrubber()
    stdout = _cut_utf8(_redact(bytes(captured.stdout), scrubber), caps.stdout_bytes)
    stderr = _cut_utf8(_redact(bytes(captured.stderr), scrubber), caps.stderr_bytes)
    return PhaseResult(
        phase=phase,
        exit_class=exit_class,
        exit_code=exit_code,
        stdout=stdout,
        stderr=stderr,
        truncated=captured.cap_hit is not None,
        timed_out=captured.timed_out,
        duration_seconds=duration,
        cap_hit=captured.cap_hit,
        message=_message(
            phase,
            exit_class,
            exit_code,
            timed_out=captured.timed_out,
            cap_hit=captured.cap_hit,
            caps=caps,
            timeout_seconds=timeout_seconds,
        ),
        process_returncode=process.returncode,
    )


def describe_spawn(attempt: Attempt, argv: Sequence[str]) -> Mapping[str, object]:
    """What a consent prompt shows: the exact argv and the script's digest (R3 uses it)."""
    items = validate_argv(argv)
    script = resolve_script(attempt.snapshot_dir, items[0])
    return {"argv": items, "script": str(script), "script_digest": script_digest(script)}
