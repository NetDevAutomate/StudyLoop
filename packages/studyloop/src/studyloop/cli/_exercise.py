"""Exercise command group — the three topic formats and their review pipeline.

The agent-facing surface. Every command has a ``--json`` form because a Socratic
mentor drives these programmatically, while the default output stays readable in
a terminal sidebar.

``exercise review`` prints the Markdown block by default: that is what the agent
pastes into the conversation after an attempt. Note what it prints and what it
does not — a score, which criteria held, and the *questions* to work through.
Never the solution. An agent that reads this output cannot accidentally hand over
the answer, because the answer is not in it.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import NoReturn

import click
from rich.table import Table

from studyloop.cli._shared import console
from studyloop.planning.exercises import (
    EXERCISE_KINDS,
    ExerciseSet,
    create_set,
    exercises_dir,
    from_milestone,
    list_sets,
    load_set,
    parse_exercise_set,
    readiness,
    record_review,
    render_exercise_set,
    render_for_learner,
    review_submission,
    unique_set_id,
)
from studyloop.planning.exercises.store import (
    ExerciseSetExistsError,
    ExerciseSetNotFoundError,
    InvalidSetIdError,
)


def _fail(message: str) -> NoReturn:
    """Print an error and exit non-zero, never a traceback."""
    console.print(f"[red]{message}[/red]")
    raise SystemExit(1)


def _load(set_id: str) -> ExerciseSet:
    try:
        return load_set(set_id)
    except ExerciseSetNotFoundError:
        _fail(f"No exercise set with id {set_id!r}. Try: studyloop exercise list")
    except InvalidSetIdError as exc:
        _fail(str(exc))


def _print_readiness(check: dict) -> None:
    if check["blockers"]:
        console.print("[yellow]Not fully authored:[/yellow]")
        for item in check["blockers"]:
            console.print(f"  [red]•[/red] {item}")
    else:
        console.print("[green]All three formats are ready.[/green]")
    for item in check["nudges"]:
        console.print(f"  [dim]• {item}[/dim]")


@click.group("exercise")
def exercise_group() -> None:
    """Author and review the three topic exercise formats."""


@exercise_group.command("list")
@click.option("--plan", "plan_id", default="", help="Only sets belonging to this plan.")
@click.option("--topic", default="", help="Only sets for this topic.")
@click.option("--json", "as_json", is_flag=True, help="Machine-readable output.")
def exercise_list(plan_id: str, topic: str, as_json: bool) -> None:
    """List exercise sets."""
    sets = list_sets(plan_id=plan_id, topic=topic)
    if as_json:
        click.echo(json.dumps([s.summary() for s in sets], indent=2))
        return
    if not sets:
        console.print(
            "[dim]No exercise sets yet. Create one: "
            "studyloop exercise new --topic ... --requirement ...[/dim]"
        )
        return

    table = Table(title="Exercise Sets")
    table.add_column("ID", style="bold")
    table.add_column("Topic")
    table.add_column("Plan", style="dim")
    table.add_column("Formats")
    for item in sets:
        missing = item.missing_formats()
        formats = "all 3" if not missing else f"{3 - len(missing)}/3 (missing {', '.join(missing)})"
        table.add_row(item.set_id, item.topic, item.plan_id or "—", formats)
    console.print(table)


@exercise_group.command("show")
@click.argument("set_id")
@click.option(
    "--markdown",
    "as_markdown",
    is_flag=True,
    help="Print the learner-safe document (no answers).",
)
@click.option(
    "--with-answers",
    is_flag=True,
    help="Include reference solutions and marked answers. Author use only.",
)
@click.option("--json", "as_json", is_flag=True, help="Machine-readable output.")
def exercise_show(set_id: str, as_markdown: bool, with_answers: bool, as_json: bool) -> None:
    """Show one exercise set.

    Answers are withheld unless ``--with-answers`` is passed, so pasting this
    output into a study session cannot hand over the solution.
    """
    item = _load(set_id)
    if as_markdown or with_answers:
        click.echo(render_exercise_set(item) if with_answers else render_for_learner(item))
        return
    if as_json:
        click.echo(json.dumps({"set": item.summary(), "readiness": readiness(item)}, indent=2))
        return

    console.print(f"[bold]{item.title}[/bold]  [dim]({item.set_id})[/dim]")
    if item.plan_id:
        console.print(f"Plan: {item.plan_id}")
    for kind in ("blank_slate", "completion"):
        exercise = item.code_exercise(kind)
        label = kind.replace("_", " ").title()
        if exercise is None:
            console.print(f"\n[bold]{label}[/bold]  [red]absent[/red]")
            continue
        scaffold = (
            "no starting code"
            if not exercise.starter_code.strip()
            else f"{round(exercise.scaffold_ratio * 100)}% supplied"
        )
        console.print(f"\n[bold]{label}[/bold]  [dim]({scaffold})[/dim]")
        for requirement in exercise.requirements:
            console.print(f"  • {requirement}")
    answerable = sum(1 for q in item.multiple_choice if q.is_answerable())
    console.print(f"\n[bold]Multiple Choice[/bold]  {answerable} answerable question(s)")
    console.print()
    _print_readiness(readiness(item))


@exercise_group.command("new")
@click.option("--topic", required=True, help="Topic the exercises cover.")
@click.option("--plan", "plan_id", default="", help="Study plan this belongs to.")
@click.option("--concept", "concepts", multiple=True, help="Mastery concept (repeatable).")
@click.option(
    "--requirement",
    "requirements",
    multiple=True,
    help="A requirement the learner must satisfy (repeatable).",
)
@click.option(
    "--reference",
    "reference_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
    help="File holding the reference solution. The completion format is sliced from it.",
)
@click.option(
    "--reveal",
    type=float,
    default=0.4,
    show_default=True,
    help="Fraction of the reference revealed as completion starter code (capped below 1).",
)
@click.option("--language", default="python", show_default=True, help="Code language.")
@click.option("--json", "as_json", is_flag=True, help="Machine-readable output.")
def exercise_new(
    topic: str,
    plan_id: str,
    concepts: tuple[str, ...],
    requirements: tuple[str, ...],
    reference_path: Path | None,
    reveal: float,
    language: str,
    as_json: bool,
) -> None:
    """Create an exercise set with all three formats.

    The completion exercise is derived from the blank slate, so one authored task
    yields both code formats. Nothing is invented: a missing rubric check or a
    missing quiz is reported by ``readiness``, not filled in with a guess.
    """
    from studyloop.planning.exercises import draft_exercise_set

    reference = reference_path.read_text(encoding="utf-8") if reference_path else ""
    try:
        item = draft_exercise_set(
            topic,
            plan_id=plan_id,
            set_id=unique_set_id(plan_id, topic),
            concepts=list(concepts),
            requirements=list(requirements),
            reference_solution=reference,
            language=language,
            reveal=reveal,
        )
    except ValueError as exc:
        _fail(str(exc))

    try:
        path = create_set(item)
    except (ExerciseSetExistsError, InvalidSetIdError) as exc:
        _fail(str(exc))

    check = readiness(item)
    if as_json:
        click.echo(
            json.dumps({"set": item.summary(), "readiness": check, "path": str(path)}, indent=2)
        )
        return
    console.print(f"[green]Created[/green] {item.set_id} → {path}")
    _print_readiness(check)


@exercise_group.command("from-milestone")
@click.argument("plan_id")
@click.option("--index", type=int, default=None, help="Milestone index (default: next unchecked).")
@click.option("--json", "as_json", is_flag=True, help="Machine-readable output.")
def exercise_from_milestone(plan_id: str, index: int | None, as_json: bool) -> None:
    """Draft an exercise set from a study plan's milestone.

    Requirements are seeded from the milestone's concepts — the same join key the
    plan uses against ``study_progress`` — so the exercise, the milestone, and
    the confidence evidence all name the same thing.
    """
    from studyloop.planning import load_plan
    from studyloop.planning.store import InvalidPlanIdError, PlanNotFoundError

    try:
        plan = load_plan(plan_id)
    except (PlanNotFoundError, InvalidPlanIdError) as exc:
        _fail(str(exc))

    if not plan.milestones:
        _fail(f"Plan {plan_id!r} has no milestones to build exercises from.")
    if index is None:
        milestone = plan.next_milestone() or plan.milestones[0]
    elif 0 <= index < len(plan.milestones):
        milestone = plan.milestones[index]
    else:
        _fail(f"No milestone at index {index} (plan has {len(plan.milestones)}).")

    item = from_milestone(plan.plan_id, milestone.title, milestone.concepts)
    item.set_id = unique_set_id(plan.plan_id, item.topic)
    try:
        path = create_set(item)
    except (ExerciseSetExistsError, InvalidSetIdError) as exc:
        _fail(str(exc))

    check = readiness(item)
    if as_json:
        click.echo(
            json.dumps({"set": item.summary(), "readiness": check, "path": str(path)}, indent=2)
        )
        return
    console.print(
        f"[green]Created[/green] {item.set_id} for milestone {milestone.title!r} → {path}"
    )
    _print_readiness(check)


@exercise_group.command("review")
@click.argument("set_id")
@click.option(
    "--kind",
    type=click.Choice(EXERCISE_KINDS),
    default="blank_slate",
    show_default=True,
    help="Which format is being attempted.",
)
@click.option(
    "--file",
    "submission_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
    help="File holding the learner's code. Use '-' semantics via --stdin instead.",
)
@click.option("--stdin", "from_stdin", is_flag=True, help="Read the submission from stdin.")
@click.option(
    "--answer",
    "answers",
    multiple=True,
    help="Multiple-choice answer as 'question:choice' or 'question:a,b' (repeatable).",
)
@click.option("--record", is_flag=True, help="Write the confidence signal to study_progress.")
@click.option("--json", "as_json", is_flag=True, help="Machine-readable output.")
def exercise_review(
    set_id: str,
    kind: str,
    submission_path: Path | None,
    from_stdin: bool,
    answers: tuple[str, ...],
    record: bool,
    as_json: bool,
) -> None:
    """Score an attempt and print the Socratic follow-up.

    The same pipeline serves both code formats: a completion attempt is scored on
    what the learner *added*, with criteria the starter code already satisfied
    marked ``given`` and excluded. Output carries questions, never the solution.
    """
    item = _load(set_id)

    submission = ""
    if kind != "multiple_choice":
        if from_stdin:
            submission = sys.stdin.read()
        elif submission_path is not None:
            submission = submission_path.read_text(encoding="utf-8")
        else:
            _fail("Provide the attempt with --file PATH or --stdin.")

    parsed_answers: dict[int, list[int]] = {}
    for entry in answers:
        question_part, _, choice_part = entry.partition(":")
        try:
            question_index = int(question_part.strip())
        except ValueError:
            _fail(f"Bad --answer {entry!r}: expected 'question:choice', e.g. '0:b'.")
        picks: list[int] = []
        for token in choice_part.split(","):
            token = token.strip().lower()
            if not token:
                continue
            if token.isdigit():
                picks.append(int(token))
            elif len(token) == 1 and token.isalpha():
                picks.append(ord(token) - ord("a"))
            else:
                _fail(f"Bad choice {token!r} in --answer {entry!r}: use 0-based index or a letter.")
        parsed_answers[question_index] = picks

    if kind == "multiple_choice" and not parsed_answers:
        _fail("Provide at least one --answer, e.g. --answer 0:b")

    try:
        review = review_submission(item, kind, submission=submission, answers=parsed_answers)
    except LookupError as exc:
        _fail(str(exc))

    recorded = record_review(review, concepts=item.concepts) if record else False

    if as_json:
        click.echo(
            json.dumps({"review": review.to_dict(), "recorded": recorded}, indent=2, default=str)
        )
        return
    click.echo(review.as_markdown())
    if record:
        state = "recorded" if recorded else "not recorded (progress DB unavailable)"
        console.print(f"[dim]Confidence signal {state}.[/dim]")


@exercise_group.command("import")
@click.argument("path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--json", "as_json", is_flag=True, help="Machine-readable output.")
def exercise_import(path: Path, as_json: bool) -> None:
    """Import a hand-authored exercise document.

    Multiple-choice questions are authored in plain Markdown (``- [x]`` marks the
    correct option), so a set can be written in any text editor with no tooling.
    """
    try:
        item = parse_exercise_set(path.read_text(encoding="utf-8"))
    except Exception as exc:
        _fail(f"Could not parse {path}: {exc}")
    if not item.set_id:
        item.set_id = unique_set_id(item.plan_id, item.topic)
    try:
        written = create_set(item, overwrite=False)
    except (ExerciseSetExistsError, InvalidSetIdError) as exc:
        _fail(str(exc))

    check = readiness(item)
    if as_json:
        click.echo(
            json.dumps({"set": item.summary(), "readiness": check, "path": str(written)}, indent=2)
        )
        return
    console.print(f"[green]Imported[/green] {item.set_id} → {written}")
    _print_readiness(check)


@exercise_group.command("path")
def exercise_path_cmd() -> None:
    """Print the directory holding exercise documents."""
    click.echo(str(exercises_dir()))
