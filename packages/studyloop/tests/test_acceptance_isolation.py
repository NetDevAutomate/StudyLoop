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

    def test_dedicated_tmux_socket_dir_is_under_scratch_home(self, tmp_path: Path) -> None:
        """A shared tmux server started under the developer's REAL
        environment must never be what a live tmux-driven acceptance lane
        attaches to -- each run gets its own socket directory under its own
        scratch tree, so no run can retain another run's (or the real
        session's) env."""
        scratch = create_scratch_environment(tmp_path)
        assert scratch.tmux_socket_dir.is_relative_to(scratch.home)
        assert scratch.tmux_socket_dir.is_dir()
        assert scratch.env["TMUX_TMPDIR"] == str(scratch.tmux_socket_dir)

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
