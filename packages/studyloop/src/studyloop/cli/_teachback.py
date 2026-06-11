"""Teach-back CLI commands."""

from __future__ import annotations

from typing import cast

import click
from rich.table import Table

from studyloop.cli._shared import console

TEACHBACK_TYPES = ("micro", "structured", "transfer", "full")


class TeachbackScoresParam(click.ParamType):
    """Parse five comma-separated teach-back rubric scores."""

    name = "scores"

    def convert(
        self,
        value: object,
        param: click.Parameter | None,
        ctx: click.Context | None,
    ) -> tuple[int, int, int, int, int]:
        if isinstance(value, tuple):
            return cast("tuple[int, int, int, int, int]", value)

        raw = str(value)
        parts = [part.strip() for part in raw.split(",")]
        if len(parts) != 5 or any(part == "" for part in parts):
            self.fail(
                'expected exactly five comma-separated scores, e.g. "3,3,4,3,2"',
                param,
                ctx,
            )

        try:
            scores = tuple(int(part) for part in parts)
        except ValueError:
            self.fail("scores must be integers from 1 to 4", param, ctx)

        if any(score < 1 or score > 4 for score in scores):
            self.fail("each score must be between 1 and 4", param, ctx)

        return cast("tuple[int, int, int, int, int]", scores)


TEACHBACK_SCORES = TeachbackScoresParam()


@click.command(name="teachback")
@click.argument("concept")
@click.option("--topic", "-t", required=True, help="Study topic for this concept.")
@click.option(
    "--score",
    "scores",
    required=True,
    type=TEACHBACK_SCORES,
    help='Five rubric scores, comma-separated, e.g. "3,3,4,3,2".',
)
@click.option(
    "--type",
    "review_type",
    required=True,
    type=click.Choice(TEACHBACK_TYPES),
    help="Teach-back review type.",
)
@click.option("--angle", default=None, help="Question angle or prompt variant used.")
@click.option("--notes", default=None, help="Optional assessment notes.")
def teachback(
    concept: str,
    topic: str,
    scores: tuple[int, int, int, int, int],
    review_type: str,
    angle: str | None,
    notes: str | None,
) -> None:
    """Record a teach-back assessment for a concept."""
    from studyloop.history import record_teachback

    if not record_teachback(
        concept=concept,
        topic=topic,
        scores=scores,
        review_type=review_type,
        angle=angle,
        notes=notes,
    ):
        raise click.ClickException(
            "Failed to record teach-back. Run 'studyloop doctor' to diagnose."
        )

    total = sum(scores)
    console.print(
        f"[green]Recorded teach-back:[/green] "
        f"[bold]{concept}[/bold] ({topic}, {review_type}) - [bold]{total}/20[/bold]"
    )


@click.command(name="teachback-history")
@click.argument("concept")
@click.option("--topic", "-t", default=None, help="Filter to one study topic.")
def teachback_history(concept: str, topic: str | None) -> None:
    """Show recent teach-back scores for a concept."""
    from studyloop.history import get_teachback_history

    rows = get_teachback_history(concept, topic=topic)
    if not rows:
        topic_suffix = f" in {topic}" if topic else ""
        console.print(f"[dim]No teach-back history for {concept}{topic_suffix}.[/dim]")
        return

    table = Table(title=f"Teach-back History: {concept}")
    table.add_column("Date")
    table.add_column("Topic", style="cyan")
    table.add_column("Type", no_wrap=True)
    table.add_column("Scores")
    table.add_column("Total", justify="right")
    table.add_column("Angle", no_wrap=True)

    for row in rows:
        scores = (
            row["score_accuracy"],
            row["score_own_words"],
            row["score_structure"],
            row["score_depth"],
            row["score_transfer"],
        )
        total = row.get("total_score")
        if total is None:
            total = sum(scores)

        table.add_row(
            str(row.get("created_at") or "")[:10],
            str(row.get("topic") or "-"),
            str(row.get("review_type") or "-"),
            ",".join(str(score) for score in scores),
            f"{total}/20",
            str(row.get("question_angle") or "-"),
        )

    console.print(table)
