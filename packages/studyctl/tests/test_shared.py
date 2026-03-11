"""Tests for shared module — init_config, push_state, pull_state, sync_status."""

from __future__ import annotations

import socket
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml


def _make_hosts_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    local_state_json: str = "",
    local_sessions_db: str = "",
) -> Path:
    """Create a hosts-style config with local machine auto-detected."""
    hostname = socket.gethostname().split(".")[0]
    config = {
        "hosts": {
            "laptop": {
                "hostname": hostname,
                "ip_address": {"primary": "192.168.1.50"},
                "user": "testuser",
                "state_json": local_state_json or str(tmp_path / "state.json"),
                "sessions_db": local_sessions_db,
            },
            "miniserver": {
                "hostname": "some-other-host",
                "ip_address": {
                    "primary": "192.168.1.100",
                    "secondary": "10.0.0.100",
                },
                "user": "testuser",
                "state_json": "~/.config/studyctl/state.json",
            },
        },
    }
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.dump(config))
    monkeypatch.setattr("studyctl.shared.CONFIG_PATH", config_path)
    return config_path


class TestLoadConfig:
    def test_returns_empty_when_no_file(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from studyctl.shared import _load_config

        monkeypatch.setattr("studyctl.shared.CONFIG_PATH", Path("/nonexistent/config.yaml"))
        assert _load_config() == {}

    def test_loads_yaml(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from studyctl.shared import _load_config

        config_path = tmp_path / "config.yaml"
        config_path.write_text(yaml.dump({"hosts": {"laptop": {"hostname": "test"}}}))
        monkeypatch.setattr("studyctl.shared.CONFIG_PATH", config_path)

        result = _load_config()
        assert result["hosts"]["laptop"]["hostname"] == "test"

    def test_empty_yaml_returns_empty(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from studyctl.shared import _load_config

        config_path = tmp_path / "config.yaml"
        config_path.write_text("")
        monkeypatch.setattr("studyctl.shared.CONFIG_PATH", config_path)

        assert _load_config() == {}


class TestResolveHosts:
    def test_identifies_local_by_hostname(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from studyctl.shared import _resolve_hosts

        hostname = socket.gethostname().split(".")[0]
        config = {
            "hosts": {
                "this-machine": {"hostname": hostname, "ip_address": {"primary": "1.2.3.4"}},
                "other": {"hostname": "not-me", "ip_address": {"primary": "5.6.7.8"}},
            }
        }
        local_name, local_config, remotes = _resolve_hosts(config)
        assert local_name == "this-machine"
        assert local_config["hostname"] == hostname
        assert "other" in remotes
        assert "this-machine" not in remotes

    def test_no_matching_hostname(self) -> None:
        from studyctl.shared import _resolve_hosts

        config = {
            "hosts": {
                "a": {"hostname": "not-this-machine"},
                "b": {"hostname": "also-not-this"},
            }
        }
        local_name, local_config, remotes = _resolve_hosts(config)
        assert local_name is None
        assert local_config == {}
        assert len(remotes) == 2

    def test_empty_hosts(self) -> None:
        from studyctl.shared import _resolve_hosts

        local_name, _, remotes = _resolve_hosts({})
        assert local_name is None
        assert remotes == {}


class TestGetHostIps:
    def test_dict_format(self) -> None:
        from studyctl.shared import _get_host_ips

        assert _get_host_ips({"ip_address": {"primary": "1.1.1.1", "secondary": "2.2.2.2"}}) == [
            "1.1.1.1",
            "2.2.2.2",
        ]

    def test_primary_only(self) -> None:
        from studyctl.shared import _get_host_ips

        assert _get_host_ips({"ip_address": {"primary": "1.1.1.1"}}) == ["1.1.1.1"]

    def test_no_ip(self) -> None:
        from studyctl.shared import _get_host_ips

        assert _get_host_ips({}) == []


class TestSyncStatus:
    def test_unconfigured(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from studyctl.shared import sync_status

        monkeypatch.setattr("studyctl.shared.CONFIG_PATH", Path("/nonexistent/config.yaml"))
        result = sync_status()
        assert result["configured"] is False

    def test_configured_with_reachable_remote(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from studyctl.shared import sync_status

        _make_hosts_config(tmp_path, monkeypatch)

        mock_result = MagicMock()
        mock_result.returncode = 0

        with patch("studyctl.shared.subprocess.run", return_value=mock_result):
            result = sync_status()

        assert result["configured"] is True
        assert result["local"] == "laptop"
        assert result["remotes"]["miniserver"]["reachable"] is True

    def test_configured_with_unreachable_remote(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from studyctl.shared import sync_status

        _make_hosts_config(tmp_path, monkeypatch)

        mock_result = MagicMock()
        mock_result.returncode = 255

        with patch("studyctl.shared.subprocess.run", return_value=mock_result):
            result = sync_status()

        assert result["remotes"]["miniserver"]["reachable"] is False


class TestPushState:
    def test_raises_when_no_config(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from studyctl.shared import push_state

        monkeypatch.setattr("studyctl.shared.CONFIG_PATH", Path("/nonexistent/config.yaml"))
        with pytest.raises(FileNotFoundError):
            push_state()

    def test_pushes_state_json(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from studyctl.shared import push_state

        state_json = tmp_path / "state.json"
        state_json.write_text("{}")

        _make_hosts_config(tmp_path, monkeypatch, local_state_json=str(state_json))

        mock_result = MagicMock()
        mock_result.returncode = 0

        with patch("studyctl.shared.subprocess.run", return_value=mock_result):
            pushed = push_state()

        assert any("state.json" in p for p in pushed)

    def test_push_specific_remote(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from studyctl.shared import push_state

        hostname = socket.gethostname().split(".")[0]
        state_json = tmp_path / "state.json"
        state_json.write_text("{}")

        config = {
            "hosts": {
                "laptop": {
                    "hostname": hostname,
                    "ip_address": {"primary": "192.168.1.50"},
                    "user": "u",
                    "state_json": str(state_json),
                    "sessions_db": "",
                },
                "server-a": {
                    "hostname": "host-a",
                    "ip_address": {"primary": "1.1.1.1"},
                    "user": "u",
                },
                "server-b": {
                    "hostname": "host-b",
                    "ip_address": {"primary": "2.2.2.2"},
                    "user": "u",
                },
            }
        }
        config_path = tmp_path / "config.yaml"
        config_path.write_text(yaml.dump(config))
        monkeypatch.setattr("studyctl.shared.CONFIG_PATH", config_path)

        mock_result = MagicMock()
        mock_result.returncode = 0

        with patch("studyctl.shared.subprocess.run", return_value=mock_result):
            pushed = push_state(remote="server-a")

        assert any("server-a" in p for p in pushed)
        assert not any("server-b" in p for p in pushed)


class TestPullState:
    def test_raises_when_no_config(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from studyctl.shared import pull_state

        monkeypatch.setattr("studyctl.shared.CONFIG_PATH", Path("/nonexistent/config.yaml"))
        with pytest.raises(FileNotFoundError):
            pull_state()

    def test_pulls_state_json(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from studyctl.shared import pull_state

        _make_hosts_config(tmp_path, monkeypatch, local_state_json=str(tmp_path / "state.json"))

        mock_result = MagicMock()
        mock_result.returncode = 0

        with patch("studyctl.shared.subprocess.run", return_value=mock_result):
            pulled = pull_state()

        assert any("state.json" in p for p in pulled)


class TestInitConfig:
    def test_creates_default_config(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from studyctl.shared import init_config

        config_path = tmp_path / "config.yaml"
        monkeypatch.setattr("studyctl.shared.CONFIG_PATH", config_path)

        result = init_config()
        assert result == config_path
        assert config_path.exists()
        data = yaml.safe_load(config_path.read_text())
        assert "hosts" in data

    def test_does_not_overwrite_existing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from studyctl.shared import init_config

        config_path = tmp_path / "config.yaml"
        config_path.write_text("existing: true")
        monkeypatch.setattr("studyctl.shared.CONFIG_PATH", config_path)

        result = init_config()
        assert result == config_path
        assert "existing: true" in config_path.read_text()
