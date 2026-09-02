"""Tests for config_loader module."""

import os
import subprocess
import sys
from pathlib import Path

from agent_session_tools.config_loader import (
    DEFAULT_CONFIG,
    ensure_config_dir,
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

    def test_reads_yaml_from_studyloop_config_path(self, tmp_path, monkeypatch):
        """Test that STUDYLOOP_CONFIG points load_config at a custom YAML file."""
        config_path = tmp_path / "custom" / "studyloop.yaml"
        config_path.parent.mkdir()
        config_path.write_text(
            """
database:
  path: /tmp/custom-sessions.db
logging:
  level: DEBUG
thresholds:
  warning_mb: 42
""",
            encoding="utf-8",
        )
        monkeypatch.setenv("STUDYLOOP_CONFIG", str(config_path))
        monkeypatch.delenv("DATABASE_PATH", raising=False)
        monkeypatch.delenv("LOG_LEVEL", raising=False)
        monkeypatch.delenv("WARNING_THRESHOLD_MB", raising=False)

        config = load_config()

        assert config["database"]["path"] == "/tmp/custom-sessions.db"
        assert config["logging"]["level"] == "DEBUG"
        assert config["thresholds"]["warning_mb"] == 42


class TestEnsureConfigDir:
    """Tests for ensure_config_dir function."""

    def test_creates_config_and_env_at_studyloop_config_path(
        self, tmp_path, monkeypatch
    ):
        """Test that STUDYLOOP_CONFIG controls created config and .env paths."""
        config_path = tmp_path / "profile" / "config.yaml"
        env_path = config_path.parent / ".env"
        monkeypatch.setenv("STUDYLOOP_CONFIG", str(config_path))

        ensure_config_dir()

        assert config_path.exists()
        assert env_path.exists()


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


class TestDotenvCannotSetTheTestHatch:
    """R-09b: this loader is a SECOND, independent dotenv load that a `.env`
    at ``~/.config/studyloop/.env`` reaches even after studyloop's own R-09
    scrub (``studyloop/__init__.py``) has already run and refused it.

    ``export_sessions.py`` calls ``load_config()`` at MODULE IMPORT TIME
    (top-level statement), and ``studyloop/web/_schema_init.py``'s
    ``prepare_schema()`` -- called from ``web/app.py``'s server-startup
    lifespan -- imports ``agent_session_tools.export_sessions``, which
    triggers that call. So a `.env` planted at this path re-adds
    STUDYLOOP_TEST_AGENT_CMD/ACP_CMD on every server boot, strictly AFTER
    studyloop's own import-time scrub already deleted it, before the first
    request is served.

    A package-import-time side effect can only be observed honestly in a
    FRESH interpreter, so this spawns a real subprocess with a fake HOME --
    same technique as ``studyloop/tests/test_dotenv_test_hatch.py``.
    """

    @staticmethod
    def _write_fake_home_env_file(home: Path) -> None:
        env_dir = home / ".config" / "studyloop"
        env_dir.mkdir(parents=True)
        (env_dir / ".env").write_text(
            "STUDYLOOP_TEST_AGENT_CMD=/bin/false\n"
            "STUDYLOOP_OTHER_THING=hello-from-dotenv\n"
        )

    @staticmethod
    def _run(tmp_path: Path, home: Path, code: str) -> subprocess.CompletedProcess[str]:
        # cwd is a SEPARATE tmp dir with no .env anywhere in it or its
        # parents, so studyloop's own directory-walking loader cannot also
        # find a file here -- this test isolates the SECOND loader only.
        cwd = tmp_path / "cwd"
        cwd.mkdir()
        env = {"PATH": os.environ.get("PATH", ""), "HOME": str(home)}
        return subprocess.run(
            [sys.executable, "-c", code],
            cwd=str(cwd),
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )

    def test_planted_home_env_file_cannot_set_the_hatch(self, tmp_path: Path) -> None:
        home = tmp_path / "home"
        home.mkdir()
        self._write_fake_home_env_file(home)

        # Import studyloop first, exactly like the real process does --
        # its own R-09 scrub runs and finds nothing yet (this .env is a
        # different path from the one it walks up from cwd).
        code = (
            "import studyloop; "
            "from agent_session_tools.config_loader import load_config; "
            "load_config(); "
            "import os; "
            "print(repr(os.environ.get('STUDYLOOP_TEST_AGENT_CMD')))"
        )
        proc = self._run(tmp_path, home, code)

        assert proc.returncode == 0, proc.stderr
        assert proc.stdout.strip() == "None"

    def test_warns_once_naming_the_key_and_the_env_path(self, tmp_path: Path) -> None:
        home = tmp_path / "home"
        home.mkdir()
        self._write_fake_home_env_file(home)

        code = (
            "import studyloop; "
            "from agent_session_tools.config_loader import load_config; "
            "load_config()"
        )
        proc = self._run(tmp_path, home, code)

        assert "STUDYLOOP_TEST_AGENT_CMD" in proc.stderr
        assert str(home / ".config" / "studyloop" / ".env") in proc.stderr

    def test_other_dotenv_keys_still_load(self, tmp_path: Path) -> None:
        home = tmp_path / "home"
        home.mkdir()
        self._write_fake_home_env_file(home)

        code = (
            "import studyloop; "
            "from agent_session_tools.config_loader import load_config; "
            "load_config(); "
            "import os; "
            "print(repr(os.environ.get('STUDYLOOP_OTHER_THING')))"
        )
        proc = self._run(tmp_path, home, code)

        assert proc.returncode == 0, proc.stderr
        assert proc.stdout.strip() == repr("hello-from-dotenv")

    def test_harness_exported_hatch_still_works(self, tmp_path: Path) -> None:
        """The value is trusted when the REAL process env already had it
        before this loader's dotenv call -- same rule as studyloop's own
        scrub, and the same guarantee the e2e harness relies on."""
        home = tmp_path / "home"
        home.mkdir()
        self._write_fake_home_env_file(home)

        cwd = tmp_path / "cwd"
        cwd.mkdir()
        env = {
            "PATH": os.environ.get("PATH", ""),
            "HOME": str(home),
            "STUDYLOOP_TEST_AGENT_CMD": "from-parent-env",
        }
        code = (
            "import studyloop; "
            "from agent_session_tools.config_loader import load_config; "
            "load_config(); "
            "import os; "
            "print(repr(os.environ.get('STUDYLOOP_TEST_AGENT_CMD')))"
        )
        proc = subprocess.run(
            [sys.executable, "-c", code],
            cwd=str(cwd),
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )

        assert proc.returncode == 0, proc.stderr
        assert proc.stdout.strip() == repr("from-parent-env")
