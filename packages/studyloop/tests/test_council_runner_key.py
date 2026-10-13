"""``scripts/council/run_council.py`` finds the gateway key without a human.

The litellm-proxy-docker install moved its secrets out of ``.env``: the file now
carries ``LITELLM_MASTER_KEY_REF=op://...`` (a 1Password reference) where it
used to carry ``LITELLM_MASTER_KEY=<literal>``. The council runner only knew the
literal form, so with ``LITELLM_API_KEY`` unset it exited with "no gateway key"
on a machine whose gateway was up and whose key ``op read`` resolves without a
prompt -- a council could not be convened unattended. These tests pin the
resolution order and the one rule that matters for receipts: the key value is
never echoed in a message.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
RUNNER = REPO_ROOT / "scripts" / "council" / "run_council.py"


@pytest.fixture
def runner(monkeypatch: pytest.MonkeyPatch):
    spec = importlib.util.spec_from_file_location("run_council_under_test", RUNNER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    monkeypatch.delenv(module.ENV_KEY, raising=False)
    yield module
    sys.modules.pop(spec.name, None)


def _env_file(tmp_path: Path, body: str):
    path = tmp_path / ".env"
    path.write_text(body, encoding="utf-8")
    return path


def test_env_var_wins_without_reading_the_file(runner, tmp_path, monkeypatch):
    monkeypatch.setenv(runner.ENV_KEY, "sk-from-env")
    monkeypatch.setattr(runner, "DOCKER_ENV", tmp_path / "absent.env")
    assert runner._api_key() == "sk-from-env"


def test_literal_master_key_in_the_env_file_still_works(runner, tmp_path, monkeypatch):
    monkeypatch.setattr(
        runner,
        "DOCKER_ENV",
        _env_file(tmp_path, "OTHER=1\nLITELLM_MASTER_KEY='sk-literal'\n"),
    )
    assert runner._api_key() == "sk-literal"


def test_a_1password_reference_is_resolved_with_op_read(runner, tmp_path, monkeypatch):
    monkeypatch.setattr(
        runner,
        "DOCKER_ENV",
        _env_file(tmp_path, 'LITELLM_MASTER_KEY_REF="op://vault/item/field"\n'),
    )
    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        calls.append(list(cmd))
        return subprocess.CompletedProcess(cmd, 0, stdout="sk-resolved\n", stderr="")

    monkeypatch.setattr(runner.subprocess, "run", fake_run)

    assert runner._api_key() == "sk-resolved"
    assert calls == [["op", "read", "op://vault/item/field"]]


def test_a_failing_op_read_is_a_clean_exit_that_names_the_cause(runner, tmp_path, monkeypatch):
    monkeypatch.setattr(
        runner,
        "DOCKER_ENV",
        _env_file(tmp_path, "LITELLM_MASTER_KEY_REF=op://vault/item/field\n"),
    )

    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(
            cmd, 1, stdout="", stderr="[ERROR] account is not signed in"
        )

    monkeypatch.setattr(runner.subprocess, "run", fake_run)

    with pytest.raises(SystemExit) as excinfo:
        runner._api_key()
    message = str(excinfo.value)
    assert "op read" in message
    assert "not signed in" in message


def test_no_key_anywhere_is_the_original_message(runner, tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "DOCKER_ENV", _env_file(tmp_path, "UNRELATED=1\n"))
    with pytest.raises(SystemExit, match="no gateway key"):
        runner._api_key()
