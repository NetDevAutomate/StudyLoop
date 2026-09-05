"""Tests for the ``studyloop exercise`` command group."""

from __future__ import annotations

import json

import pytest
from click.testing import CliRunner

from studyloop.cli import cli
from studyloop.planning.exercises import store as exercise_store

REFERENCE = """def make_counter():
    count = 0

    def increment():
        nonlocal count
        count += 1
        return count

    return increment
"""

AUTHORED = """---
id: python--closures
plan_id: python
topic: closures
concepts:
  - closures
---

# Closures

## Blank Slate

### Requirements

- `make_counter()` returns a callable

### Rubric

- [1] Defines the factory `(check: def\\s+make_counter)` `(ask: What has to exist first)`
- [3] Keeps state in scope `(check: nonlocal\\s+\\w+)` `(ask: Where must the count live)`

### Reference Solution

```python
def make_counter():
    count = 0

    def increment():
        nonlocal count
        count += 1
        return count

    return increment
```

## Multiple Choice

### Q1 — What keeps a closure's variable alive?

- [ ] The global namespace `(why: globals are shared between counters)`
- [x] A cell object held by the function
"""


@pytest.fixture
def runner(tmp_path, monkeypatch):
    monkeypatch.setenv(exercise_store.EXERCISES_DIR_ENV, str(tmp_path / "exercises"))
    return CliRunner()


@pytest.fixture
def authored(runner, tmp_path):
    document = tmp_path / "closures.md"
    document.write_text(AUTHORED, encoding="utf-8")
    result = runner.invoke(cli, ["--dev", "exercise", "import", str(document)])
    assert result.exit_code == 0, result.output
    return "python--closures"


def test_exercise_is_hidden_without_dev_flag(runner) -> None:
    help_result = runner.invoke(cli, ["--help"])
    assert help_result.exit_code == 0
    assert "exercise" not in help_result.output

    invoke_result = runner.invoke(cli, ["exercise", "list"])
    assert invoke_result.exit_code == 2
    assert "No such command 'exercise'" in invoke_result.output


def test_dev_flag_exposes_exercise_command(runner) -> None:
    result = runner.invoke(cli, ["--dev", "exercise", "--help"])
    assert result.exit_code == 0
    assert "Author and review the three topic exercise formats" in result.output


def test_list_is_honest_when_empty(runner) -> None:
    result = runner.invoke(cli, ["--dev", "exercise", "list"])
    assert result.exit_code == 0
    assert "No exercise sets yet" in result.output


