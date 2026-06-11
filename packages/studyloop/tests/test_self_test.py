"""Tests for the lightweight ``studyloop self-test`` command."""

from __future__ import annotations

import json
from pathlib import Path

import click
from click.testing import CliRunner

from studyloop.cli import _self_test as self_test_cli
from studyloop.cli import cli
from studyloop.self_test import SelfTestResult, exit_code_for, results_as_json, run_self_tests

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_exit_code_for_results() -> None:
    assert exit_code_for([SelfTestResult("one", "pass", "ok")]) == 0
    assert (
        exit_code_for(
            [
                SelfTestResult("one", "pass", "ok"),
                SelfTestResult("two", "warn", "check setup"),
            ]
        )
        == 1
    )
    assert (
        exit_code_for(
            [
                SelfTestResult("one", "warn", "check setup"),
                SelfTestResult("two", "fail", "broken"),
            ]
        )
        == 2
    )


def test_results_as_json_is_valid_json() -> None:
    payload = results_as_json([SelfTestResult("cli_import", "pass", "Imported studyloop.cli")])

    assert json.loads(payload) == [
        {
            "name": "cli_import",
            "status": "pass",
            "message": "Imported studyloop.cli",
        }
    ]


def test_run_self_tests_has_required_check_names(tmp_path, monkeypatch) -> None:
    config_path = tmp_path / "config.yaml"
    monkeypatch.setenv("STUDYLOOP_CONFIG", str(config_path))
    monkeypatch.setenv("STUDYLOOP_SKIP_LEGACY_MIGRATION", "1")

    results = run_self_tests()

    assert {result.name for result in results} >= {
        "cli_import",
        "config_read",
        "database_path",
        "web_import",
    }
    by_name = {result.name: result for result in results}
    assert by_name["config_read"].status == "warn"
    assert by_name["database_path"].status == "pass"


def test_self_test_json_output(monkeypatch) -> None:
    monkeypatch.setattr(
        self_test_cli,
        "run_self_tests",
        lambda: [SelfTestResult("cli_import", "pass", "ok")],
    )

    result = CliRunner().invoke(cli, ["self-test", "--json"])

    assert result.exit_code == 0
    assert json.loads(result.output) == [{"name": "cli_import", "status": "pass", "message": "ok"}]


def test_self_test_quiet_output(monkeypatch) -> None:
    monkeypatch.setattr(
        self_test_cli,
        "run_self_tests",
        lambda: [
            SelfTestResult("cli_import", "pass", "ok"),
            SelfTestResult("config_read", "warn", "missing config"),
        ],
    )

    result = CliRunner().invoke(cli, ["self-test", "--quiet"])

    assert result.exit_code == 1
    assert result.output.strip() == "self-test: 1 passed, 1 warning, 0 failures."
    assert "missing config" not in result.output


def test_self_test_command_registration_and_docs() -> None:
    command = click.Context(cli).command
    assert isinstance(command, click.Group)
    assert command.get_command(click.Context(command), "self-test") is not None

    cli_reference = REPO_ROOT / "docs" / "cli-reference.md"
    assert "studyloop self-test" in cli_reference.read_text(encoding="utf-8")
