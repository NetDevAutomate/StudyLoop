"""Tests for doctor PyPI version checks with caching."""

from __future__ import annotations

import json
import os
import time
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

if TYPE_CHECKING:
    from pathlib import Path


class TestPypiVersionCheck:
    def test_up_to_date(self):
        from studyctl.doctor.updates import check_pypi_versions

        pypi_response = json.dumps({"info": {"version": "2.0.0"}}).encode()
        mock_resp = MagicMock()
        mock_resp.read.return_value = pypi_response
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with (
            patch("studyctl.doctor.updates._get_installed_version", return_value="2.0.0"),
            patch("studyctl.doctor.updates._read_cache", return_value=None),
            patch("urllib.request.urlopen", return_value=mock_resp),
            patch("studyctl.doctor.updates._write_cache"),
        ):
            results = check_pypi_versions()
        assert any(r.status == "pass" and "studyctl" in r.name for r in results)

    def test_update_available(self):
        from studyctl.doctor.updates import check_pypi_versions

        pypi_response = json.dumps({"info": {"version": "2.1.0"}}).encode()
        mock_resp = MagicMock()
        mock_resp.read.return_value = pypi_response
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with (
            patch("studyctl.doctor.updates._get_installed_version", return_value="2.0.0"),
            patch("studyctl.doctor.updates._read_cache", return_value=None),
            patch("urllib.request.urlopen", return_value=mock_resp),
            patch("studyctl.doctor.updates._write_cache"),
        ):
            results = check_pypi_versions()
        assert any(r.status == "warn" and r.fix_auto for r in results)

    def test_network_failure_returns_info(self):
        import urllib.error

        from studyctl.doctor.updates import check_pypi_versions

        with (
            patch("studyctl.doctor.updates._get_installed_version", return_value="2.0.0"),
            patch("studyctl.doctor.updates._read_cache", return_value=None),
            patch("urllib.request.urlopen", side_effect=urllib.error.URLError("offline")),
        ):
            results = check_pypi_versions()
        assert all(r.status == "info" for r in results)

    def test_cache_hit_skips_network(self):
        from studyctl.doctor.updates import check_pypi_versions

        cached = {"studyctl": "2.0.0", "agent-session-tools": "1.0.0"}

        with (
            patch("studyctl.doctor.updates._get_installed_version", return_value="2.0.0"),
            patch("studyctl.doctor.updates._read_cache", return_value=cached),
        ):
            results = check_pypi_versions()
        assert any(r.status == "pass" for r in results)


class TestCache:
    def test_write_and_read(self, tmp_path: Path):
        from studyctl.doctor.updates import _read_cache, _write_cache

        cache_file = tmp_path / "pypi-check.json"
        data = {"studyctl": "2.0.0"}
        with patch("studyctl.doctor.updates._get_cache_path", return_value=cache_file):
            _write_cache(data)
            result = _read_cache()
        assert result == data

    def test_expired_cache_returns_none(self, tmp_path: Path):
        from studyctl.doctor.updates import _read_cache, _write_cache

        cache_file = tmp_path / "pypi-check.json"
        data = {"studyctl": "2.0.0"}
        with patch("studyctl.doctor.updates._get_cache_path", return_value=cache_file):
            _write_cache(data)
            old_time = time.time() - 7200  # 2 hours ago
            os.utime(cache_file, (old_time, old_time))
            result = _read_cache()
        assert result is None