def test_new_creates_all_three_formats(runner, tmp_path) -> None:
    reference = tmp_path / "sol.py"
    reference.write_text(REFERENCE, encoding="utf-8")
    result = runner.invoke(
        cli,
        [
            *["--dev", "exercise", "new"],
            "--topic",
            "closures",
            "--plan",
            "python",
            "--requirement",
            "make_counter() returns a callable",
            "--reference",
            str(reference),
            "--json",
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    formats = payload["set"]["formats"]
    assert formats["blank_slate"]["has_starter_code"] is False
    assert formats["completion"]["has_starter_code"] is True
    assert 0.0 < formats["completion"]["scaffold_ratio"] < 1.0
    # Nothing invented — the gaps are reported.
    assert payload["readiness"]["ready"] is False


def test_show_markdown_hides_the_answer(runner, authored) -> None:
    result = runner.invoke(cli, ["--dev", "exercise", "show", authored, "--markdown"])
    assert result.exit_code == 0
    assert "nonlocal count" not in result.output
    assert "- [x]" not in result.output
    # The brief survives.
    assert "What keeps a closure's variable alive?" in result.output


def test_show_with_answers_is_the_authoring_view(runner, authored) -> None:
    result = runner.invoke(cli, ["--dev", "exercise", "show", authored, "--with-answers"])
    assert result.exit_code == 0
    assert "nonlocal count" in result.output
    assert "- [x]" in result.output


def test_show_reports_missing_formats(runner, authored) -> None:
    result = runner.invoke(cli, ["--dev", "exercise", "show", authored])
    assert result.exit_code == 0
    assert "Not fully authored" in result.output
    assert "completion" in result.output.lower()


def test_show_rejects_an_unknown_set(runner) -> None:
    result = runner.invoke(cli, ["--dev", "exercise", "show", "nope"])
    assert result.exit_code == 1
    assert "No exercise set with id" in result.output


def test_review_scores_a_weak_attempt_and_asks_questions(runner, authored) -> None:
    result = runner.invoke(
        cli,
        ["--dev", "exercise", "review", authored, "--kind", "blank_slate", "--stdin"],
        input="def make_counter():\n    pass\n",
    )
    assert result.exit_code == 0, result.output
    assert "Score 25/100" in result.output
    assert "Ask, do not tell" in result.output
    assert "Where must the count live?" in result.output
    # The output an agent pastes must not carry the solution.
    assert "nonlocal count" not in result.output


def test_review_requires_a_submission_source(runner, authored) -> None:
    result = runner.invoke(cli, ["--dev", "exercise", "review", authored, "--kind", "blank_slate"])
    assert result.exit_code == 1
    assert "--file" in result.output


def test_review_accepts_letter_answers_for_multiple_choice(runner, authored) -> None:
    right = runner.invoke(
        cli,
        [
            "--dev",
            "exercise",
            "review",
            authored,
            "--kind",
            "multiple_choice",
            "--answer",
            "0:b",
            "--json",
        ],
    )
    assert right.exit_code == 0, right.output
    assert json.loads(right.output)["review"]["score"] == 100

    wrong = runner.invoke(
        cli,
        [
            "--dev",
            "exercise",
            "review",
            authored,
            "--kind",
            "multiple_choice",
            "--answer",
            "0:a",
            "--json",
        ],
    )
    review = json.loads(wrong.output)["review"]
    assert review["score"] == 0
    assert "globals are shared" in review["results"][0]["question"]


def test_review_rejects_a_malformed_answer(runner, authored) -> None:
    result = runner.invoke(
        cli,
        [
            "--dev",
            "exercise",
            "review",
            authored,
            "--kind",
            "multiple_choice",
            "--answer",
            "zero:a",
        ],
    )
    assert result.exit_code == 1
    assert "expected 'question:choice'" in result.output


def test_review_of_a_missing_format_fails_cleanly(runner, authored) -> None:
    result = runner.invoke(
        cli,
        ["--dev", "exercise", "review", authored, "--kind", "completion", "--stdin"],
        input="x",
    )
    assert result.exit_code == 1
    assert "no 'completion' exercise" in result.output


def test_import_rejects_an_unparseable_file(runner, tmp_path) -> None:
    bad = tmp_path / "bad.md"
    bad.write_bytes(b"\xff\xfe not utf 8")
    result = runner.invoke(cli, ["--dev", "exercise", "import", str(bad)])
    assert result.exit_code == 1
    assert "Could not parse" in result.output


def test_path_prints_the_documents_directory(runner) -> None:
    result = runner.invoke(cli, ["--dev", "exercise", "path"])
    assert result.exit_code == 0
    assert "exercises" in result.output


def test_from_milestone_seeds_from_the_plan(runner, tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("STUDYLOOP_PLANS_DIR", str(tmp_path / "plans"))
    from studyloop.planning import create_plan, draft_plan

    plan = draft_plan(
        "Master Closures",
        {
            "why": "Ship a retry decorator",
            "success": ["Write one from memory"],
            "milestones": ["Closures (concepts: closures, cell variables)"],
        },
        plan_id="master-closures",
    )
    create_plan(plan)

    result = runner.invoke(
        cli, ["--dev", "exercise", "from-milestone", "master-closures", "--json"]
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["set"]["concepts"] == ["closures", "cell variables"]
    assert payload["set"]["plan_id"] == "master-closures"


def test_from_milestone_rejects_a_planless_id(runner) -> None:
    result = runner.invoke(cli, ["--dev", "exercise", "from-milestone", "nope"])
    assert result.exit_code == 1
