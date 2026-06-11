"""Tests for teach-back CLI commands."""

from __future__ import annotations

from typing import Any

from click.testing import CliRunner

from studyloop.cli import cli


def test_teachback_records_valid_scores(monkeypatch) -> None:
    calls: list[dict[str, Any]] = []

    def fake_record_teachback(**kwargs: Any) -> bool:
        calls.append(kwargs)
        return True

    monkeypatch.setattr("studyloop.history.record_teachback", fake_record_teachback)

    result = CliRunner().invoke(
        cli,
        [
            "teachback",
            "decorators",
            "--topic",
            "python",
            "--score",
            "3,3,4,3,2",
            "--type",
            "structured",
            "--angle",
            "apply_network_analogy",
            "--notes",
            "Good structure, transfer needs work.",
        ],
    )

    assert result.exit_code == 0
    assert "Recorded teach-back" in result.output
    assert "15/20" in result.output
    assert calls == [
        {
            "concept": "decorators",
            "topic": "python",
            "scores": (3, 3, 4, 3, 2),
            "review_type": "structured",
            "angle": "apply_network_analogy",
            "notes": "Good structure, transfer needs work.",
        }
    ]


def test_teachback_rejects_missing_score() -> None:
    result = CliRunner().invoke(
        cli,
        [
            "teachback",
            "decorators",
            "--topic",
            "python",
            "--type",
            "micro",
        ],
    )

    assert result.exit_code != 0
    assert "Missing option '--score'" in result.output


def test_teachback_rejects_wrong_score_count() -> None:
    result = CliRunner().invoke(
        cli,
        [
            "teachback",
            "decorators",
            "--topic",
            "python",
            "--score",
            "1,2,3,4",
            "--type",
            "micro",
        ],
    )

    assert result.exit_code != 0
    assert "exactly five" in result.output


def test_teachback_rejects_non_integer_scores() -> None:
    result = CliRunner().invoke(
        cli,
        [
            "teachback",
            "decorators",
            "--topic",
            "python",
            "--score",
            "1,2,x,4,3",
            "--type",
            "micro",
        ],
    )

    assert result.exit_code != 0
    assert "integers from 1 to 4" in result.output


def test_teachback_rejects_out_of_range_scores() -> None:
    result = CliRunner().invoke(
        cli,
        [
            "teachback",
            "decorators",
            "--topic",
            "python",
            "--score",
            "1,2,3,4,5",
            "--type",
            "micro",
        ],
    )

    assert result.exit_code != 0
    assert "between 1 and 4" in result.output


def test_teachback_history_shows_empty_message(monkeypatch) -> None:
    calls: list[tuple[str, str | None]] = []

    def fake_get_teachback_history(concept: str, topic: str | None = None) -> list[dict[str, Any]]:
        calls.append((concept, topic))
        return []

    monkeypatch.setattr("studyloop.history.get_teachback_history", fake_get_teachback_history)

    result = CliRunner().invoke(cli, ["teachback-history", "decorators", "--topic", "python"])

    assert result.exit_code == 0
    assert "No teach-back history" in result.output
    assert "decorators" in result.output
    assert "python" in result.output
    assert calls == [("decorators", "python")]


def test_teachback_history_renders_recent_scores(monkeypatch) -> None:
    def fake_get_teachback_history(concept: str, topic: str | None = None) -> list[dict[str, Any]]:
        assert concept == "decorators"
        assert topic is None
        return [
            {
                "concept": "decorators",
                "topic": "python",
                "score_accuracy": 3,
                "score_own_words": 3,
                "score_structure": 4,
                "score_depth": 3,
                "score_transfer": 2,
                "total_score": 15,
                "review_type": "structured",
                "question_angle": "apply_network_analogy",
                "notes": "Good structure, transfer needs work.",
                "created_at": "2026-06-11 08:30:00",
            }
        ]

    monkeypatch.setattr("studyloop.history.get_teachback_history", fake_get_teachback_history)

    result = CliRunner().invoke(cli, ["teachback-history", "decorators"])

    assert result.exit_code == 0
    assert "Teach-back History" in result.output
    assert "python" in result.output
    assert "structured" in result.output
    assert "3,3,4,3,2" in result.output
    assert "15/20" in result.output
    assert "apply_network_analogy" in result.output
