"""Tests for studyctl topics CLI commands (imperative shell)."""

from __future__ import annotations

from unittest.mock import patch

from click.testing import CliRunner


def _runner():
    return CliRunner()


class TestTopicsList:
    def test_empty_backlog(self):
        from studyctl.cli._topics import topics_group

        with patch("studyctl.parking.get_parked_topics", return_value=[]):
            result = _runner().invoke(topics_group, ["list"])

        assert result.exit_code == 0
        assert "no" in result.output.lower() and "topic" in result.output.lower()

    def test_shows_topics_table(self):
        from studyctl.cli._topics import topics_group

        mock_data = [
            {
                "id": 1,
                "question": "Decorators",
                "topic_tag": "Python",
                "tech_area": "Python",
                "source": "parked",
                "context": None,
                "parked_at": "2026-04-01 10:00:00",
            },
            {
                "id": 2,
                "question": "Window funcs",
                "topic_tag": "SQL",
                "tech_area": "SQL",
                "source": "struggled",
                "context": None,
                "parked_at": "2026-04-02 14:00:00",
            },
        ]

        with patch("studyctl.parking.get_parked_topics", return_value=mock_data):
            result = _runner().invoke(topics_group, ["list"])

        assert result.exit_code == 0
        assert "Decorators" in result.output
        assert "Window funcs" in result.output

    def test_filter_by_tech(self):
        from studyctl.cli._topics import topics_group

        with patch("studyctl.parking.get_parked_topics", return_value=[]) as mock_get:
            _runner().invoke(topics_group, ["list", "--tech", "Python"])

        mock_get.assert_called_once_with(status="pending", source=None, tech_area="Python")

    def test_filter_by_source(self):
        from studyctl.cli._topics import topics_group

        with patch("studyctl.parking.get_parked_topics", return_value=[]) as mock_get:
            _runner().invoke(topics_group, ["list", "--source", "struggled"])

        mock_get.assert_called_once_with(status="pending", source="struggled", tech_area=None)


class TestTopicsAdd:
    def test_add_success(self):
        from studyctl.cli._topics import topics_group

        with patch("studyctl.parking.park_topic", return_value=42):
            result = _runner().invoke(
                topics_group,
                ["add", "Python decorators", "--tech", "Python"],
            )

        assert result.exit_code == 0
        assert "#42" in result.output
        assert "Python decorators" in result.output

    def test_add_with_note(self):
        from studyctl.cli._topics import topics_group

        with patch("studyctl.parking.park_topic", return_value=43) as mock_park:
            _runner().invoke(
                topics_group,
                ["add", "Window funcs", "--tech", "SQL", "--note", "For analytics"],
            )

        mock_park.assert_called_once_with(
            question="Window funcs",
            topic_tag="SQL",
            context="For analytics",
            study_session_id=None,
            created_by="cli",
            source="manual",
            tech_area="SQL",
        )

    def test_add_failure(self):
        from studyctl.cli._topics import topics_group

        with patch("studyctl.parking.park_topic", return_value=None):
            result = _runner().invoke(topics_group, ["add", "Something"])

        assert result.exit_code == 0
        assert "failed" in result.output.lower()


class TestTopicsResolve:
    def test_resolve_success(self):
        from studyctl.cli._topics import topics_group

        with patch("studyctl.parking.resolve_parked_topic", return_value=True):
            result = _runner().invoke(topics_group, ["resolve", "42"])

        assert result.exit_code == 0
        assert "#42" in result.output
        assert "resolved" in result.output.lower()

    def test_resolve_not_found(self):
        from studyctl.cli._topics import topics_group

        with patch("studyctl.parking.resolve_parked_topic", return_value=False):
            result = _runner().invoke(topics_group, ["resolve", "999"])

        assert result.exit_code == 0
        assert "not found" in result.output.lower() or "already" in result.output.lower()
