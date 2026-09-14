"""The export hooks and the doctor checks that watch them (Stage 5, 2026-09-12).

Born of one incident: the learner's database was migrated by an unpinned
checkout that a hook reached through PATH, the pinned exporter then refused it,
and the hooks' ``|| true`` hid a day of failed exports.
"""

from __future__ import annotations

import json
import os
import sqlite3
import stat
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from studyloop import installers
from studyloop.doctor import exporter
from studyloop.doctor.harness import _claude_hook_result, _kiro_hook_result


class TestHookCommand:
    def test_the_command_is_pinned_logged_and_non_blocking(self) -> None:
        cmd = installers.export_hook_command("--kiro-only")
        assert cmd.startswith("$HOME/.local/bin/session-export --kiro-only"), "pinned path first"
        assert "session-export --kiro-only" in cmd, "the doctor's sentinel survives"
        assert cmd.count(installers.EXPORT_HOOK_LOG) == 2, "stdout/stderr and the failure line"
        assert "FAILED exit=$rc" in cmd and "rc=$?" in cmd, "the exporter's own exit status"
        assert "|| true" not in cmd and "/dev/null" not in cmd

    def test_the_pin_follows_a_non_default_uv_tool_bin_dir(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Found by the first-ever run of scripts/smoke-uv-tool-install.sh in
        `just release-check` (2026-09-14): with UV_TOOL_BIN_DIR pointing away
        from ~/.local/bin, the hooks and doctor's exporter_schema still assumed
        `$HOME/.local/bin/session-export`, so doctor reported fail and every hook
        would have called a path that does not exist."""
        bin_dir = tmp_path / "tools-bin"
        monkeypatch.setenv("UV_TOOL_BIN_DIR", str(bin_dir))
        cmd = installers.export_hook_command("--kiro-only")
        assert cmd.startswith(f"{bin_dir}/session-export --kiro-only"), cmd
        assert exporter.pinned_exporter_path() == bin_dir / "session-export"

    def test_the_pin_keeps_the_portable_home_form_for_uv_default_bin_dir(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """uv's default tool bin dir is ~/.local/bin; hooks then embed `$HOME/...`
        so an installed hook survives a home directory that moves."""
        monkeypatch.delenv("UV_TOOL_BIN_DIR", raising=False)
        monkeypatch.setattr(
            installers, "_uv_tool_bin_dir_from_uv", lambda: installers._HOME / ".local/bin"
        )
        assert installers.export_hook_command("--kiro-only").startswith(
            "$HOME/.local/bin/session-export --kiro-only"
        )

    def test_a_broken_exporter_leaves_a_dated_line_and_the_hook_exits_zero(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import subprocess

        home = tmp_path / "home"
        (home / ".local/bin").mkdir(parents=True)
        (home / ".config/studyloop").mkdir(parents=True)
        fake = home / ".local/bin/session-export"
        fake.write_text(
            "#!/bin/sh\necho 'RuntimeError: Database schema v99 is newer' >&2\nexit 1\n"
        )
        fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
        done = subprocess.run(  # the hook line, exactly as a harness would run it
            ["/bin/sh", "-c", installers.export_hook_command("--kiro-only")],
            env={**os.environ, "HOME": str(home)},
            capture_output=True,
            text=True,
            check=False,
        )
        assert done.returncode == 0, "a failing exporter must not block the session from closing"
        log = (home / ".config/studyloop/export-hook.log").read_text()
        assert "newer" in log and "session-export --kiro-only FAILED exit=1" in log

    def test_the_kiro_template_ships_the_canonical_command(self) -> None:
        repo_root = Path(__file__).resolve().parents[3]
        data = json.loads((repo_root / "agents/kiro/study-mentor.json").read_text())
        commands = [h["command"] for h in data["hooks"]["stop"] if "session-export" in h["command"]]
        assert len(commands) == 1
        assert installers.hook_command_is_canonical(commands[0], "--kiro-only")


class TestClaudeMerge:
    def _settings(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, hooks: dict) -> Path:
        home = tmp_path / "home"
        (home / ".claude").mkdir(parents=True)
        path = home / ".claude/settings.json"
        path.write_text(json.dumps({"hooks": hooks}))
        monkeypatch.setattr(installers, "_HOME", home)
        return path

    def test_a_legacy_silent_hook_is_rewritten_in_place(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        legacy = "/Users/someone/.local/bin/session-export --claude-only >/dev/null 2>&1 || true"
        path = self._settings(
            tmp_path,
            monkeypatch,
            {"Stop": [{"matcher": "", "hooks": [{"type": "command", "command": legacy}]}]},
        )
        assert installers.install_claude_stop_hook() == 1
        data = json.loads(path.read_text())
        commands = [h["command"] for g in data["hooks"]["Stop"] for h in g["hooks"]]
        assert commands == [installers.export_hook_command("--claude-only")]
        assert installers.install_claude_stop_hook() == 0, "idempotent once canonical"

    def test_the_doctor_flags_a_legacy_hook_and_passes_the_canonical_one(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        legacy = "session-export --claude-only >/dev/null 2>&1 || true"
        self._settings(
            tmp_path,
            monkeypatch,
            {"Stop": [{"matcher": "", "hooks": [{"type": "command", "command": legacy}]}]},
        )
        result = _claude_hook_result()
        assert result.status == "warn" and result.fix_auto is True
        assert "unpinned" in result.message
        installers.install_claude_stop_hook()
        assert _claude_hook_result().status == "pass"


class TestKiroHookCheck:
    def test_legacy_kiro_hook_warns_and_canonical_passes(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        home = tmp_path / "home"
        (home / ".kiro/agents").mkdir(parents=True)
        monkeypatch.setattr(installers, "_HOME", home)
        agent = home / ".kiro/agents/study-mentor.json"
        agent.write_text(
            json.dumps(
                {
                    "hooks": {
                        "stop": [{"command": "session-export --kiro-only >/dev/null 2>&1 || true"}]
                    }
                }
            )
        )
        assert _kiro_hook_result().status == "warn"
        agent.write_text(
            json.dumps(
                {"hooks": {"stop": [{"command": installers.export_hook_command("--kiro-only")}]}}
            )
        )
        assert _kiro_hook_result().status == "pass"

    def test_the_migrated_kiro_agent_schema_is_read_too(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A Kiro CLI that migrated the file writes hooks as a list of trigger/action objects."""
        home = tmp_path / "home"
        (home / ".kiro/agents").mkdir(parents=True)
        monkeypatch.setattr(installers, "_HOME", home)
        agent = home / ".kiro/agents/study-mentor.json"
        agent.write_text(
            json.dumps(
                {
                    "hooks": [
                        {
                            "name": "stop-0",
                            "trigger": "stop",
                            "action": {
                                "type": "command",
                                "command": "session-export --kiro-only >/dev/null 2>&1 || true",
                            },
                            "timeout": 10,
                        }
                    ]
                }
            )
        )
        assert _kiro_hook_result().status == "warn", "legacy command in the new schema"
        agent.write_text(
            json.dumps(
                {
                    "hooks": [
                        {
                            "trigger": "stop",
                            "action": {
                                "type": "command",
                                "command": installers.export_hook_command("--kiro-only"),
                            },
                        }
                    ]
                }
            )
        )
        assert _kiro_hook_result().status == "pass"


def _fake_exporter(path: Path, version: int | None) -> Path:
    """A console script whose shebang runs THIS interpreter with a stub agent_session_tools."""
    stub = path.parent / "stub"
    (stub / "agent_session_tools").mkdir(parents=True, exist_ok=True)
    (stub / "agent_session_tools/__init__.py").write_text("")
    body = f"CURRENT_VERSION = {version}\n" if version is not None else "raise ImportError('x')\n"
    (stub / "agent_session_tools/migrations.py").write_text(body)
    # The shebang interpreter is a tiny wrapper that puts the stub first on sys.path.
    wrapper = path.parent / "python-with-stub"
    wrapper.write_text(
        f'#!/bin/sh\nexec "{sys.executable}" -c "import sys; sys.path.insert(0, {str(stub)!r}); '
        'exec(sys.argv[1])" "$2"\n'
    )
    wrapper.chmod(wrapper.stat().st_mode | stat.S_IXUSR)
    path.write_text(f"#!{wrapper}\n")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def _db(path: Path, user_version: int, newest: str | None) -> Path:
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE messages(id TEXT, timestamp TEXT)")
    if newest:
        conn.execute("INSERT INTO messages VALUES ('m', ?)", (newest,))
    conn.execute(f"PRAGMA user_version = {user_version}")
    conn.commit()
    conn.close()
    return path


class TestExporterSchema:
    def test_reads_the_version_the_hooks_interpreter_would_run(self, tmp_path: Path) -> None:
        exp = _fake_exporter(tmp_path / "session-export", 48)
        assert exporter.exporter_schema_version(exp) == 48

    @pytest.mark.parametrize(
        ("supported", "current", "status", "needle"),
        [
            (48, 48, "pass", "agree on schema v48"),
            (47, 48, "fail", "newer than supported"),
            (49, 48, "warn", "will migrate"),
        ],
    )
    def test_compares_exporter_and_database(
        self, tmp_path: Path, supported: int, current: int, status: str, needle: str
    ) -> None:
        exp = _fake_exporter(tmp_path / "session-export", supported)
        db = _db(tmp_path / "sessions.db", current, "2026-09-12T10:00:00Z")
        result = exporter.check_exporter_schema(exp, db)
        assert result.status == status, result.message
        assert needle in result.message

    def test_a_missing_pinned_exporter_fails_loudly(self, tmp_path: Path) -> None:
        db = _db(tmp_path / "sessions.db", 48, None)
        result = exporter.check_exporter_schema(tmp_path / "absent", db)
        assert result.status == "fail" and "install tools" in result.fix_hint

    def test_an_unreadable_version_is_a_warning_not_a_crash(self, tmp_path: Path) -> None:
        exp = _fake_exporter(tmp_path / "session-export", None)
        db = _db(tmp_path / "sessions.db", 48, None)
        assert exporter.check_exporter_schema(exp, db).status == "warn"


class TestExportFreshness:
    def test_fresh_passes_and_stale_warns(self, tmp_path: Path) -> None:
        now = datetime(2026, 9, 12, 16, 0, tzinfo=UTC)
        fresh = _db(tmp_path / "fresh.db", 48, (now - timedelta(hours=3)).isoformat())
        stale = _db(tmp_path / "stale.db", 48, (now - timedelta(hours=21)).isoformat())
        assert exporter.check_export_freshness(fresh, now=now).status == "pass"
        result = exporter.check_export_freshness(stale, now=now, max_age_hours=2)
        assert result.status == "warn" and "21 h old" in result.message
        assert installers.EXPORT_HOOK_LOG in result.message

    def test_zulu_timestamps_parse(self, tmp_path: Path) -> None:
        db = _db(tmp_path / "z.db", 48, "2026-09-11T19:13:45.296Z")
        assert exporter.newest_message_at(db) == datetime(
            2026, 9, 11, 19, 13, 45, 296000, tzinfo=UTC
        )

    def test_an_empty_database_warns(self, tmp_path: Path) -> None:
        db = _db(tmp_path / "empty.db", 48, None)
        assert exporter.check_export_freshness(db).status == "warn"
