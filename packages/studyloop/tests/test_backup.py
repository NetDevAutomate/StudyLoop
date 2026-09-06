"""Tests for studyloop backup and restore commands."""

from __future__ import annotations

import sqlite3
from contextlib import closing

import pytest
from click.testing import CliRunner

from studyloop.cli import cli


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def mock_env(tmp_path, monkeypatch):
    """Set up isolated config dir with fake databases and config."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()

    # Create fake assets
    db = config_dir / "sessions.db"
    db.write_bytes(b"fake-sessions-db-content")
    review = config_dir / "review.db"
    review.write_bytes(b"fake-review-db-content")
    config = config_dir / "config.yaml"
    config.write_text("obsidian_base: ~/Obsidian\n")

    # Patch the module-level paths
    monkeypatch.setattr("studyloop.cli._backup.CONFIG_DIR", config_dir)
    monkeypatch.setattr("studyloop.cli._backup.DEFAULT_DB", db)
    monkeypatch.setenv("STUDYLOOP_CONFIG", str(config))

    return config_dir


class TestBackup:
    def test_creates_timestamped_backup(self, runner, mock_env):
        result = runner.invoke(cli, ["backup"])
        assert result.exit_code == 0
        assert "Backup saved" in result.output

        backups = list((mock_env / "backups").iterdir())
        assert len(backups) == 1
        assert backups[0].name.startswith("backup_")

        # All three files backed up
        files = {f.name for f in backups[0].iterdir()}
        assert files == {"sessions.db", "review.db", "config.yaml"}

    def test_backup_with_tag(self, runner, mock_env):
        result = runner.invoke(cli, ["backup", "--tag", "pre-upgrade"])
        assert result.exit_code == 0

        backups = list((mock_env / "backups").iterdir())
        assert any("pre-upgrade" in d.name for d in backups)

    def test_backup_preserves_content(self, runner, mock_env):
        runner.invoke(cli, ["backup"])

        backups = list((mock_env / "backups").iterdir())
        backed_up_db = backups[0] / "sessions.db"
        assert backed_up_db.read_bytes() == b"fake-sessions-db-content"

    def test_backup_nothing_to_back_up(self, runner, tmp_path, monkeypatch):
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()
        monkeypatch.setattr("studyloop.cli._backup.CONFIG_DIR", empty_dir)
        monkeypatch.setattr("studyloop.cli._backup.DEFAULT_DB", empty_dir / "nope.db")
        monkeypatch.setenv("STUDYLOOP_CONFIG", str(empty_dir / "nope.yaml"))

        result = runner.invoke(cli, ["backup"])
        assert result.exit_code == 0
        assert "Nothing to back up" in result.output


class TestRestore:
    def test_list_backups(self, runner, mock_env):
        # Create a backup first
        runner.invoke(cli, ["backup"])

        result = runner.invoke(cli, ["restore"])
        assert result.exit_code == 0
        assert "Available backups" in result.output
        assert "sessions.db" in result.output

    def test_restore_dry_run(self, runner, mock_env):
        runner.invoke(cli, ["backup"])
        backups = list((mock_env / "backups").iterdir())
        name = backups[0].name

        result = runner.invoke(cli, ["restore", name])
        assert result.exit_code == 0
        assert "Dry run" in result.output

    def test_restore_with_confirm(self, runner, mock_env):
        runner.invoke(cli, ["backup"])
        backups = list((mock_env / "backups").iterdir())
        name = backups[0].name

        # Corrupt the current DB
        (mock_env / "sessions.db").write_bytes(b"corrupted")

        result = runner.invoke(cli, ["restore", name, "--confirm"])
        assert result.exit_code == 0
        assert "Restore complete" in result.output

        # Verify content was restored
        assert (mock_env / "sessions.db").read_bytes() == b"fake-sessions-db-content"

    def test_restore_creates_safety_backup(self, runner, mock_env):
        runner.invoke(cli, ["backup"])
        backups = list((mock_env / "backups").iterdir())
        name = backups[0].name

        runner.invoke(cli, ["restore", name, "--confirm"])

        # Should now have 2 backups: original + pre-restore safety
        all_backups = list((mock_env / "backups").iterdir())
        assert len(all_backups) == 2
        assert any("pre-restore" in d.name for d in all_backups)

    def test_restore_not_found(self, runner, mock_env):
        (mock_env / "backups").mkdir(exist_ok=True)
        # Create a dummy so the "no backups" check passes
        dummy = mock_env / "backups" / "backup_dummy"
        dummy.mkdir()
        (dummy / "x").touch()

        result = runner.invoke(cli, ["restore", "nonexistent"])
        assert result.exit_code == 0
        assert "Backup not found" in result.output

    def test_no_backups_available(self, runner, mock_env):
        result = runner.invoke(cli, ["restore"])
        assert result.exit_code == 0
        assert "No backups found" in result.output


def test_backup_captures_committed_wal_without_closing_writer(runner, mock_env):
    path = mock_env / "sessions.db"
    path.unlink()
    with closing(sqlite3.connect(path)) as writer:
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute("PRAGMA wal_autocheckpoint=0")
        writer.execute("CREATE TABLE example(body TEXT)")
        writer.commit()
        writer.execute("INSERT INTO example VALUES ('committed in WAL')")
        writer.commit()
        result = runner.invoke(cli, ["backup"])
        assert result.exit_code == 0, result.output
        backup = next((mock_env / "backups").iterdir()) / "sessions.db"
        with closing(sqlite3.connect(backup)) as saved:
            assert saved.execute("SELECT body FROM example").fetchone()[0] == "committed in WAL"


def test_modern_restore_refuses_before_any_asset_or_safety_backup_write(runner, mock_env):
    from agent_session_tools.context.records import connect

    path = mock_env / "sessions.db"
    path.unlink()
    with closing(connect(path)) as conn:
        conn.execute("INSERT INTO sessions(id,source) VALUES ('before','codex')")
        conn.commit()
    assert runner.invoke(cli, ["backup"]).exit_code == 0
    saved = next((mock_env / "backups").iterdir())
    with closing(connect(path)) as conn:
        conn.execute("INSERT INTO context_tombstones VALUES ('before','deletion','now')")
        conn.commit()
    config = mock_env / "config.yaml"
    config.write_text("current_setting: keep\n")
    result = runner.invoke(cli, ["restore", saved.name, "--confirm"])
    assert result.exit_code != 0
    assert "Managed restore is required" in result.output
    assert config.read_text() == "current_setting: keep\n"
    assert len(list((mock_env / "backups").iterdir())) == 1
    with closing(connect(path)) as conn:
        assert conn.execute("SELECT 1 FROM context_tombstones WHERE session_id='before'").fetchone()


def test_restore_rejects_outside_directory_before_writes(runner, mock_env, tmp_path):
    assert runner.invoke(cli, ["backup"]).exit_code == 0
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "sessions.db").write_bytes(b"unrelated")
    result = runner.invoke(cli, ["restore", str(outside), "--confirm"])
    assert result.exit_code != 0
    assert "listed backup directory" in result.output
    assert (mock_env / "sessions.db").read_bytes() == b"fake-sessions-db-content"
