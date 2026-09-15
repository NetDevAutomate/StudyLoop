"""Per-test scratch isolation + guarded sweeper for the acceptance tier.

``settings.py:25`` binds ``CONFIG_DIR = Path.home() / ".config" / "studyloop"``
AT IMPORT TIME (council D-11, verified). An in-process ``HOME`` monkeypatch
after ``studyloop.settings`` has already been imported leaves the real config
dir live — the module-level constant does not move. Acceptance tests must
therefore drive the product through a SUBPROCESS with a sanitized env built
BEFORE that subprocess ever imports studyloop, never by mutating an
already-imported module in this process.

This module owns the scratch-tree lifecycle: a fresh HOME, a
``STUDYLOOP_STATE_DIR`` under it, a seeded config dir, and a sanitized child
env (via :func:`studyloop.session.child_env.build_scratch_child_env`) every
acceptance test hands to the subprocess it drives.

The sweeper (:func:`sweep_scratch`) is guarded, not trusting: it hard-errors
(never silently skips) if the scratch path resolves to, or under, the REAL
home or the real ``~/.config/studyloop`` (council D-11/D-12), and it refuses
to sweep at all if the ownership sentinel planted at creation is missing —
that combination is what stops a symlinked escape or a mis-resolved path from
ever reaching ``shutil.rmtree`` against the learner's real data.
"""

from __future__ import annotations

import functools
import os
import secrets
import shutil
import subprocess
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from studyloop.session.child_env import build_scratch_child_env

if TYPE_CHECKING:
    from collections.abc import Callable

_SENTINEL_NAME = ".studyloop-acceptance-sentinel"

#: macOS's `sockaddr_un.sun_path` holds at most 104 bytes (Linux's is a
#: little more generous at 108, but 104 is the binding constraint on the
#: owner's platform). tmux's actual socket is `<TMUX_TMPDIR>/tmux-<uid>/
#: default` -- verified empirically that a realistic pytest `tmp_path`
#: (`.../pytest-of-ataylor/pytest-999/<long test id>/home/.tmux-acc/tmux-501/
#: default`) produces a 145-149 char path there, well past the limit, and
#: `tmux new-session` fails outright with "error connecting to ... (File
#: name too long)" -- not a hang, not a slow failure, a dead-on-arrival
#: socket. The scratch tmux socket dir must therefore live under a SHORT
#: root, never under the (potentially very deep) scratch HOME.
_UNIX_SOCKET_PATH_LIMIT = 104
_TMUX_SOCKET_TMP_ROOT = "/tmp"
_TMUX_SOCKET_TMP_PREFIX = "sl-acc-"


class UnsafeSweepError(RuntimeError):
    """Raised when a sweep guard trips. Sweeping never proceeds after this."""


class TmuxSocketPathTooLongError(RuntimeError):
    """Raised if a freshly-created scratch tmux socket dir is, somehow,
    still too long for AF_UNIX's `sun_path` -- a defensive check, not an
    expected outcome, since `_TMUX_SOCKET_TMP_ROOT` is chosen to be short."""


@dataclass
class ScratchEnv:
    """One acceptance test's disposable world."""

    home: Path
    state_dir: Path
    config_dir: Path
    tmux_socket_dir: Path
    sentinel_path: Path
    sentinel_token: str
    env: dict[str, str]
    _descendant_stoppers: list[Callable[[], None]] = field(default_factory=list, repr=False)

    def register_descendant_stopper(self, stopper: Callable[[], None]) -> None:
        """Register a callback (kill a tmux server, an MCP child, ...).

        Every registered stopper runs, in registration order, before the
        sweeper ever touches the filesystem — a live descendant holding a
        file open, or writing into the tree mid-sweep, is exactly the kind
        of race the contract (D-12) calls out.
        """
        self._descendant_stoppers.append(stopper)

    def stop_descendants(self) -> None:
        for stopper in self._descendant_stoppers:
            stopper()


def _kill_scratch_tmux_server(socket_dir: Path) -> None:
    """Best-effort: kill any tmux server bound to this scratch run's socket.

    ``TMUX_TMPDIR`` is the standard tmux mechanism for relocating its socket
    directory — set in the child env below, so every tmux invocation a
    descendant makes under this scratch env already lands here without any
    ``-S``/argv change. The common case is "no server was ever started under
    this socket", which tmux reports as a non-zero exit ("no server running
    on ...") — not an error worth raising from a teardown path.
    """
    subprocess.run(
        ["tmux", "kill-server"],
        env={**os.environ, "TMUX_TMPDIR": str(socket_dir)},
        capture_output=True,
        timeout=10,
        check=False,
    )


