"""Mastery graph command group."""

from __future__ import annotations

import json

import click
from rich.table import Table

from studyloop.cli._shared import console
from studyloop.learning.mastery import (
    mastery_graph_json,
    mastery_graph_mermaid,
    weak_links_for_topic,
)


@click.group("mastery")
def mastery_group() -> None:
    """Inspect concept mastery and dependency weak links."""


@mastery_group.command("graph")
@click.option("--topic", required=True, help="Topic/domain to render.")
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["mermaid", "json"]),
    default="mermaid",
    show_default=True,
)
def mastery_graph(topic: str, output_format: str) -> None:
    """Render a topic mastery graph."""
    if output_format == "json":
        click.echo(json.dumps(mastery_graph_json(topic), indent=2))
        return
    click.echo(mastery_graph_mermaid(topic))


@mastery_group.command("weak-links")
@click.option("--topic", required=True, help="Topic/domain to inspect.")
def mastery_weak_links(topic: str) -> None:
    """Show weak prerequisite links for a topic."""
    links = weak_links_for_topic(topic)
    if not links:
        console.print("[dim]No weak links found for this topic yet.[/dim]")
        return

    table = Table(title=f"Weak Links: {topic}")
    table.add_column("Concept", style="bold")
    table.add_column("Blocks")
    table.add_column("Reason")
    table.add_column("Source", style="dim")
    for link in links:
        table.add_row(
            str(link.get("concept") or ""),
            str(link.get("dependency") or ""),
            str(link.get("reason") or ""),
            str(link.get("source") or ""),
        )
    console.print(table)
