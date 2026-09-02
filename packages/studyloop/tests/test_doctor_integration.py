"""Integration tests for the full doctor pipeline."""

from __future__ import annotations

import json
import urllib.error
from typing import TYPE_CHECKING

import pytest
from click.testing import CliRunner

if TYPE_CHECKING:
    from pathlib import Path


class TestDoctorIntegration:
    @pytest.fixture()
    def runner(self) -> CliRunner:
        return CliRunner()

    @pytest.fixture(autouse=True)
    def _isolate(self, tmp_path: Path, monkeypatch):
        """Isolate from real config/DB and block all network access.

        Patches the module-level _CONFIG_PATH in studyloop.settings so that
        load_settings(), get_db_path(), and check_config_file() all read from
        the temp YAML rather than the real user config.
        """
        import studyloop.settings as _settings

        config = tmp_path / "config.yaml"
        config.write_text("obsidian_base: ''\ntopics: []\n")

        monkeypatch.setattr(_settings, "_CONFIG_PATH", config)
        monkeypatch.setattr("studyloop.doctor.core._get_config_path", lambda: config)

        # Block all network access — prevent 10s timeouts from urllib
        def _block_network(*a, **kw):
            raise urllib.error.URLError("blocked by test")

        monkeypatch.setattr("urllib.request.urlopen", _block_network)
        monkeypatch.setattr(
            "studyloop.doctor.agents._fetch_manifest_with_reason",
            lambda: (None, "offline"),
        )
        monkeypatch.setattr("studyloop.doctor.agents._detect_ai_tools", lambda: [])
        monkeypatch.setattr("studyloop.doctor.updates._fetch_pypi_version", lambda pkg: None)
        monkeypatch.setattr("studyloop.doctor.updates._read_cache", lambda: {})

    def _run_doctor(self, runner, args=None):
        from studyloop.cli._doctor import doctor

        return runner.invoke(doctor, args or ["--json"])

    def _run_update(self, runner, args=None):
        from studyloop.cli._upgrade import update

        return runner.invoke(update, args or ["--json"])

    def test_doctor_runs_all_categories(self, runner: CliRunner):
        result = self._run_doctor(runner)
        assert result.exit_code in (0, 1, 2), (
            f"Unexpected exit code: {result.exit_code}\n{result.output}"
        )
        data = json.loads(result.output)
        categories = {r["category"] for r in data}
        assert "core" in categories
        assert "deps" in categories

    def test_doctor_json_is_list_of_dicts(self, runner: CliRunner):
        result = self._run_doctor(runner)
        assert result.exit_code in (0, 1, 2), (
            f"Unexpected exit code: {result.exit_code}\n{result.output}"
        )
        data = json.loads(result.output)
        assert isinstance(data, list)
        assert len(data) > 0, "Expected at least one check result"
        for item in data:
            assert "category" in item
            assert "status" in item
            assert "fix_hint" in item
            assert "fix_auto" in item

    def test_doctor_json_has_required_fields(self, runner: CliRunner):
        result = self._run_doctor(runner)
        data = json.loads(result.output)
        for item in data:
            assert "name" in item
            assert "message" in item

    def test_doctor_all_statuses_are_valid(self, runner: CliRunner):
        valid_statuses = {"pass", "warn", "fail", "info"}
        result = self._run_doctor(runner)
        data = json.loads(result.output)
        for item in data:
            assert item["status"] in valid_statuses, f"Unexpected status: {item['status']!r}"

    def test_doctor_category_filter(self, runner: CliRunner):
        """--category core returns only core results."""
        result = self._run_doctor(runner, ["--json", "--category", "core"])
        assert result.exit_code in (0, 1, 2)
        data = json.loads(result.output)
        assert all(r["category"] == "core" for r in data)

    def test_update_command_works(self, runner: CliRunner):
        result = self._run_update(runner)
        assert result.exit_code == 0

    def test_update_json_output_is_list(self, runner: CliRunner):
        """update --json returns a JSON list (filtered to core + updates)."""
        result = self._run_update(runner)
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert isinstance(data, list)
        for item in data:
            assert item["category"] in ("core", "updates")

    def test_doctor_quiet_returns_summary_line(self, runner: CliRunner):
        """--quiet mode outputs a single summary line, not JSON."""
        result = self._run_doctor(runner, ["--quiet"])
        assert result.exit_code in (0, 1, 2)
        output = result.output.strip()
        assert output.endswith(".")
        assert not output.startswith("[")

    def test_orphaned_ttyd_port_key_is_named_by_the_real_doctor_command(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        """R-34b: check_unknown_config_keys (R-34) is wired into the real
        `doctor` CLI command, not just unit-tested against the bare
        function. A config.yaml carrying the retired ttyd_port key must
        make the actual `studyloop doctor` invocation name it, exactly as
        a user running the real command would see it -- end-to-end through
        _get_registry(), not through a mocked registry.
        """
        (tmp_path / "config.yaml").write_text(
            "ttyd_port: 7681\nweb_port: 9000\nobsidian_base: ''\ntopics: []\n"
        )

        result = self._run_doctor(runner, ["--json"])

        assert result.exit_code in (0, 1, 2), (
            f"Unexpected exit code: {result.exit_code}\n{result.output}"
        )
        data = json.loads(result.output)
        unknown_key_results = [r for r in data if r["name"] == "unknown_config_keys"]
        assert len(unknown_key_results) == 1
        assert "ttyd_port" in unknown_key_results[0]["message"]
        assert "ttyd_port" in unknown_key_results[0]["fix_hint"]