def _assert_socket_dir_short_enough(socket_dir: Path) -> None:
    """Defensive check: the ACTUAL socket tmux opens is
    ``<socket_dir>/tmux-<uid>/default``, not ``socket_dir`` itself -- verify
    that full path, not just the directory tempfile handed back."""
    candidate = socket_dir / f"tmux-{os.getuid()}" / "default"
    if len(str(candidate)) >= _UNIX_SOCKET_PATH_LIMIT:
        raise TmuxSocketPathTooLongError(
            f"scratch tmux socket path {candidate} is {len(str(candidate))} "
            f"chars, at or past AF_UNIX's {_UNIX_SOCKET_PATH_LIMIT}-byte "
            "sun_path limit -- tmux would fail to start a server here"
        )


def _assert_safe_to_remove_tmux_socket_dir(socket_dir: Path) -> None:
    """Guard the OUT-OF-``home`` sweep step the same way ``assert_safe_to_sweep``
    guards the home tree: refuse (hard error, never skip) unless the
    resolved path is unambiguously one this module created."""
    resolved = socket_dir.resolve()
    tmp_root = Path(_TMUX_SOCKET_TMP_ROOT).resolve()
    if not resolved.is_relative_to(tmp_root) or not resolved.name.startswith(
        _TMUX_SOCKET_TMP_PREFIX
    ):
        raise UnsafeSweepError(
            f"refusing to remove tmux socket dir {socket_dir}: resolved to "
            f"{resolved}, which is not a {_TMUX_SOCKET_TMP_PREFIX!r}-prefixed "
            f"directory directly under {tmp_root}"
        )


def create_scratch_environment(
    tmp_path: Path,
    *,
    extra_env: dict[str, str] | None = None,
) -> ScratchEnv:
    """Build a fresh scratch HOME + state dir + seeded config + sanitized env.

    ``tmp_path`` is expected to be a pytest ``tmp_path``-shaped, per-test
    throwaway directory — this function trusts its caller to already be
    isolated from the real filesystem; it does not itself consult
    ``Path.home()``.
    """
    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)

    state_dir = home / ".local" / "share" / "studyloop"
    state_dir.mkdir(parents=True, exist_ok=True)

    config_dir = home / ".config" / "studyloop"
    config_dir.mkdir(parents=True, exist_ok=True)
    # Seeded, not empty: a real first-run would trip migration/onboarding
    # prompts the acceptance journeys are not testing.
    (config_dir / "config.yaml").write_text("topics: []\n", encoding="utf-8")

    # Dedicated tmux socket directory per run: a shared tmux server started
    # under the developer's REAL environment must never be what a live
    # tmux-driven acceptance lane attaches to. tmux requires its socket
    # directory to be private (mode 0700), same as the real ~/.tmux/ default.
    #
    # Deliberately NOT under `home`: `home` is rooted at the caller's
    # `tmp_path`, which under a real pytest run can already be 80+ chars
    # deep before this function adds anything -- past the point where
    # appending tmux's own `tmux-<uid>/default` suffix fits in AF_UNIX's
    # 104-byte `sun_path` (see `_UNIX_SOCKET_PATH_LIMIT` above). A short,
    # unrelated `/tmp` directory is used instead, and swept explicitly in
    # `sweep_scratch` below since it now sits outside the tree that
    # function's `shutil.rmtree(scratch.home, ...)` call reaches.
    tmux_socket_dir = Path(
        tempfile.mkdtemp(prefix=_TMUX_SOCKET_TMP_PREFIX, dir=_TMUX_SOCKET_TMP_ROOT)
    )
    tmux_socket_dir.chmod(0o700)
    _assert_socket_dir_short_enough(tmux_socket_dir)

    token = secrets.token_hex(16)
    sentinel_path = home / _SENTINEL_NAME
    sentinel_path.write_text(token, encoding="utf-8")

    caller_env = dict(extra_env) if extra_env else None
    env = build_scratch_child_env(home=home, state_dir=state_dir, caller_env=caller_env)
    env["TMUX_TMPDIR"] = str(tmux_socket_dir)

    scratch = ScratchEnv(
        home=home,
        state_dir=state_dir,
        config_dir=config_dir,
        tmux_socket_dir=tmux_socket_dir,
        sentinel_path=sentinel_path,
        sentinel_token=token,
        env=env,
    )
    # First real caller of register_descendant_stopper (isolation.py had the
    # hook but nothing registered with it): a tmux server bound to THIS run's
    # socket must be stopped before the sweeper ever touches the filesystem.
    scratch.register_descendant_stopper(
        functools.partial(_kill_scratch_tmux_server, tmux_socket_dir)
    )
    return scratch


