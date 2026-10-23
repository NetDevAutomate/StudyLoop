"""Directories that hold copies of the 0600 record are created owner-only.

Plan 5, lane Q, larger #2 item 5 (lane 4's found-not-fixed #5). Every copy of
the session record -- maintenance backups, snapshots, the full tier, vector
sidecars -- is created 0600 since F-AST-14 / R-19c, but the directories that
hold them were created with ``Path.mkdir`` under the process umask: 0755 under
the common 022, so the listing (file names carry the database stem and the
backup timestamps) was world-readable and a later copy created by any other
tool there would start wide. ``get_backup_dir``, ``ensure_config_dir`` and
``tiering.ensure_leaf_dir`` now create a missing directory 0700. A directory
that already exists is left as it is: the learner may have chosen a shared
volume deliberately, so only ``session-maint fix-perms`` -- an explicit,
opt-in sweep -- tightens a pre-existing directory, and only one this user owns.
"""

from __future__ import annotations

import os
import stat
from collections.abc import Iterator
from pathlib import Path

import pytest

from agent_session_tools import config_loader, maintenance
from agent_session_tools.config_loader import ensure_config_dir, get_backup_dir
from agent_session_tools.maintenance import _fix_perms
from agent_session_tools.tiering import ensure_leaf_dir


@pytest.fixture
def umask_022() -> Iterator[None]:
    previous = os.umask(0o022)
    try:
        yield
    finally:
        os.umask(previous)


def _mode(path: Path) -> int:
    return stat.S_IMODE(os.lstat(path).st_mode)


def _set_mode(path: Path, mode: int) -> None:
    os.chmod(path, mode)
    assert _mode(path) == mode


def _wide_dir(path: Path, mode: int = 0o755) -> Path:
    """A directory left at the mode the umask would have given it (0755 under 022)."""
    path.mkdir(parents=True, exist_ok=True)
    _set_mode(path, mode)
    return path


class TestCreatedOwnerOnly:
    def test_get_backup_dir_creates_a_missing_directory_0700(self, tmp_path, umask_022):
        target = tmp_path / "external" / "Backups"
        cfg = {"database": {"backup_dir": str(target)}}

        assert get_backup_dir(cfg) == target

        assert target.is_dir()
        assert _mode(target) == 0o700, f"{_mode(target):04o}"

    def test_get_backup_dir_leaves_an_existing_directory_alone(
        self, tmp_path, umask_022
    ):
        """Not this function's call: a learner may have made it shared on purpose."""
        target = tmp_path / "Backups"
        _wide_dir(target)
        cfg = {"database": {"backup_dir": str(target)}}

        assert get_backup_dir(cfg) == target

        assert _mode(target) == 0o755

    def test_ensure_leaf_dir_creates_the_leaf_0700(self, tmp_path, umask_022):
        """Snapshot dir, full-tier dir and compact destination all come through here."""
        target = tmp_path / "DB"

        ensure_leaf_dir(target)

        assert target.is_dir()
        assert _mode(target) == 0o700, f"{_mode(target):04o}"

    def test_ensure_leaf_dir_leaves_an_existing_directory_alone(
        self, tmp_path, umask_022
    ):
        target = tmp_path / "DB"
        _wide_dir(target)

        ensure_leaf_dir(target)

        assert _mode(target) == 0o755

    def test_ensure_config_dir_creates_the_default_backup_dir_0700(
        self, tmp_path, umask_022, monkeypatch
    ):
        config_path = tmp_path / "profile" / "config.yaml"
        monkeypatch.setenv("STUDYLOOP_CONFIG", str(config_path))
        default_backups = tmp_path / "profile" / "backups"
        monkeypatch.setitem(
            config_loader.DEFAULT_CONFIG["database"], "backup_dir", str(default_backups)
        )

        ensure_config_dir()

        assert default_backups.is_dir()
        assert _mode(default_backups) == 0o700, f"{_mode(default_backups):04o}"


