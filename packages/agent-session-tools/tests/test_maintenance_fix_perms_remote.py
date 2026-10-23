"""`session-maint fix-perms --remote`: run the printed `ssh … chmod 600` per endpoint.

Plan 5, lane Q, item C. `_seed_remote_db` scps a 0600 snapshot, but an existing
remote file keeps its own mode and a fresh one takes the remote umask (lane L,
plan 4). The local sweep already computes the exact command for each configured
endpoint and prints it; `--remote` runs it, opt-in, one `subprocess.run` per
endpoint path with a list argv and no shell, and reports one result row per
endpoint with a classified reason (ok / unreachable / permission / timeout). A
failed endpoint never aborts the sweep: everything is reported, then the exit
code is non-zero (same shape as 3031bac1 / 285b0ac7). Without `--remote` nothing
is executed. No test here runs a real ssh.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from agent_session_tools import maintenance
from agent_session_tools.maintenance import _fix_perms, app

runner = CliRunner()

# RFC 5737 TEST-NET addresses: never routable, never anyone's host.
ENDPOINTS = {
    "alpha": {
        "username": "learner",
        "ip_address": {"primary_ip": "192.0.2.10"},
        "path": "/srv/study/sessions.db",
        "full_path": "/srv/study/sessions_full.db",
    },
    "beta": {
        "username": "learner",
        "ip_address": {"primary_ip": "198.51.100.7"},
        "path": "/home/learner/My Sessions/sessions.db",
        "full_path": "",
    },
}


@pytest.fixture
def cfg(tmp_path: Path) -> dict:
    return {
        "database": {
            "path": str(tmp_path / "db" / "sessions.db"),
            "backup_dir": str(tmp_path / "backups"),
            "full_db_path": str(tmp_path / "full" / "sessions_full.db"),
            "snapshot_dir": str(tmp_path / "snapshots"),
        },
        "logging": {"path": str(tmp_path / "log" / "sessions.log"), "level": "INFO"},
        # Legacy endpoint form: no hostname lookup, exactly what get_endpoints returns.
        "endpoints": ENDPOINTS,
    }


def _completed(argv, rc=0, err=""):
    return subprocess.CompletedProcess(argv, rc, stdout="", stderr=err)


class _Ssh:
    """Records every argv; answers per remote path from a script."""

    def __init__(self, script):
        self.script = script
        self.calls: list[tuple[list[str], dict]] = []

    def __call__(self, argv, *args, **kwargs):
        self.calls.append((list(argv), kwargs))
        assert not args, "argv must be the only positional argument"
        outcome = self.script.get(argv[-1], ("ok",))
        if outcome[0] == "timeout":
            raise subprocess.TimeoutExpired(argv, kwargs.get("timeout", 0))
        if outcome[0] == "rc":
            return _completed(argv, outcome[1], outcome[2])
        return _completed(argv)


def no_process(*args, **kwargs):
    pytest.fail("fix-perms must not execute anything without --remote")


class TestWithoutRemote:
    def test_nothing_is_executed_and_the_hints_are_still_printed(
        self, cfg, capsys, monkeypatch
    ):
        monkeypatch.setattr(maintenance.subprocess, "run", no_process)

        assert _fix_perms(cfg) == 0

        out = capsys.readouterr().out
        assert "ssh learner@192.0.2.10 chmod 600 /srv/study/sessions.db" in out
        assert "ssh learner@192.0.2.10 chmod 600 /srv/study/sessions_full.db" in out
        assert (
            "ssh learner@198.51.100.7 chmod 600 '/home/learner/My Sessions/sessions.db'"
            in out
        )
        assert "not reached from here" in out


class TestRemote:
    def test_one_argv_per_endpoint_path_with_no_shell(self, cfg, monkeypatch):
        ssh = _Ssh({})
        monkeypatch.setattr(maintenance.subprocess, "run", ssh)

        assert _fix_perms(cfg, remote=True) == 0

        argvs = [argv for argv, _ in ssh.calls]
        assert argvs == [
            [
                "ssh",
                "-o",
                "BatchMode=yes",
                "-o",
                "ConnectTimeout=10",
                "learner@192.0.2.10",
                "chmod",
                "600",
                "/srv/study/sessions.db",
            ],
            [
                "ssh",
                "-o",
                "BatchMode=yes",
                "-o",
                "ConnectTimeout=10",
                "learner@192.0.2.10",
                "chmod",
                "600",
                "/srv/study/sessions_full.db",
            ],
            [
                "ssh",
                "-o",
                "BatchMode=yes",
                "-o",
                "ConnectTimeout=10",
                "learner@198.51.100.7",
                "chmod",
                "600",
                # ssh joins the remote words with spaces for the remote shell,
                # so the path is quoted exactly as the printed hint quotes it.
                "'/home/learner/My Sessions/sessions.db'",
            ],
        ]
        for _, kwargs in ssh.calls:
            assert kwargs.get("shell", False) is False
            assert kwargs.get("timeout") == 30
            assert kwargs.get("capture_output") is True

    def test_every_endpoint_gets_a_row_and_all_ok_exits_zero(
        self, cfg, capsys, monkeypatch
    ):
        monkeypatch.setattr(maintenance.subprocess, "run", _Ssh({}))

        assert _fix_perms(cfg, remote=True) == 0

        out = capsys.readouterr().out
        assert (
            "✅ Remote 'alpha' learner@192.0.2.10:/srv/study/sessions.db -> 0600" in out
        )
        assert (
            "✅ Remote 'alpha' learner@192.0.2.10:/srv/study/sessions_full.db -> 0600"
            in out
        )
        assert (
            "✅ Remote 'beta' learner@198.51.100.7:/home/learner/My Sessions/sessions.db -> 0600"
            in out
        )
        assert "not reached from here" not in out
        assert "3 remote cop" in out

    def test_a_failed_endpoint_is_reported_the_sweep_continues_and_exit_is_1_at_the_end(
        self, cfg, capsys, monkeypatch
    ):
        ssh = _Ssh(
            {
                "/srv/study/sessions.db": (
                    "rc",
                    255,
                    "ssh: connect to host 192.0.2.10 port 22: Connection refused\n",
                ),
            }
        )
        monkeypatch.setattr(maintenance.subprocess, "run", ssh)

        assert _fix_perms(cfg, remote=True) == 1

        # The sweep went on to the second alpha path and to beta after the failure.
        assert [argv[-1] for argv, _ in ssh.calls] == [
            "/srv/study/sessions.db",
            "/srv/study/sessions_full.db",
            "'/home/learner/My Sessions/sessions.db'",
        ]
        out = capsys.readouterr().out
        assert (
            "❌ Remote 'alpha' learner@192.0.2.10:/srv/study/sessions.db: unreachable"
            in out
        )
        assert "Connection refused" in out
        assert (
            "✅ Remote 'alpha' learner@192.0.2.10:/srv/study/sessions_full.db -> 0600"
            in out
        )
        assert (
            "✅ Remote 'beta' learner@198.51.100.7:/home/learner/My Sessions/sessions.db -> 0600"
            in out
        )
        assert "1 remote copy could not be changed" in out

    @pytest.mark.parametrize(
        ("outcome", "reason"),
        [
            (("timeout",), "timeout"),
            (
                ("rc", 255, "learner@192.0.2.10: Permission denied (publickey).\n"),
                "permission",
            ),
            (
                (
                    "rc",
                    255,
                    "ssh: connect to host 192.0.2.10 port 22: Connection timed out\n",
                ),
                "unreachable",
            ),
            (
                ("rc", 255, "ssh: Could not resolve hostname 192.0.2.10\n"),
                "unreachable",
            ),
            (
                (
                    "rc",
                    1,
                    "chmod: changing permissions of '/srv/study/sessions.db': Operation not permitted\n",
                ),
                "permission",
            ),
            (
                (
                    "rc",
                    1,
                    "chmod: cannot access '/srv/study/sessions.db': No such file or directory\n",
                ),
                "missing",
            ),
            (("rc", 3, "something else entirely\n"), "failed (exit 3)"),
        ],
    )
    def test_failure_reasons_are_classified(
        self, cfg, capsys, monkeypatch, outcome, reason
    ):
        monkeypatch.setattr(
            maintenance.subprocess, "run", _Ssh({"/srv/study/sessions.db": outcome})
        )

        assert _fix_perms(cfg, remote=True) == 1

        out = capsys.readouterr().out
        assert (
            f"❌ Remote 'alpha' learner@192.0.2.10:/srv/study/sessions.db: {reason}"
            in out
        ), out

    def test_a_missing_ssh_binary_fails_every_endpoint_but_still_reports_each(
        self, cfg, capsys, monkeypatch
    ):
        def no_ssh(argv, *args, **kwargs):
            raise FileNotFoundError(2, "No such file or directory", "ssh")

        monkeypatch.setattr(maintenance.subprocess, "run", no_ssh)

        assert _fix_perms(cfg, remote=True) == 1

        out = capsys.readouterr().out
        assert out.count("❌ Remote") == 3
        assert "ssh not found" in out

    def test_an_endpoint_without_an_address_is_a_failed_row_not_an_ssh(
        self, cfg, capsys, monkeypatch
    ):
        cfg["endpoints"] = {
            "ghost": {
                "username": "learner",
                "ip_address": {"primary_ip": ""},
                "path": "/srv/study/sessions.db",
                "full_path": "",
            }
        }
        monkeypatch.setattr(maintenance.subprocess, "run", no_process)

        assert _fix_perms(cfg, remote=True) == 1

        out = capsys.readouterr().out
        assert "❌ Remote 'ghost'" in out and "no address configured" in out

    def test_dry_run_with_remote_executes_nothing_and_says_what_it_would_run(
        self, cfg, capsys, monkeypatch
    ):
        monkeypatch.setattr(maintenance.subprocess, "run", no_process)

        assert _fix_perms(cfg, dry_run=True, remote=True) == 0

        out = capsys.readouterr().out
        assert (
            "🔍 Remote 'alpha' learner@192.0.2.10:/srv/study/sessions.db: would run "
            "ssh learner@192.0.2.10 chmod 600 /srv/study/sessions.db"
        ) in out

    def test_a_local_failure_and_a_remote_failure_both_make_the_exit_1(
        self, cfg, capsys, monkeypatch, tmp_path
    ):
        import os

        victim = tmp_path / "backups" / "sessions_backup_20260101_000000.db"
        victim.parent.mkdir(parents=True)
        victim.write_bytes(b"x")
        os.chmod(victim, 0o644)
        real_chmod = os.chmod

        def flaky_chmod(path, mode, *args, **kwargs):
            if Path(path) == victim:
                raise PermissionError(13, "Operation not permitted", str(path))
            return real_chmod(path, mode, *args, **kwargs)

        monkeypatch.setattr(os, "chmod", flaky_chmod)
        monkeypatch.setattr(maintenance.subprocess, "run", _Ssh({}))

        assert _fix_perms(cfg, remote=True) == 1
        out = capsys.readouterr().out
        assert "1 could not be changed" in out
        assert out.count("✅ Remote") == 3


class TestCli:
    def test_remote_flag_reaches_the_remote_sweep(self, cfg, monkeypatch):
        ssh = _Ssh({})
        monkeypatch.setattr(maintenance.subprocess, "run", ssh)
        monkeypatch.setattr(maintenance, "_config", cfg)

        result = runner.invoke(app, ["fix-perms", "--remote"])

        assert result.exit_code == 0, result.output
        assert len(ssh.calls) == 3
        assert "✅ Remote 'beta'" in result.output

    def test_default_stays_print_only(self, cfg, monkeypatch):
        monkeypatch.setattr(maintenance.subprocess, "run", no_process)
        monkeypatch.setattr(maintenance, "_config", cfg)

        result = runner.invoke(app, ["fix-perms"])

        assert result.exit_code == 0, result.output
        assert "not reached from here" in result.output

    def test_help_names_the_flag_and_that_it_is_opt_in(self):
        result = runner.invoke(app, ["fix-perms", "--help"], terminal_width=200)
        assert result.exit_code == 0
        assert "--remote" in result.output
        assert "ssh" in result.output
