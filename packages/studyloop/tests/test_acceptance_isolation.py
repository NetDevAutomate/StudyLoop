"""Unit tests for tests/acceptance/isolation.py's guarded sweeper.

Deliberately OUTSIDE tests/acceptance/ and carrying no `acceptance` marker:
these test the MECHANISM (the guard functions), not a live product session,
so they must run under the default `just test` gate, not only under
`STUDYLOOP_ACC=1` -- a regression here (a guard that stops guarding) must be
caught by every CI run, not only an opt-in one.

Path bootstrapping mirrors test_harness_matrix.py's convention for this repo
(sys.path insert, then a plain import) rather than a conftest.py, which risks
the workspace's "two packages both named tests" pluggy registration conflict.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_tests_dir = Path(__file__).parent
if str(_tests_dir) not in sys.path:
    sys.path.insert(0, str(_tests_dir))

from acceptance.isolation import (  # noqa: E402
    UnsafeSweepError,
    assert_safe_to_sweep,
    create_scratch_environment,
    scratch_environment,
    sweep_scratch,
)


class TestScratchCreation:
    def test_creates_home_state_dir_and_seeded_config(self, tmp_path: Path) -> None:
        scratch = create_scratch_environment(tmp_path)
        assert scratch.home.is_dir()
        assert scratch.state_dir.is_dir()
        assert scratch.config_dir.is_dir()
        assert (scratch.config_dir / "config.yaml").exists()

    def test_seeded_config_carries_a_default_context_scope(self, tmp_path: Path) -> None:
        """A scratch is a fresh install, and a fresh install cannot start a session.

        The context-memory scope policy (``agent_session_tools.context.scope``)
        refuses to infer a scope: with no ``memory.default_scope`` and no
        project root, ``studyloop study`` exits 2 ("No context scope
        configured") BEFORE any harness is launched -- found 2026-09-16 by the
        first live harness-evidence run, where every harness failed identically
        at this gate. The seeded config therefore has to carry a scope, or the
        live lane can never reach the harness it is meant to certify.
        """
        import yaml

        from agent_session_tools.context.scope import ScopePolicy

        scratch = create_scratch_environment(tmp_path)
        config = yaml.safe_load((scratch.config_dir / "config.yaml").read_text())
        assert config["memory"]["default_scope"] == "unclassified"
        # The same object the product builds from this file must resolve a
        # scope without consulting a project root, cwd, or an env override.
        policy = ScopePolicy.from_config(config)
        assert policy.default_scope is not None
        assert policy.default_scope.value == "unclassified"

    def test_dedicated_tmux_socket_dir_is_deliberately_outside_scratch_home(
        self, tmp_path: Path
    ) -> None:
        """A shared tmux server started under the developer's REAL
        environment must never be what a live tmux-driven acceptance lane
        attaches to -- each run gets its own socket directory, so no run can
        retain another run's (or the real session's) env.

        Deliberately NOT under `scratch.home`, unlike the rest of the
        scratch tree: `home` is rooted at pytest's `tmp_path`, which can be
        arbitrarily deep, and appending tmux's own `tmux-<uid>/default`
        suffix to a deep path blows past AF_UNIX's 104-byte `sun_path` limit
        (see `test_tmux_socket_path_stays_under_the_unix_socket_limit`
        below) -- so the socket dir lives under a short, unrelated `/tmp`
        root instead."""
        scratch = create_scratch_environment(tmp_path)
        assert not scratch.tmux_socket_dir.is_relative_to(scratch.home)
        assert scratch.tmux_socket_dir.is_relative_to(Path("/tmp"))
        assert scratch.tmux_socket_dir.is_dir()
        assert scratch.env["TMUX_TMPDIR"] == str(scratch.tmux_socket_dir)

    def test_tmux_socket_path_stays_under_the_unix_socket_limit_even_for_a_deep_tmp_path(
        self, tmp_path: Path
    ) -> None:
        """Regression (review finding, B2 fix round 1): a realistic pytest
        `tmp_path` -- `.../pytest-of-<user>/pytest-<n>/<long test id>/` -- is
        already ~80+ chars deep before this module adds anything. Rooting
        the tmux socket dir under such a path and then appending tmux's own
        `tmux-<uid>/default` suffix produced a MEASURED 149-char path, past
        macOS's 104-byte `sun_path` limit, so `tmux new-session` could never
        start a server there at all ("File name too long"), not merely run
        slowly."""
        deep = tmp_path
        for part in ("pytest-of-ataylor", "pytest-999", "test_cli_tmux_lane_complet0"):
            deep = deep / part
        deep.mkdir(parents=True)

        scratch = create_scratch_environment(deep)

        candidate = scratch.tmux_socket_dir / f"tmux-{os.getuid()}" / "default"
        assert len(str(candidate)) < 104, (
            f"{candidate} is {len(str(candidate))} chars -- past AF_UNIX's 104-byte sun_path limit"
        )

    def test_sweep_removes_the_tmux_socket_dir_even_though_it_is_outside_home(
        self, tmp_path: Path
    ) -> None:
        scratch = create_scratch_environment(tmp_path)
        socket_dir = scratch.tmux_socket_dir

        sweep_scratch(scratch)

        assert not socket_dir.exists()

    def test_two_scratch_environments_get_different_tmux_sockets(self, tmp_path: Path) -> None:
        first = create_scratch_environment(tmp_path / "a")
        second = create_scratch_environment(tmp_path / "b")
        assert first.tmux_socket_dir != second.tmux_socket_dir

    def test_sentinel_written_and_recorded(self, tmp_path: Path) -> None:
        scratch = create_scratch_environment(tmp_path)
        assert scratch.sentinel_path.exists()
        assert scratch.sentinel_path.read_text(encoding="utf-8") == scratch.sentinel_token

    def test_env_points_at_scratch(self, tmp_path: Path) -> None:
        scratch = create_scratch_environment(tmp_path)
        assert scratch.env["HOME"] == str(scratch.home)
        assert scratch.env["STUDYLOOP_STATE_DIR"] == str(scratch.state_dir)


class TestSweepGuards:
    """(b) the guarded sweeper never reaches real data."""

    def test_normal_scratch_sweeps_cleanly(self, tmp_path: Path) -> None:
        scratch = create_scratch_environment(tmp_path)
        sweep_scratch(scratch)
        assert not scratch.home.exists()

    def test_rejects_scratch_home_equal_to_real_home(self, tmp_path: Path) -> None:
        fake_real_home = tmp_path / "real-home"
        fake_real_home.mkdir()
        scratch = create_scratch_environment(tmp_path)
        scratch.home = fake_real_home  # simulate a mis-resolved path

        with pytest.raises(UnsafeSweepError):
            assert_safe_to_sweep(scratch, real_home=fake_real_home)
        assert fake_real_home.exists(), "guard must not delete anything on rejection"

    def test_rejects_scratch_home_under_real_home(self, tmp_path: Path) -> None:
        fake_real_home = tmp_path / "real-home"
        fake_real_home.mkdir()
        scratch = create_scratch_environment(fake_real_home)  # scratch nested inside "real"

        with pytest.raises(UnsafeSweepError):
            sweep_scratch(scratch, real_home=fake_real_home)
        assert scratch.home.exists(), "guard must not delete anything on rejection"

    def test_rejects_symlinked_escape(self, tmp_path: Path) -> None:
        """A scratch home that is a SYMLINK back into the real tree must trip too."""
        fake_real_home = tmp_path / "real-home"
        fake_real_home.mkdir()
        canary = fake_real_home / "canary.txt"
        canary.write_text("do not touch", encoding="utf-8")

        scratch_root = tmp_path / "scratch-root"
        scratch_root.mkdir()
        scratch = create_scratch_environment(scratch_root)
        # Replace the scratch home with a symlink escaping to the real tree.
        import shutil

        shutil.rmtree(scratch.home)
        scratch.home.symlink_to(fake_real_home)

        with pytest.raises(UnsafeSweepError):
            sweep_scratch(scratch, real_home=fake_real_home)
        assert canary.exists(), "symlinked escape must never reach the real tree"

    def test_refuses_to_sweep_when_sentinel_missing(self, tmp_path: Path) -> None:
        scratch = create_scratch_environment(tmp_path)
        scratch.sentinel_path.unlink()

        with pytest.raises(UnsafeSweepError):
            sweep_scratch(scratch)
        assert scratch.home.exists(), "missing sentinel must refuse the sweep, not proceed"

    def test_refuses_to_sweep_when_sentinel_mismatched(self, tmp_path: Path) -> None:
        scratch = create_scratch_environment(tmp_path)
        scratch.sentinel_path.write_text("tampered", encoding="utf-8")

        with pytest.raises(UnsafeSweepError):
            sweep_scratch(scratch)
        assert scratch.home.exists()


class TestTmuxDescendantStopper:
    """(D-12) the tmux server bound to this run's socket must be killed
    BEFORE the sweeper ever touches the filesystem -- register_descendant_stopper
    exists precisely for this, and this is its first real caller."""

    def test_sweep_kills_the_scratch_tmux_server_first(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls_log = tmp_path / "tmux-calls.log"
        fake_bin_dir = tmp_path / "fake-bin"
        fake_bin_dir.mkdir()
        fake_tmux = fake_bin_dir / "tmux"
        fake_tmux.write_text(
            f'#!/bin/sh\necho "$@ TMUX_TMPDIR=$TMUX_TMPDIR" >> "{calls_log}"\nexit 0\n',
            encoding="utf-8",
        )
        fake_tmux.chmod(0o755)
        monkeypatch.setenv("PATH", f"{fake_bin_dir}:{os.environ['PATH']}")

        scratch_root = tmp_path / "scratch-root"
        scratch_root.mkdir()
        scratch = create_scratch_environment(scratch_root)
        sweep_scratch(scratch)

        logged = calls_log.read_text(encoding="utf-8")
        assert "kill-server" in logged
        assert f"TMUX_TMPDIR={scratch.tmux_socket_dir}" in logged


class TestScratchEnvironmentContextManager:
    def test_swept_even_when_the_body_raises(self, tmp_path: Path) -> None:
        captured_home = None

        class BoomError(RuntimeError):
            pass

        with pytest.raises(BoomError), scratch_environment(tmp_path) as scratch:
            captured_home = scratch.home
            assert captured_home.exists()
            raise BoomError("test body failed")

        assert captured_home is not None
        assert not captured_home.exists(), "scratch must be swept even after a failing test body"

    def test_escape_canary_stays_clean_across_a_full_lifecycle(self, tmp_path: Path) -> None:
        """Plant a canary in a fake real home; a full create+sweep must never touch it."""
        fake_real_home = tmp_path / "real-home"
        fake_real_home.mkdir()
        canary = fake_real_home / "canary.txt"
        canary.write_text("untouched", encoding="utf-8")

        scratch_root = tmp_path / "scratch-root"
        scratch_root.mkdir()
        scratch = create_scratch_environment(scratch_root)
        sweep_scratch(scratch, real_home=fake_real_home)

        assert canary.read_text(encoding="utf-8") == "untouched"
        assert not scratch.home.exists()


@pytest.mark.skipif(not shutil.which("tmux"), reason="tmux not installed")
class TestScratchTmuxSocketDirIsUsable:
    """The positive control the path-length regression test above cannot
    provide by itself: proves a real `tmux` server can actually bind and
    accept a session under the scratch socket dir, not merely that its path
    is short enough in principle."""

    def test_a_real_tmux_session_starts_under_the_scratch_socket_dir(self, tmp_path: Path) -> None:
        scratch = create_scratch_environment(tmp_path)
        session_name = f"sl-acc-socket-smoke-{os.getpid()}"
        env = {**os.environ, "TMUX_TMPDIR": str(scratch.tmux_socket_dir)}
        try:
            created = subprocess.run(
                ["tmux", "new-session", "-d", "-s", session_name, "sleep", "30"],
                env=env,
                capture_output=True,
                text=True,
                timeout=10,
            )
            assert created.returncode == 0, (
                f"tmux new-session failed under the scratch socket dir: {created.stderr}"
            )

            found = subprocess.run(
                ["tmux", "has-session", "-t", session_name],
                env=env,
                capture_output=True,
                text=True,
                timeout=10,
            )
            assert found.returncode == 0, "session started under the scratch socket must be found"
        finally:
            subprocess.run(
                ["tmux", "kill-server"],
                env=env,
                capture_output=True,
                timeout=10,
                check=False,
            )
            sweep_scratch(scratch)
