"""Deterministic learning-map rendering for canonical plan Markdown.

Only trusted StudyLoop code writes Mermaid syntax. Learner-authored labels are
encoded as numeric entities and stable plan identities are hashed into Mermaid
node identifiers, so label text cannot add nodes, edges, or directives.
"""

from __future__ import annotations

from hashlib import sha256
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .models import StudyPlan


def _normalise_label(value: str, *, fallback: str) -> str:
    normalised = " ".join(str(value).split())
    return normalised or fallback


def _encode_label(value: str, *, fallback: str, preserve_spaces: bool) -> str:
    label = _normalise_label(value, fallback=fallback)
    safe: list[str] = []
    entity_prefix = "&#" if preserve_spaces else "#"
    for character in label:
        if (character.isascii() and character.isalnum()) or (preserve_spaces and character == " "):
            safe.append(character)
        else:
            safe.append(f"{entity_prefix}{ord(character)};")
    return "".join(safe)


def _node_id(kind: str, stable_id: str, *, fallback: str) -> str:
    identity = stable_id or fallback
    digest = sha256(f"{kind}:{identity}".encode()).hexdigest()[:16]
    return f"{kind}_{digest}"


def _reject_duplicate_ids(kind: str, identities: list[str]) -> None:
    seen: set[str] = set()
    for identity in identities:
        if not identity:
            continue
        if identity in seen:
            msg = f"duplicate {kind}: {identity}"
            raise ValueError(msg)
        seen.add(identity)


def render_learning_map(plan: StudyPlan) -> str:
    """Return an accessible hierarchy and derived Mermaid learning map.

    Node identifiers depend on stable goal/milestone identities rather than
    display labels. Legacy objects without IDs receive deterministic,
    plan-local positional identities so old documents still render safely.
    """
    if not plan.goals and not plan.milestones:
        return "### Text learning map\n\n_No goals or milestones yet._"

    _reject_duplicate_ids("goal_id", [goal.goal_id for goal in plan.goals])
    _reject_duplicate_ids("milestone_id", [milestone.milestone_id for milestone in plan.milestones])

    goal_node_lines: list[str] = []
    milestone_node_lines: list[str] = []
    edge_lines: list[str] = []
    text_lines = ["### Text learning map", ""]

    linked_milestones: set[int] = set()
    for goal_index, goal in enumerate(plan.goals):
        fallback_id = f"{plan.plan_id}:goal:{goal_index}"
        node_id = _node_id("g", goal.goal_id, fallback=fallback_id)
        diagram_label = _encode_label(
            goal.title,
            fallback="Untitled goal",
            preserve_spaces=False,
        )
        text_label = _encode_label(
            goal.title,
            fallback="Untitled goal",
            preserve_spaces=True,
        )
        goal_node_lines.append(f'    {node_id}["{diagram_label}"]')
        text_lines.append(f"- Goal: {text_label}")

        for milestone_index, milestone in enumerate(plan.milestones):
            if not milestone.goal_id or not goal.goal_id or milestone.goal_id != goal.goal_id:
                continue
            linked_milestones.add(milestone_index)
            milestone_fallback = f"{plan.plan_id}:milestone:{milestone_index}"
            milestone_node = _node_id(
                "m",
                milestone.milestone_id,
                fallback=milestone_fallback,
            )
            milestone_label = _encode_label(
                milestone.title,
                fallback="Untitled milestone",
                preserve_spaces=False,
            )
            text_milestone = _encode_label(
                milestone.title,
                fallback="Untitled milestone",
                preserve_spaces=True,
            )
            milestone_node_lines.append(f'    {milestone_node}["{milestone_label}"]')
            edge_lines.append(f"    {node_id} --> {milestone_node}")
            text_lines.append(f"  - Milestone: {text_milestone}")

    unlinked = [
        (index, milestone)
        for index, milestone in enumerate(plan.milestones)
        if index not in linked_milestones
    ]
    if unlinked:
        text_lines.append("- Unassigned milestones")
        for milestone_index, milestone in unlinked:
            milestone_fallback = f"{plan.plan_id}:milestone:{milestone_index}"
            milestone_node = _node_id(
                "m",
                milestone.milestone_id,
                fallback=milestone_fallback,
            )
            milestone_label = _encode_label(
                milestone.title,
                fallback="Untitled milestone",
                preserve_spaces=False,
            )
            text_milestone = _encode_label(
                milestone.title,
                fallback="Untitled milestone",
                preserve_spaces=True,
            )
            milestone_node_lines.append(f'    {milestone_node}["{milestone_label}"]')
            text_lines.append(f"  - Milestone: {text_milestone}")

    diagram_lines = [
        "```mermaid",
        "flowchart TD",
        *goal_node_lines,
        *milestone_node_lines,
        *edge_lines,
        "```",
    ]
    return "\n".join([*text_lines, "", *diagram_lines])
