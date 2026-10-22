"""`session-maint fix-perms`: tighten pre-existing copies of the record to 0600.

Plan 4, lane L, D#2. Snapshots, maintenance backups and vector sidecars are
created owner-only since 92186d77 / R-19c, but copies made before that keep
the 0644 the umask gave them. This opt-in sweep chmods the files the config
names -- and nothing else -- and reports what it did.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest
from typer.testing import CliRunner

from agent_session_tools import maintenance
from agent_session_tools.maintenance import _fix_perms, app

runner = CliRunner()


def _mode(path: Path) -> int:
    return stat.S_IMODE(os.lstat(path).st_mode)


def _write(path: Path, mode: int) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x")
    os.chmod(path, mode)
    assert _mode(path) == mode
    return path


@pytest.fixture
def tree(tmp_path: Path) -> dict[str, object]:
    """A configured tree with 0644 copies inside it and decoys outside."""
    cfg = {
        "database": {
            "path": str(tmp_path / "db" / "sessions.db"),
            "backup_dir": str(tmp_path / "backups"),
            "full_db_path": str(tmp_path / "full" / "sessions_full.db"),
            "snapshot_dir": str(tmp_path / "snapshots"),
        },
        # The app callback configures logging from the config (CLI tests).
        "logging": {"path": str(tmp_path / "log" / "sessions.log"), "level": "INFO"},
    }
    targets = [
        _write(
            tmp_path / "snapshots" / "sessions_full_snapshot_20260101_000000.db", 0o644
        ),
        _write(
            tmp_path / "snapshots" / "sessions_full_snapshot_20260102_000000.db", 0o664
        ),
        _write(tmp_path / "backups" / "sessions_backup_20260101_000000.db", 0o644),
        # `vacuum --db <full>` backs the full DB up under its own stem.
        _write(tmp_path / "backups" / "sessions_full_backup_20260101_000000.db", 0o644),
        _write(tmp_path / "db" / "sessions.vec.db", 0o644),
        _write(tmp_path / "db" / "sessions.vec.db-wal", 0o644),
    ]
    already = _write(tmp_path / "full" / "sessions_full.vec.db", 0o600)
    decoys = [
        # Outside every configured directory, even with a matching name.
        _write(
            tmp_path / "elsewhere" / "sessions_full_snapshot_20260103_000000.db", 0o644
        ),
        # Inside a configured directory, but not a copy of the record.
        _write(tmp_path / "snapshots" / "notes.txt", 0o644),
        _write(tmp_path / "snapshots" / "other_snapshot_20260101_000000.db", 0o644),
        _write(
            tmp_path / "backups" / "sessions_full_snapshot_20260101_000000.db", 0o644
        ),
        # The record itself is not this command's business.
        _write(tmp_path / "db" / "sessions.db", 0o644),
    ]
    # A symlink inside the snapshot dir pointing at a file outside it: a
    # chmod through it would touch a file outside the configured dirs.
    pointed_at = _write(tmp_path / "elsewhere" / "pointed_at.db", 0o644)
    link = tmp_path / "snapshots" / "sessions_full_snapshot_20260104_000000.db"
    link.symlink_to(pointed_at)
    return {
        "cfg": cfg,
        "targets": targets,
        "already": already,
        "decoys": decoys,
        "link": link,
        "pointed_at": pointed_at,
    }


class TestFixPerms:
    def test_a_file_that_cannot_be_tightened_is_reported_and_the_sweep_continues(
        self, tree, capsys, monkeypatch
    ):
        """One unwritable copy (another user's file, a read-only volume) must not
        abort the sweep: the other copies are still tightened, the failure is named,
        and the exit code says the sweep was not clean (council pass 4, kimi-k3)."""
        import os

        victim = tree["targets"][0]
        real_chmod = os.chmod

        def flaky_chmod(path, mode, *args, **kwargs):
            if Path(path) == victim:
                raise PermissionError(13, "Operation not permitted", str(path))
            return real_chmod(path, mode, *args, **kwargs)

        monkeypatch.setattr(os, "chmod", flaky_chmod)

        assert _fix_perms(tree["cfg"]) == 1

        assert _mode(victim) == 0o644
        for path in tree["targets"][1:]:
            assert _mode(path) == 0o600, path
        out = capsys.readouterr().out
        assert str(victim) in out and "Operation not permitted" in out
        assert "Tightened 5 file(s) to 0600" in out
        assert "1 could not be changed" in out

    def test_tightens_only_the_configured_copies_and_reports_counts(self, tree, capsys):
        assert _fix_perms(tree["cfg"]) == 0

        for path in tree["targets"]:
            assert _mode(path) == 0o600, path
        assert _mode(tree["already"]) == 0o600
        for path in tree["decoys"]:
            assert _mode(path) == 0o644, path
        assert _mode(tree["pointed_at"]) == 0o644
        out = capsys.readouterr().out
        assert "Tightened 6 file(s) to 0600" in out
        assert "1 already 0600" in out
        assert "skipped 1 symlink" in out
        assert str(tree["link"]) in out

    def test_dry_run_changes_nothing_and_says_what_it_would_do(self, tree, capsys):
        assert _fix_perms(tree["cfg"], dry_run=True) == 0

        for path in tree["targets"]:
            assert _mode(path) != 0o600, path
        out = capsys.readouterr().out
        assert "Would tighten 6 file(s) to 0600" in out
        for path in tree["targets"]:
            assert str(path) in out

    def test_a_second_run_finds_nothing_to_do(self, tree, capsys):
        assert _fix_perms(tree["cfg"]) == 0
        capsys.readouterr()
        assert _fix_perms(tree["cfg"]) == 0
        out = capsys.readouterr().out
        assert "Tightened 0 file(s) to 0600" in out
        assert "7 already 0600" in out

    def test_without_a_full_db_only_the_hot_tier_is_swept(self, tmp_path, capsys):
        cfg = {
            "database": {
                "path": str(tmp_path / "sessions.db"),
                "backup_dir": str(tmp_path / "backups"),
                "full_db_path": "",
                "snapshot_dir": "",
            }
        }
        backup = _write(
            tmp_path / "backups" / "sessions_backup_20260101_000000.db", 0o644
        )
        sidecar = _write(tmp_path / "sessions.vec.db", 0o644)
        stray = _write(tmp_path / "backups" / "x_snapshot_20260101_000000.db", 0o644)

        assert _fix_perms(cfg) == 0

        assert _mode(backup) == 0o600
        assert _mode(sidecar) == 0o600
        assert _mode(stray) == 0o644
        out = capsys.readouterr().out
        assert "Tightened 2 file(s) to 0600" in out
        assert "full_db_path is not configured" in out

    def test_missing_directories_are_reported_not_created(self, tmp_path, capsys):
        cfg = {
            "database": {
                "path": str(tmp_path / "db" / "sessions.db"),
                "backup_dir": str(tmp_path / "no-backups"),
                "full_db_path": str(tmp_path / "full" / "f.db"),
                "snapshot_dir": str(tmp_path / "no-snapshots"),
            }
        }
        assert _fix_perms(cfg) == 0
        assert not (tmp_path / "no-backups").exists()
        assert not (tmp_path / "no-snapshots").exists()
        assert "Tightened 0 file(s) to 0600" in capsys.readouterr().out


class TestCli:
    def test_fix_perms_is_a_command_that_reaches_the_sweep(self, tree, monkeypatch):
        monkeypatch.setattr(maintenance, "_config", tree["cfg"])
        result = runner.invoke(app, ["fix-perms"])
        assert result.exit_code == 0, result.output
        assert "Tightened 6 file(s) to 0600" in result.output
        for path in tree["targets"]:
            assert _mode(path) == 0o600, path

    def test_dry_run_flag(self, tree, monkeypatch):
        monkeypatch.setattr(maintenance, "_config", tree["cfg"])
        result = runner.invoke(app, ["fix-perms", "--dry-run"])
        assert result.exit_code == 0, result.output
        assert "Would tighten 6 file(s) to 0600" in result.output
        for path in tree["targets"]:
            assert _mode(path) != 0o600, path

    def test_help_names_what_it_touches(self):
        result = runner.invoke(app, ["fix-perms", "--help"], terminal_width=200)
        assert result.exit_code == 0
        for word in ("snapshot", "backup", "sidecar", "0600"):
            assert word in result.output
