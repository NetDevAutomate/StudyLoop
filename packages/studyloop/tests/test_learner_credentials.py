"""Security boundary tests for learner-owned LAN credentials."""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

import pytest
import yaml
from click.testing import CliRunner


def test_password_verifier_accepts_only_the_original_password() -> None:
    """Removing password verification or comparing the encoded hash must fail this test."""
    from studyloop.learner_credentials import hash_password, verify_password

    verifier = hash_password("correct horse battery staple")

    assert "correct horse battery staple" not in verifier
    assert verify_password("correct horse battery staple", verifier)
    assert not verify_password("wrong horse battery staple", verifier)


def test_invalid_password_verifier_fails_closed() -> None:
    """Treating malformed verifier data as disabled authentication must fail this test."""
    from studyloop.learner_credentials import verify_password

    assert not verify_password("anything", "not-a-supported-verifier")


def test_loading_legacy_config_atomically_replaces_plaintext_with_verifier(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Leaving the migrated password bytes in the live config must fail this test."""
    from studyloop.learner_credentials import verify_password
    from studyloop.settings import load_settings

    legacy_password = "legacy-human-password"  # pragma: allowlist secret
    config = tmp_path / "config.yaml"
    config.write_text(
        yaml.safe_dump(
            {
                "lan_username": "learner",
                "lan_password": legacy_password,
                "web_port": 9012,
            },
            sort_keys=False,
        )
    )
    monkeypatch.setenv("STUDYLOOP_CONFIG", str(config))

    settings = load_settings()

    raw_bytes = config.read_bytes()
    migrated = yaml.safe_load(raw_bytes)
    assert legacy_password.encode() not in raw_bytes
    assert "lan_password" not in migrated
    assert verify_password(legacy_password, migrated["lan_password_verifier"])
    assert settings.lan_password_verifier == migrated["lan_password_verifier"]
    assert not hasattr(settings, "lan_password")
    assert settings.web_port == 9012
    assert os.stat(config).st_mode & 0o077 == 0


def test_empty_legacy_password_is_removed_without_creating_authority(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Retaining the legacy credential key after migration must fail this test."""
    from studyloop.settings import load_settings

    config = tmp_path / "config.yaml"
    config.write_text("lan_password: ''\nlan_username: learner\n")
    monkeypatch.setenv("STUDYLOOP_CONFIG", str(config))

    settings = load_settings()

    migrated = yaml.safe_load(config.read_text())
    assert "lan_password" not in migrated
    assert settings.lan_password_verifier == ""


def test_invalid_configured_verifier_is_rejected(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Starting with an attacker-controlled or corrupt verifier must fail this test."""
    from studyloop.settings import ConfigError, load_settings

    config = tmp_path / "config.yaml"
    config.write_text("lan_password_verifier: definitely-not-valid\n")
    monkeypatch.setenv("STUDYLOOP_CONFIG", str(config))

    with pytest.raises(ConfigError, match="LAN password verifier"):
        load_settings()


@pytest.mark.parametrize("command_name", ["web", "study"])
def test_public_cli_neither_documents_nor_accepts_password_argv(command_name: str) -> None:
    """Reintroducing a reusable password in public process argv must fail this test."""
    from studyloop.cli import cli

    runner = CliRunner()
    help_result = runner.invoke(cli, [command_name, "--help"])
    rejected = runner.invoke(
        cli,
        [
            command_name,
            "--password",
            "argv-secret",
            *(["topic"] if command_name == "study" else []),
        ],
    )

    assert help_result.exit_code == 0
    assert "--password" not in help_result.output
    assert rejected.exit_code == 2
    assert "No such option" in rejected.output
    assert "--password" in rejected.output


def test_interactive_credential_preparation_hashes_before_returning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Returning the entered password instead of only its verifier must fail this test."""
    from studyloop.learner_credentials import prepare_lan_auth, verify_password

    prompts = iter(["human-entered-password", "human-entered-password"])
    shown: list[tuple[str, str, bool]] = []
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("getpass.getpass", lambda _prompt: next(prompts))

    username, verifier = prepare_lan_auth(
        username="learner",
        configured_verifier="",
        display=lambda user, password, generated: shown.append((user, password, generated)),
    )

    assert username == "learner"
    assert verify_password("human-entered-password", verifier)
    assert shown == [("learner", "human-entered-password", False)]


def test_noninteractive_credential_preparation_refuses_to_generate_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Falling back to a captured non-TTY password must fail this test."""
    from studyloop.learner_credentials import LearnerCredentialError, prepare_lan_auth

    monkeypatch.setattr("sys.stdin.isatty", lambda: False)

    with pytest.raises(LearnerCredentialError, match="interactive terminal"):
        prepare_lan_auth(username="learner", configured_verifier="", display=lambda *_: None)


def test_real_web_process_migrates_config_without_password_in_argv(tmp_path) -> None:
    """A real long-running public web process must expose neither secret source."""
    legacy_secret = "real-process-legacy-secret"  # pragma: allowlist secret
    config = tmp_path / "config.yaml"
    config.write_text(
        f"lan_username: learner\nlan_password: {legacy_secret}\n"
        f"session_db: {tmp_path / 'sessions.db'}\n"
    )
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]

    env = {
        **os.environ,
        "STUDYLOOP_CONFIG": str(config),
        "STUDYLOOP_SESSION_DIR": str(tmp_path / "ipc"),
        "STUDYLOOP_STATE_DIR": str(tmp_path / "state"),
        "STUDYLOOP_SKIP_LEGACY_MIGRATION": "1",
    }
    process = subprocess.Popen(
        [sys.executable, "-m", "studyloop.cli", "web", "--lan", "--port", str(port)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=env,
    )
    try:
        for _ in range(50):
            if process.poll() is not None:
                pytest.fail(f"web process exited early with {process.returncode}")
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=0.2)
            except urllib.error.HTTPError as exc:
                if exc.code == 401:
                    break
            except OSError:
                pass
            time.sleep(0.1)
        else:
            pytest.fail("web process did not become ready")

        process_argv = subprocess.run(
            ["ps", "-p", str(process.pid), "-o", "command="],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        assert legacy_secret not in process_argv
        assert "--password" not in process_argv
        assert legacy_secret not in config.read_text()
        assert "lan_password:" not in config.read_text()
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def test_config_lan_password_stores_only_verifier(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A persistent-password workflow that writes plaintext must fail this test."""
    from studyloop.cli import cli
    from studyloop.learner_credentials import verify_password

    config = tmp_path / "config.yaml"
    config.write_text("web_port: 9012\n")
    monkeypatch.setenv("STUDYLOOP_CONFIG", str(config))
    monkeypatch.setattr("studyloop.cli._config._stdin_is_interactive", lambda: True)
    prompts = iter(["persistent-human-password", "persistent-human-password"])
    monkeypatch.setattr("getpass.getpass", lambda _prompt: next(prompts))

    result = CliRunner().invoke(cli, ["config", "lan-password"])

    assert result.exit_code == 0, result.output
    raw_bytes = config.read_bytes()
    persisted = yaml.safe_load(raw_bytes)
    assert b"persistent-human-password" not in raw_bytes
    assert "lan_password" not in persisted
    assert verify_password("persistent-human-password", persisted["lan_password_verifier"])
    assert persisted["web_port"] == 9012
    assert "persistent-human-password" not in result.output


def test_config_lan_password_refuses_noninteractive_input(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Allowing a pipeline or agent process to establish human authority must fail."""
    from studyloop.cli import cli

    config = tmp_path / "config.yaml"
    config.write_text("web_port: 9012\n")
    monkeypatch.setenv("STUDYLOOP_CONFIG", str(config))
    monkeypatch.setattr("studyloop.cli._config._stdin_is_interactive", lambda: False)

    result = CliRunner().invoke(cli, ["config", "lan-password"])

    assert result.exit_code == 1
    assert "interactive terminal" in result.output
    assert "lan_password_verifier" not in config.read_text()
