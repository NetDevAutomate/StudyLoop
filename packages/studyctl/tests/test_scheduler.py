"""Tests for scheduler module -- output verification only, no real job installation."""

from unittest.mock import patch

from studyctl.scheduler import Job, _cron_expression, _cron_line, _launchd_plist, list_jobs


class TestJobDataclass:
    def test_stores_fields(self):
        job = Job(name="test-job", command="~/bin/run", schedule="every 2h", description="A test")
        assert job.name == "test-job"
        assert job.command == "~/bin/run"
        assert job.schedule == "every 2h"
        assert job.description == "A test"

    def test_default_description(self):
        job = Job(name="x", command="y", schedule="z")
        assert job.description == ""


class TestLaunchdPlist:
    def test_contains_label(self):
        job = Job(name="my-job", command="~/.local/bin/do-stuff", schedule="every 2h")
        plist = _launchd_plist(job, "testuser")
        assert "com.studyctl.my-job" in plist

    def test_contains_program_arguments(self):
        job = Job(name="run", command="~/.local/bin/studyctl sync --all", schedule="daily 7am")
        with patch("studyctl.scheduler._is_macos", return_value=True):
            plist = _launchd_plist(job, "alice")
        assert "/Users/alice/.local/bin/studyctl" in plist
        assert "<string>sync</string>" in plist
        assert "<string>--all</string>" in plist

    def test_every_2h_schedule(self):
        job = Job(name="j", command="~/cmd", schedule="every 2h")
        plist = _launchd_plist(job, "u")
        assert "StartCalendarInterval" in plist
        assert "<array>" in plist

    def test_daily_schedule(self):
        job = Job(name="j", command="~/cmd", schedule="daily 9am")
        plist = _launchd_plist(job, "u")
        assert "<integer>9</integer>" in plist

    def test_valid_xml_structure(self):
        job = Job(name="j", command="~/cmd", schedule="every 4h")
        plist = _launchd_plist(job, "u")
        assert plist.startswith("<?xml version=")
        assert plist.rstrip().endswith("</plist>")


class TestCronEntry:
    def test_every_2h_expression(self):
        job = Job(name="j", command="~/cmd", schedule="every 2h")
        assert _cron_expression(job) == "0 8-22/2 * * *"

    def test_every_4h_expression(self):
        job = Job(name="j", command="~/cmd", schedule="every 4h")
        assert _cron_expression(job) == "30 8-22/4 * * *"

    def test_daily_expression(self):
        job = Job(name="j", command="~/cmd", schedule="daily 7am")
        assert _cron_expression(job) == "0 7 * * *"

    def test_cron_line_contains_marker(self):
        job = Job(name="my-job", command="~/.local/bin/run", schedule="every 2h")
        line = _cron_line(job)
        assert "# studyctl:my-job" in line

    def test_cron_line_expands_tilde(self):
        job = Job(name="j", command="~/.local/bin/run", schedule="every 2h")
        line = _cron_line(job)
        assert "~" not in line.split("#")[0]  # tilde should be expanded in command portion


class TestListJobs:
    @patch("studyctl.scheduler._launchd_list", return_value=[])
    @patch("studyctl.scheduler._is_macos", return_value=True)
    def test_returns_empty_on_macos(self, _mock_mac, _mock_list):
        assert list_jobs() == []

    @patch("studyctl.scheduler._cron_list", return_value=[])
    @patch("studyctl.scheduler._is_macos", return_value=False)
    def test_returns_empty_on_linux(self, _mock_mac, _mock_list):
        assert list_jobs() == []
