"""Small, runnable examples linked by the public contributor testing cookbook."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest
from click.testing import CliRunner

from studyloop.cli import _practice as practice_cli
from studyloop.learning.practice import peek_verification_command

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def deck_path(tmp_path: Path) -> Path:
    """Synthetic content only; creating the deck must not execute its command."""
    path = tmp_path / "practice.json"
    path.write_text(
        json.dumps(
            {
                "title": "Contributor example",
                "tasks": [
                    {
                        "taskType": "build",
                        "prompt": "Explain why approval is required.",
                        "setup": "",
                        "successCriteria": ["The learner can explain the boundary."],
                        "hint": "",
                        "expectedLearningOutcome": "Explicit consent",
                        "verification": {
                            "kind": "command",
                            "command": "echo synthetic-check",
                            "successCriteria": ["The check exits successfully."],
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


def test_peek_returns_command_without_changing_deck(deck_path: Path) -> None:
    before = deck_path.read_bytes()

    result = peek_verification_command(deck_path, task_index=1)

    assert result == ("command", "echo synthetic-check")
    assert deck_path.read_bytes() == before


@pytest.mark.parametrize("task_index", [0, 2])
def test_peek_rejects_out_of_range_task(deck_path: Path, task_index: int) -> None:
    with pytest.raises(ValueError, match="--task must be between"):
        peek_verification_command(deck_path, task_index=task_index)


def test_cli_refusal_never_calls_verifier(deck_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden_verifier(*args, **kwargs):
        pytest.fail("The verifier must not run without approval")

    monkeypatch.setattr(practice_cli, "verify_practice_task", forbidden_verifier)
    result = CliRunner().invoke(
        practice_cli.practice_group,
        ["verify", str(deck_path), "--task", "1", "--run-command"],
    )

    assert result.exit_code == 2
    assert "nothing executed" in result.output
