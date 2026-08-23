"""Authoring support: interview the learner, then draft a plan.

The agent does the talking; this module supplies the *structure* so every plan
comes out shaped the same way and grounded in real data:

* :data:`INTERVIEW` — the mission-first question set the agent must work
  through before writing anything (a bad mission is worse than no mission).
* :func:`seed_from_history` — what the databases already suggest the learner
  should plan for, so the interview starts from evidence rather than a blank
  page.
* :func:`draft_plan` — turn answers into a valid :class:`StudyPlan`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from studyloop.learning.concept_quality import is_usable_concept

from .models import Milestone, Mission, Resource, StudyPlan, slugify, utc_now_iso

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class InterviewQuestion:
    """One question in the plan-creation interview."""

    key: str
    prompt: str
    why: str
    required: bool = True
    multi: bool = False


#: Ordered interview. ``why`` is shown to the agent, not the learner — it
#: explains what the answer is *for*, so the agent can tell a usable answer
#: from a vague one and push back rather than accepting filler.
INTERVIEW: tuple[InterviewQuestion, ...] = (
    InterviewQuestion(
        key="why",
        prompt="What changes in your work or life once you have this skill?",
        why="The mission. Grounds every milestone; abstract answers make plans untrackable.",
    ),
    InterviewQuestion(
        key="success",
        prompt="What will you be able to *do* that you cannot do today? (2-4 things)",
        why="Observable success criteria — the completion test for the whole plan.",
        multi=True,
    ),
    InterviewQuestion(
        key="topics",
        prompt="Which StudyLoop topics does this sit under?",
        why="Join key for spaced repetition, struggle signal, and session matching.",
        multi=True,
    ),
    InterviewQuestion(
        key="constraints",
        prompt="How much time per week, and on which days/energy levels?",
        why="Bounds milestone size. AuDHD-relevant: prevents plans only a good day can serve.",
        multi=True,
        required=False,
    ),
    InterviewQuestion(
        key="out_of_scope",
        prompt="What adjacent rabbit holes are explicitly NOT part of this?",
        why="Protects the zone of proximal development and gives the parking lot a rule.",
        multi=True,
        required=False,
    ),
    InterviewQuestion(
        key="milestones",
        prompt="Let's break it into 3-6 checkable steps. What is the first one?",
        why="The trackable unit. Each should be one session's worth of work.",
        multi=True,
    ),
    InterviewQuestion(
        key="target_date",
        prompt="Is there a real deadline, or a date you want this done by? (optional)",
        why="Enables the at-risk verdict. Leave blank rather than inventing one.",
        required=False,
    ),
    InterviewQuestion(
        key="resources",
        prompt="Any high-trust sources you already know you want to work from?",
        why="Never trust parametric knowledge — lessons should cite primary sources.",
        multi=True,
        required=False,
    ),
)


def interview_spec() -> list[dict]:
    """Return the interview as plain dicts (for the API and MCP tools)."""
    return [
        {
            "key": q.key,
            "prompt": q.prompt,
            "why": q.why,
            "required": q.required,
            "multi": q.multi,
        }
        for q in INTERVIEW
    ]


def seed_from_history(*, days: int = 30, limit: int = 8) -> dict:
    """Suggest plan material from what the databases already know.

    Reads both table families in ``sessions.db``: struggle/confidence rows from
    the StudyLoop tables, and recurring question topics from the session
    archive.  Every reader is guarded — a fresh install returns empty lists and
    a note, not an error.
    """
    suggestions: dict = {
        "struggling_topics": [],
        "due_concepts": [],
        "recurring_questions": [],
        "configured_topics": [],
        "notes": [],
    }

    try:
        from studyloop import history
    except Exception:
        suggestions["notes"].append("history package unavailable — no seed data")
        return suggestions

    try:
        suggestions["struggling_topics"] = [
            {"topic": row.get("topic", ""), "last_seen": row.get("last_seen", "")}
            for row in history.progress.get_struggling_topics(days=days)[:limit]
            if is_usable_concept(row.get("topic"))
        ]
    except Exception:
        suggestions["notes"].append("struggle signal unavailable")

    try:
        from studyloop.topics import get_topics

        topics = get_topics()
        suggestions["configured_topics"] = [t.name for t in topics][:limit]
        keyword_map = {t.name: [t.name, *t.tags] for t in topics}
    except Exception:
        keyword_map = {}
        suggestions["notes"].append("configured topics unavailable")

    if keyword_map:
        try:
            # The due-concepts rows are where the worst debris arrived: a
            # truncated path (`study-notes/introd`), a single character (`x`),
            # and a row whose topic and concept disagreed. An agent handed a
            # concept called `x` either invents a meaning for it or burns a turn
            # asking what it is, so reject before it ever reaches the brief.
            suggestions["due_concepts"] = [
                {
                    "topic": row.get("topic", ""),
                    "concept": row.get("concept") or "",
                    "review_type": row.get("review_type", ""),
                }
                for row in history.spaced_repetition_due(keyword_map)[:limit]
                if is_usable_concept(row.get("concept") or row.get("topic"))
            ]
        except Exception:
            suggestions["notes"].append("spaced-repetition data unavailable")

    try:
        suggestions["recurring_questions"] = [
            {"topic": row.get("topic", ""), "mentions": row.get("mentions", 0)}
            for row in history.struggle_topics(days=days, min_sessions=2)[:limit]
        ]
    except Exception:
        suggestions["notes"].append("session archive unavailable")

    return suggestions


def _as_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        parts = [p.strip() for p in value.replace("\n", ",").split(",")]
        return [p for p in parts if p]
    return [str(v).strip() for v in value if str(v).strip()]


def _parse_milestone_answer(answer) -> Milestone:
    """Accept either ``"Title (concepts: a, b)"`` or a dict from the API."""
    if isinstance(answer, dict):
        return Milestone(
            title=str(answer.get("title", "")).strip() or "Untitled milestone",
            done=bool(answer.get("done", False)),
            concepts=_as_list(answer.get("concepts")),
            notes=str(answer.get("notes", "")).strip(),
        )
    from .markdown import _parse_milestone_line

    return _parse_milestone_line(str(answer), done=False)


def draft_plan(
    title: str,
    answers: dict,
    *,
    plan_id: str = "",
    status: str = "draft",
) -> StudyPlan:
    """Build a :class:`StudyPlan` from interview ``answers``.

    Missing optional answers are simply absent from the document — the renderer
    writes an explicit "not yet captured" placeholder so the gap is visible in
    the UI rather than silently looking complete.
    """
    mission = Mission(
        why=str(answers.get("why", "")).strip(),
        success=_as_list(answers.get("success")),
        constraints=_as_list(answers.get("constraints")),
        out_of_scope=_as_list(answers.get("out_of_scope")),
    )

    milestones = [_parse_milestone_answer(item) for item in (answers.get("milestones") or [])]

    resources: list[Resource] = []
    for item in answers.get("resources") or []:
        if isinstance(item, dict):
            resources.append(
                Resource(
                    label=str(item.get("label", "")).strip() or str(item.get("url", "")).strip(),
                    url=str(item.get("url", "")).strip(),
                    note=str(item.get("note", "")).strip(),
                )
            )
        else:
            text = str(item).strip()
            if text.startswith("http"):
                resources.append(Resource(label=text, url=text))
            elif text:
                resources.append(Resource(label=text))

    energy_floor = answers.get("energy_floor", 3)
    try:
        energy_floor = max(1, min(10, int(energy_floor)))
    except (TypeError, ValueError):
        energy_floor = 3

    cadence = answers.get("review_cadence_days", 3)
    try:
        cadence = max(1, min(90, int(cadence)))
    except (TypeError, ValueError):
        cadence = 3

    now = utc_now_iso()
    return StudyPlan(
        plan_id=plan_id or slugify(title),
        title=title.strip() or "Untitled plan",
        status=status,
        created=now,
        updated=now,
        topics=_as_list(answers.get("topics")),
        energy_floor=energy_floor,
        target_date=str(answers.get("target_date", "")).strip(),
        review_cadence_days=cadence,
        mission=mission,
        milestones=milestones,
        resources=resources,
        notes=str(answers.get("notes", "")).strip(),
    )


def readiness(plan: StudyPlan) -> dict:
    """Report what still blocks a draft from becoming an active plan.

    Used by the agent to know whether to keep interviewing, and by the API to
    refuse a premature activation with a reason rather than a bare 400.
    """
    blockers: list[str] = []
    nudges: list[str] = []

    if not plan.mission.why.strip():
        blockers.append("Mission 'why' is empty — interview the learner first.")
    if not plan.mission.success:
        blockers.append("No observable success criteria.")
    if not plan.milestones:
        blockers.append("No milestones — the plan cannot be evaluated.")
    elif len(plan.milestones) > 8:
        nudges.append(f"{len(plan.milestones)} milestones is a lot; consider splitting the plan.")

    if not plan.topics:
        nudges.append("No topics set — spaced repetition cannot match this plan.")
    if not any(m.concepts for m in plan.milestones):
        nudges.append("No milestone names concepts — confidence evidence cannot be joined.")
    if not plan.mission.out_of_scope:
        nudges.append("Nothing marked out of scope — tangents will be hard to refuse.")
    if not plan.resources:
        nudges.append("No primary sources captured yet.")

    return {
        "plan_id": plan.plan_id,
        "ready": not blockers,
        "blockers": blockers,
        "nudges": nudges,
    }
