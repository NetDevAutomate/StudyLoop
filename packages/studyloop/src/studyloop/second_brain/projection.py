"""Pure renderers for the notes StudyLoop publishes into a vault.

Every function here is a total function of its arguments: no clock, no
filesystem, no settings, no subprocess. That is the design decision the writer
depends on, not a stylistic preference.

Idempotence is achieved by comparing a rendered body against the hash recorded in
the file already on disk. A timestamp, a hostname or a "generated at" line in the
output would make that comparison always differ, so every publish would rewrite
every note, every day — which in an Obsidian vault means a sync conflict and a
changed mtime for a file whose content did not change.

Three projections:

* the plan — the same sections as the plan document, in the same order, so a
  learner reading it in their vault is reading the shape they authored;
* Today — one next action, a few alternates, what is due, what is in focus;
* one note per learning record — regenerated from the plan, never appended to.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

import yaml

from studyloop.planning import MISSION_SUBSECTION_HEADINGS, PLAN_SECTION_HEADINGS

if TYPE_CHECKING:
    from studyloop.planning.models import LearningRecord, StudyPlan

#: The frontmatter key that marks a file as StudyLoop's to regenerate.
#:
#: Its presence is the mechanical form of "never overwrite the learner's own
#: notes": a file without it is refused, so the rule is a check rather than a
#: convention someone has to remember.
OWNERSHIP_KEY = "studyloop"

#: Bumped when the marker's shape changes, so a future version can recognise —
#: and refuse, or migrate — a projection written by an older one.
OWNERSHIP_SCHEMA = 1

ProjectionKind = Literal["plan-projection", "today-projection", "learning-record-projection"]

#: Plan-level frontmatter keys the projection writes.
#:
#: Named as a constant because the packaged Dataview snippet queries them: a key
#: renamed here silently empties the learner's "due reviews" table, so the
#: template guard compares the snippet's keys against this tuple.
PROJECTED_PLAN_KEYS: tuple[str, ...] = (
    "title",
    "status",
    "progress_pct",
    "target_date",
    "review_cadence_days",
    "topics",
    "updated",
)

#: ``Today.md``'s own sections. Three, and no more: the whole point of the note
#: is that it can be read at a glance before deciding to sit down.
TODAY_SECTION_HEADINGS: tuple[str, ...] = ("Next action", "Due reviews", "Active topics")

#: Heading for the wikilinks section, when backlinks are enabled and match.
#: Not part of PLAN_SECTION_HEADINGS: it is StudyLoop's addition to the projection,
#: not a section of the plan document, and the template guard compares those.
RELATED_HEADING = "Related notes"

#: Bounds on Today. Chosen so the note stays a decision aid rather than a backlog:
#: an unbounded due list is the thing a learner avoids looking at.
MAX_TODAY_ALTERNATES = 3
MAX_DUE_CARDS = 20
MAX_FOCUS_TOPICS = 10

_HASH_PLACEHOLDER = "0" * 64


@dataclass(frozen=True)
class ProjectionIdentity:
    """Who a projection belongs to, recorded in its ownership marker.

    Identity is checked before a rewrite: a file marked as the projection of a
    different plan is refused rather than replaced, so a learner who renamed a
    plan does not lose the note under the old name.
    """

    kind: ProjectionKind
    plan_id: str | None
    learning_record: int | None
    #: Where the content came from, as a portable label. Deliberately not an
    #: absolute path: this string is written into a file that may be synced to a
    #: phone, and it would otherwise carry the machine's home directory with it.
    source: str


@dataclass(frozen=True)
class TodayData:
    """Everything ``Today.md`` renders, gathered by the backend.

    A plain value object so the renderer stays pure: the backend does the
    querying (decision engine, review database, focus filter), the renderer only
    formats.
    """

    primary: str
    primary_reason: str
    primary_minutes: int
    alternates: tuple[str, ...] = ()
    due_cards: tuple[dict[str, Any], ...] = ()
    focus_topics: tuple[str, ...] = ()


def content_hash_of(rendered: str) -> str:
    """The hash a rendered projection records in its own marker.

    Computed over the document with the hash field blanked out, because a hash
    cannot cover itself. Blanking rather than removing keeps the byte layout
    identical, so the same function works on a file read back from disk.
    """
    return hashlib.sha256(_blank_hash(rendered).encode("utf-8")).hexdigest()


def _blank_hash(rendered: str) -> str:
    marker_line = "  content_hash: "
    out = []
    for line in rendered.splitlines(keepends=True):
        if line.startswith(marker_line):
            out.append(f"{marker_line}{_HASH_PLACEHOLDER}\n")
        else:
            out.append(line)
    return "".join(out)


def _progress_pct(plan: StudyPlan) -> int:
    """Percentage of milestones done, or 0 when there are none.

    Derived rather than stored: ``StudyPlan`` has no progress field, and adding
    one would create a second number that can disagree with the milestones it is
    supposed to summarise.
    """
    if not plan.milestones:
        return 0
    done = sum(1 for milestone in plan.milestones if milestone.done)
    return round(done * 100 / len(plan.milestones))


def _render_frontmatter(fields: dict[str, Any], identity: ProjectionIdentity) -> str:
    """Frontmatter plus the ownership marker, with a placeholder hash."""
    marker = {
        "owned": True,
        "schema": OWNERSHIP_SCHEMA,
        "kind": identity.kind,
        "plan_id": identity.plan_id,
        "learning_record": identity.learning_record,
        "source": identity.source,
        "content_hash": _HASH_PLACEHOLDER,
    }
    body = yaml.dump(
        {**fields, OWNERSHIP_KEY: marker},
        default_flow_style=False,
        sort_keys=False,
        allow_unicode=True,
    )
    return f"---\n{body}---\n"


def _finalise(document: str) -> str:
    """Stamp the real content hash into a rendered document."""
    digest = content_hash_of(document)
    return _blank_hash(document).replace(
        f"  content_hash: {_HASH_PLACEHOLDER}", f"  content_hash: {digest}", 1
    )


def _bullets(items: list[str], *, empty: str) -> list[str]:
    if not items:
        return [f"_{empty}_", ""]
    return [f"- {item}" for item in items] + [""]


def render_plan_projection(
    plan: StudyPlan,
    identity: ProjectionIdentity,
    *,
    backlinks: tuple[str, ...] = (),
) -> str:
    """Render a plan as the note StudyLoop owns inside the vault.

    Section order comes from :data:`PLAN_SECTION_HEADINGS`, the same constant the
    plan document and the vault template use, so all three cannot drift apart.

    ``backlinks`` are rendered HERE rather than appended by the caller. Appending
    them to a finished document left the recorded ``content_hash`` covering only the
    part before the footer, so for the commonest note kind the marker did not mean
    what its name says. The hash is stamped by :func:`_finalise` at the end of this
    function, so anything that must be covered by it has to pass through here.
    """
    frontmatter = {
        "title": plan.title,
        "status": plan.status,
        "progress_pct": _progress_pct(plan),
        "target_date": plan.target_date,
        "review_cadence_days": plan.review_cadence_days,
        "topics": list(plan.topics),
        "updated": plan.updated,
    }
    out: list[str] = [_render_frontmatter(frontmatter, identity)]
    out.append(f"# {plan.title}\n")

    out.append(f"## {PLAN_SECTION_HEADINGS[0]}\n")
    out.append(f"### {MISSION_SUBSECTION_HEADINGS[0]}\n")
    out.append(f"{plan.mission.why or '_Not captured yet._'}\n")
    out.append(f"### {MISSION_SUBSECTION_HEADINGS[1]}\n")
    out.append("\n".join(_bullets(plan.mission.success, empty="Nothing captured yet.")))
    out.append(f"### {MISSION_SUBSECTION_HEADINGS[2]}\n")
    out.append("\n".join(_bullets(plan.mission.constraints, empty="None recorded.")))
    out.append(f"### {MISSION_SUBSECTION_HEADINGS[3]}\n")
    out.append("\n".join(_bullets(plan.mission.out_of_scope, empty="Nothing excluded.")))

    out.append(f"## {PLAN_SECTION_HEADINGS[1]}\n")
    if plan.milestones:
        for milestone in plan.milestones:
            box = "x" if milestone.done else " "
            line = f"- [{box}] **{milestone.title}**"
            if milestone.notes:
                line += f" — {milestone.notes}"
            if milestone.concepts:
                line += f" `(concepts: {', '.join(milestone.concepts)})`"
            out.append(line)
        out.append("")
    else:
        out.append("_No milestones yet._\n")

    out.append(f"## {PLAN_SECTION_HEADINGS[2]}\n")
    if plan.learning_records:
        for record in plan.learning_records:
            out.append(f"### LR-{record.number:04d} — {record.title}\n")
            out.append(f"{record.body or '_No detail recorded._'}\n")
    else:
        out.append("_No learning records yet._\n")

    out.append(f"## {PLAN_SECTION_HEADINGS[3]}\n")
    if plan.resources:
        for resource in plan.resources:
            line = (
                f"- [{resource.label}]({resource.url})" if resource.url else f"- {resource.label}"
            )
            if resource.note:
                line += f" — {resource.note}"
            out.append(line)
        out.append("")
    else:
        out.append("_No resources gathered yet._\n")

    out.append(f"## {PLAN_SECTION_HEADINGS[4]}\n")
    out.append("| When | Phase | Verdict | Summary |")
    out.append("| --- | --- | --- | --- |")
    for checkpoint in plan.checkpoints:
        summary = checkpoint.summary.replace("|", "\\|").replace("\n", " ").strip()
        out.append(f"| {checkpoint.at} | {checkpoint.phase} | {checkpoint.verdict} | {summary} |")
    out.append("")

    out.append(f"## {PLAN_SECTION_HEADINGS[5]}\n")
    out.append(f"{plan.notes or '_No notes._'}\n")

    if backlinks:
        out.append(f"## {RELATED_HEADING}\n")
        out.extend(f"- {link}" for link in backlinks)
        out.append("")

    return _finalise("\n".join(out))


def render_today(data: TodayData, identity: ProjectionIdentity) -> str:
    """Render ``Today.md``: one action, a few alternates, what is due.

    Every list is bounded (see the ``MAX_*`` constants). The note replaces its
    predecessor rather than accumulating, which is why the renderer never sees
    the previous day's content at all.
    """
    out: list[str] = [
        _render_frontmatter({"title": "Today"}, identity),
        "# Today\n",
        f"## {TODAY_SECTION_HEADINGS[0]}\n",
    ]
    if data.primary:
        out.append(f"- **{data.primary}** — {data.primary_minutes} min")
        if data.primary_reason:
            out.append(f"  - {data.primary_reason}")
        out.append("")
    else:
        out.append("_Nothing scheduled. Pick something you are curious about._\n")

    if data.alternates:
        out.append("Alternatives:\n")
        out.extend(f"- {item}" for item in data.alternates[:MAX_TODAY_ALTERNATES])
        out.append("")

    out.append(f"## {TODAY_SECTION_HEADINGS[1]}\n")
    if data.due_cards:
        for card in data.due_cards[:MAX_DUE_CARDS]:
            course = card.get("course", "")
            card_hash = card.get("card_hash", "")
            due = card.get("next_review", "")
            out.append(f"- [ ] {course} `{card_hash}` (due {due})")
        out.append("")
    else:
        out.append("_Nothing due today._\n")

    out.append(f"## {TODAY_SECTION_HEADINGS[2]}\n")
    if data.focus_topics:
        out.extend(f"- {topic}" for topic in data.focus_topics[:MAX_FOCUS_TOPICS])
        out.append("")
    else:
        out.append("_No focus topics set._\n")

    return _finalise("\n".join(out))


def render_learning_record_projection(
    plan: StudyPlan, record: LearningRecord, identity: ProjectionIdentity
) -> str:
    """Render one learning record as its own note.

    Regenerated from the plan on every publish, never appended to: the plan
    document is the record's home, and a note that accumulated edits would become
    a second, diverging copy of something the learner already owns elsewhere.
    """
    frontmatter = {
        "title": f"LR-{record.number:04d} — {record.title}",
        "plan": plan.title,
        "status": record.status,
        "updated": plan.updated,
    }
    out = [
        _render_frontmatter(frontmatter, identity),
        f"# LR-{record.number:04d} — {record.title}\n",
        f"{record.body or '_No detail recorded._'}\n",
        f"Part of **{plan.title}**.\n",
    ]
    return _finalise("\n".join(out))


__all__ = [
    "MAX_DUE_CARDS",
    "MAX_FOCUS_TOPICS",
    "MAX_TODAY_ALTERNATES",
    "OWNERSHIP_KEY",
    "OWNERSHIP_SCHEMA",
    "PROJECTED_PLAN_KEYS",
    "RELATED_HEADING",
    "TODAY_SECTION_HEADINGS",
    "ProjectionIdentity",
    "ProjectionKind",
    "TodayData",
    "content_hash_of",
    "render_learning_record_projection",
    "render_plan_projection",
    "render_today",
]