def assert_safe_to_sweep(scratch: ScratchEnv, *, real_home: Path | None = None) -> None:
    """Hard-error (never skip) if sweeping ``scratch`` could touch real data.

    Every check resolves symlinks first (``Path.resolve()``) — a scratch
    home that is ITSELF a symlink pointing back at the real home, or
    somewhere under it, must trip this exactly as a literal path would.
    """
    real_home = (real_home or Path.home()).resolve()
    real_config_dir = real_home / ".config" / "studyloop"

    resolved_home = scratch.home.resolve()

    if resolved_home == real_home:
        raise UnsafeSweepError(
            f"refusing to sweep: scratch home {scratch.home} resolves to the real home {real_home}"
        )
    if resolved_home.is_relative_to(real_home):
        raise UnsafeSweepError(
            f"refusing to sweep: scratch home {scratch.home} resolves to "
            f"{resolved_home}, which is under the real home {real_home}"
        )
    if real_home.is_relative_to(resolved_home):
        raise UnsafeSweepError(
            f"refusing to sweep: the real home {real_home} is under scratch home "
            f"{scratch.home} ({resolved_home}) — sweeping it would reach real data"
        )

    resolved_config = scratch.config_dir.resolve()
    resolved_real_config = real_config_dir.resolve()
    if resolved_config == resolved_real_config:
        raise UnsafeSweepError(
            f"refusing to sweep: scratch config dir {scratch.config_dir} resolves to "
            f"the real config dir {real_config_dir}"
        )
    if resolved_config.is_relative_to(resolved_real_config):
        raise UnsafeSweepError(
            f"refusing to sweep: scratch config dir {scratch.config_dir} resolves "
            f"under the real config dir {real_config_dir}"
        )

    if not scratch.sentinel_path.exists():
        raise UnsafeSweepError(
            f"refusing to sweep: ownership sentinel {scratch.sentinel_path} is "
            "missing — this scratch tree cannot be proven to be the one this "
            "test created"
        )
    if scratch.sentinel_path.read_text(encoding="utf-8") != scratch.sentinel_token:
        raise UnsafeSweepError(
            f"refusing to sweep: ownership sentinel {scratch.sentinel_path} does "
            "not match the token recorded at creation"
        )


def sweep_scratch(scratch: ScratchEnv, *, real_home: Path | None = None) -> None:
    """Stop descendants, run every safety guard, then remove the scratch tree.

    Raises :class:`UnsafeSweepError` and leaves the tree untouched if any
    guard trips — a failed guard is a hard error, never a silent skip
    (council D-12).
    """
    scratch.stop_descendants()
    assert_safe_to_sweep(scratch, real_home=real_home)
    shutil.rmtree(scratch.home, ignore_errors=False)

    # The tmux socket dir lives OUTSIDE `scratch.home` (see
    # `create_scratch_environment`), so the rmtree above never reaches it --
    # sweep it separately, behind its own guard.
    if scratch.tmux_socket_dir.exists():
        _assert_safe_to_remove_tmux_socket_dir(scratch.tmux_socket_dir)
        shutil.rmtree(scratch.tmux_socket_dir, ignore_errors=True)


@contextmanager
def scratch_environment(tmp_path: Path, *, extra_env: dict[str, str] | None = None):
    """Context manager: create on enter, sweep on exit — even on exception.

    A guard failure on exit propagates (it is a hard error, not swallowed);
    the ORIGINAL exception from the ``with`` body, if any, is what a caller
    sees first via normal exception-chaining semantics.
    """
    scratch = create_scratch_environment(tmp_path, extra_env=extra_env)
    try:
        yield scratch
    finally:
        sweep_scratch(scratch)
