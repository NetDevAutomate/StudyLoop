"""Tests for config_loader module."""

from pathlib import Path

from agent_session_tools.config_loader import (
    DEFAULT_CONFIG,
    expand_path,
    get_backup_dir,
    get_db_path,
    get_log_path,
    load_config,
)


class TestExpandPath:
    """Tests for expand_path function."""

    def test_expand_tilde(self):
        """Test expanding ~ to home directory."""
        result = expand_path("~/test/path")
        assert not str(result).startswith("~")
        assert Path.home() in result.parents or result == Path.home() / "test" / "path"

    def test_expand_env_var(self, monkeypatch):
        """Test expanding environment variables."""
        monkeypatch.setenv("TEST_VAR", "/custom/path")
        result = expand_path("$TEST_VAR/subdir")
        assert "/custom/path" in str(result)

    def test_regular_path(self):
        """Test that regular paths are returned as Path objects."""
        result = expand_path("/absolute/path")
        assert isinstance(result, Path)
        assert str(result) == "/absolute/path"


class TestLoadConfig:
    """Tests for load_config function."""

    def test_returns_dict(self):
        """Test that load_config returns a dictionary."""
        config = load_config()
        assert isinstance(config, dict)

    def test_has_required_keys(self):
        """Test that config has all required keys."""
        config = load_config()
        assert "database" in config
        assert "thresholds" in config
        assert "logging" in config
        assert "tui" in config

    def test_database_section(self):
        """Test database configuration section."""
        config = load_config()
        assert "path" in config["database"]
        assert "archive_path" in config["database"]
        assert "backup_dir" in config["database"]

    def test_thresholds_section(self):
        """Test thresholds configuration section."""
        config = load_config()
        assert "warning_mb" in config["thresholds"]
        assert "critical_mb" in config["thresholds"]
        assert isinstance(config["thresholds"]["warning_mb"], int)
        assert isinstance(config["thresholds"]["critical_mb"], int)

    def test_env_override_database_path(self, monkeypatch):
        """Test that DATABASE_PATH env var overrides config."""
        test_path = "/custom/test/path.db"
        monkeypatch.setenv("DATABASE_PATH", test_path)
        config = load_config()
        assert config["database"]["path"] == test_path

    def test_env_override_log_level(self, monkeypatch):
        """Test that LOG_LEVEL env var overrides config."""
        monkeypatch.setenv("LOG_LEVEL", "DEBUG")
        config = load_config()
        assert config["logging"]["level"] == "DEBUG"


class TestDefaultConfig:
    """Tests for DEFAULT_CONFIG constant."""

    def test_default_config_structure(self):
        """Test default config has expected structure."""
        assert "database" in DEFAULT_CONFIG
        assert "thresholds" in DEFAULT_CONFIG
        assert "logging" in DEFAULT_CONFIG
        assert "tui" in DEFAULT_CONFIG

    def test_default_threshold_values(self):
        """Test default threshold values are reasonable."""
        assert DEFAULT_CONFIG["thresholds"]["warning_mb"] == 100
        assert DEFAULT_CONFIG["thresholds"]["critical_mb"] == 500


class TestGetDbPath:
    """Tests for get_db_path function."""

    def test_returns_path(self):
        """Test that get_db_path returns a Path object."""
        result = get_db_path()
        assert isinstance(result, Path)

    def test_with_config(self):
        """Test get_db_path with explicit config."""
        config = {"database": {"path": "/test/path.db"}}
        result = get_db_path(config)
        assert result == Path("/test/path.db")


class TestGetBackupDir:
    """Tests for get_backup_dir function."""

    def test_returns_path(self):
        """Test that get_backup_dir returns a Path object."""
        result = get_backup_dir()
        assert isinstance(result, Path)


class TestGetLogPath:
    """Tests for get_log_path function."""

    def test_returns_path(self):
        """Test that get_log_path returns a Path object."""
        result = get_log_path()
        assert isinstance(result, Path)