class TestFixPermsTightensTheDirectories:
    @pytest.fixture
    def cfg(self, tmp_path: Path) -> dict:
        backups = tmp_path / "backups"
        snapshots = tmp_path / "snapshots"
        for directory in (backups, snapshots):
            _wide_dir(directory)
        return {
            "database": {
                "path": str(tmp_path / "db" / "sessions.db"),
                "backup_dir": str(backups),
                "full_db_path": str(tmp_path / "full" / "sessions_full.db"),
                "snapshot_dir": str(snapshots),
            },
            "logging": {
                "path": str(tmp_path / "log" / "sessions.log"),
                "level": "INFO",
            },
        }

    def test_fix_perms_tightens_the_backup_and_snapshot_directories(
        self, cfg, capsys, umask_022
    ):
        assert _fix_perms(cfg) == 0

        assert _mode(Path(cfg["database"]["backup_dir"])) == 0o700
        assert _mode(Path(cfg["database"]["snapshot_dir"])) == 0o700
        out = capsys.readouterr().out
        assert f"directory {cfg['database']['backup_dir']}: 0755 -> 0700" in out
        assert f"directory {cfg['database']['snapshot_dir']}: 0755 -> 0700" in out
        assert "2 directory(ies)" in out or "2 directories" in out

    def test_dry_run_reports_the_directories_and_changes_nothing(
        self, cfg, capsys, umask_022
    ):
        assert _fix_perms(cfg, dry_run=True) == 0

        assert _mode(Path(cfg["database"]["backup_dir"])) == 0o755
        assert _mode(Path(cfg["database"]["snapshot_dir"])) == 0o755
        out = capsys.readouterr().out
        assert f"directory {cfg['database']['backup_dir']}: 0755 -> 0700" in out

    def test_a_directory_owned_by_someone_else_is_named_and_left_alone(
        self, cfg, capsys, umask_022, monkeypatch
    ):
        """Only this user's directories are ours to tighten (a shared volume
        root, a directory root created for us) -- say so instead of trying."""
        monkeypatch.setattr(os, "geteuid", lambda: os.getuid() + 1)

        assert _fix_perms(cfg) == 0

        assert _mode(Path(cfg["database"]["backup_dir"])) == 0o755
        out = capsys.readouterr().out
        assert "not owned by this user" in out
        assert cfg["database"]["backup_dir"] in out

    def test_an_already_owner_only_directory_is_counted_not_changed(
        self, cfg, capsys, umask_022
    ):
        os.chmod(cfg["database"]["backup_dir"], 0o700)
        os.chmod(cfg["database"]["snapshot_dir"], 0o700)

        assert _fix_perms(cfg) == 0

        out = capsys.readouterr().out
        assert "0755 -> 0700" not in out

    def test_a_symlinked_directory_is_skipped(self, cfg, capsys, umask_022, tmp_path):
        real = tmp_path / "elsewhere"
        _wide_dir(real)
        link = tmp_path / "snapshots-link"
        link.symlink_to(real)
        cfg["database"]["snapshot_dir"] = str(link)

        assert _fix_perms(cfg) == 0

        assert _mode(real) == 0o755
        assert "symlink" in capsys.readouterr().out

    def test_a_directory_that_cannot_be_changed_is_reported_and_exit_is_1(
        self, cfg, capsys, umask_022, monkeypatch
    ):
        real_chmod = os.chmod
        victim = Path(cfg["database"]["backup_dir"])

        def flaky_chmod(path, mode, *args, **kwargs):
            if Path(path) == victim:
                raise PermissionError(1, "Operation not permitted", str(path))
            return real_chmod(path, mode, *args, **kwargs)

        monkeypatch.setattr(os, "chmod", flaky_chmod)

        assert _fix_perms(cfg) == 1

        assert _mode(victim) == 0o755
        assert _mode(Path(cfg["database"]["snapshot_dir"])) == 0o700
        out = capsys.readouterr().out
        assert "Operation not permitted" in out

    def test_without_a_full_db_only_the_backup_dir_is_considered(
        self, tmp_path, capsys, umask_022
    ):
        backups = tmp_path / "backups"
        _wide_dir(backups)
        stray = tmp_path / "snapshots"
        _wide_dir(stray)
        cfg = {
            "database": {
                "path": str(tmp_path / "sessions.db"),
                "backup_dir": str(backups),
                "full_db_path": "",
                "snapshot_dir": str(stray),
            }
        }

        assert _fix_perms(cfg) == 0

        assert _mode(backups) == 0o700
        # No full tier: the snapshot dir holds nothing of ours and is not touched.
        assert _mode(stray) == 0o755

    def test_the_existing_file_sweep_is_unchanged(self, cfg, tmp_path, umask_022):
        """The directory rows sit beside the file rows; neither displaces the other."""
        copy = (
            Path(cfg["database"]["backup_dir"]) / "sessions_backup_20260101_000000.db"
        )
        copy.write_bytes(b"x")
        _set_mode(copy, 0o644)

        assert _fix_perms(cfg) == 0

        assert _mode(copy) == 0o600
        assert _mode(copy.parent) == 0o700
        assert maintenance  # the module under test, imported for its namespace
