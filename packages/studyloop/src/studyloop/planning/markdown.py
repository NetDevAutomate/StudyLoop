"""Structured Markdown (de)serialisation for study plans.

The Markdown document is the source of truth, so the contract that matters is
**round-trip fidelity**: ``parse_plan(render_plan(plan)) == plan`` for every
field this module knows about.  Anything the parser does not recognise is
preserved in :attr:`StudyPlan.notes` rather than silently dropped.

Canonical document shape::

    ---
    id: python-decorators
    title: Master Python Decorators
    status: active
    ...
    ---

    # Master Python Decorators

    ## Mission
    ### Why
    ### Success looks like
    ### Constraints
    ### Out of scope

    ## Milestones
    - [x] **Closures** — cell variables `(concepts: closures, cell-vars)`

    ## Learning Records
    ### LR-0001 — Closures clicked

    ## Resources
    - [PEP 318](https://peps.python.org/pep-0318/) — primary source

    ## Checkpoints
    | When | Phase | Verdict | Summary |

    ## Notes
"""

from __future__ import annotations

import re
from datetime import date, datetime

from .models import (
    Checkpoint,
    LearningRecord,
    Milestone,
    Mission,
    Resource,
    StudyPlan,
    slugify,
    utc_now_iso,
)

_FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?", re.DOTALL)
_CHECKBOX_RE = re.compile(r"^[-*]\s+\[( |x|X)\]\s*(.*)$")
_CONCEPTS_RE = re.compile(r"[`(]?\(?concepts:\s*([^)`]*)\)?[`)]?\s*$", re.IGNORECASE)
_BULLET_RE = re.compile(r"^[-*]\s+(.*)$")
_LINK_RE = re.compile(r"^\[([^\]]*)\]\(([^)]*)\)\s*(?:[—-]\s*(.*))?$")
_LR_HEADING_RE = re.compile(r"^LR-(\d+)\s*(?:[—-]\s*(.*))?$", re.IGNORECASE)
_BOLD_RE = re.compile(r"\*\*(.*?)\*\*")

#: The plan document's ``##`` sections, in the order ``render_plan`` emits them.
#:
#: One source of truth for three artefacts that must agree: this renderer, the
#: Obsidian projection of a plan, and the vault template a learner writes notes
#: from. Three copies drift, and the drift is invisible — a template whose
#: sections no longer match the document still looks perfectly fine on its own.
#: ``tests/test_second_brain_templates.py`` is the guard.
PLAN_SECTION_HEADINGS: tuple[str, ...] = (
    "Mission",
    "Milestones",
    "Learning Records",
    "Resources",
    "Checkpoints",
    "Notes",
)

#: The ``###`` sections nested under Mission, in render order.
MISSION_SUBSECTION_HEADINGS: tuple[str, ...] = (
    "Why",
    "Success looks like",
    "Constraints",
    "Out of scope",
)

#: Headings the parser understands at ``##`` level, normalised to lower case.
#:
#: Derived, not written out again: a section the renderer emits but the parser
#: does not recognise is silently swept into ``StudyPlan.notes`` on the next
#: round trip, losing structure with no error anywhere.
_KNOWN_SECTIONS = {heading.lower() for heading in PLAN_SECTION_HEADINGS}

# Placeholders written for empty sections so a gap is *visible* in the rendered
# document rather than looking complete. They are defined once and consumed by
# both the renderer and the parser: if the parser did not strip them, an empty
# mission would round-trip into prose that reads as populated, and the readiness
# check would report a plan as ready when it is not.
PLACEHOLDER_WHY = "_Not yet captured — the agent should interview for this._"
PLACEHOLDER_SUCCESS = "No success criteria captured yet."
PLACEHOLDER_CONSTRAINTS = "None recorded."
PLACEHOLDER_OUT_OF_SCOPE = "Nothing explicitly excluded."
PLACEHOLDER_MILESTONES = "_No milestones yet._"
PLACEHOLDER_LEARNING_RECORDS = "_No learning records yet._"
PLACEHOLDER_RECORD_BODY = "_No detail recorded._"
PLACEHOLDER_RESOURCES = "_No resources gathered yet._"
PLACEHOLDER_NOTES = "_No notes._"

#: Every placeholder the parser must read back as "absent".
_PLACEHOLDERS = frozenset(
    {
        PLACEHOLDER_WHY,
        PLACEHOLDER_MILESTONES,
        PLACEHOLDER_LEARNING_RECORDS,
        PLACEHOLDER_RECORD_BODY,
        PLACEHOLDER_RESOURCES,
        PLACEHOLDER_NOTES,
        f"_{PLACEHOLDER_SUCCESS}_",
        f"_{PLACEHOLDER_CONSTRAINTS}_",
        f"_{PLACEHOLDER_OUT_OF_SCOPE}_",
    }
)


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def _load_frontmatter(text: str) -> tuple[dict, str]:
    """Split YAML frontmatter from the body. Returns ``(metadata, body)``."""
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return {}, text
    raw = match.group(1)
    body = text[match.end() :]
    try:
        import yaml

        loaded = yaml.safe_load(raw)
    except Exception:
        loaded = None
    if not isinstance(loaded, dict):
        loaded = _naive_frontmatter(raw)
    return loaded, body


def _naive_frontmatter(raw: str) -> dict:
    """Minimal ``key: value`` / ``- item`` fallback when YAML is unavailable."""
    data: dict = {}
    current_list_key: str | None = None
    for line in raw.splitlines():
        if not line.strip():
            continue
        if line.lstrip().startswith("- ") and current_list_key:
            data[current_list_key].append(line.lstrip()[2:].strip())
            continue
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()
        if value:
            data[key] = value
            current_list_key = None
        else:
            data[key] = []
            current_list_key = key
    return data


def _split_sections(body: str) -> tuple[str, dict[str, list[str]], list[str]]:
    """Split the body into ``(h1_title, {h2_lower: lines}, unknown_lines)``.

    Sub-headings (``###``) stay inside their parent ``##`` block so the mission
    and learning-record parsers can walk them.
    """
    title = ""
    sections: dict[str, list[str]] = {}
    unknown: list[str] = []
    current: list[str] | None = None
    in_fence = False

    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
        if not in_fence and stripped.startswith("# ") and not title:
            title = stripped[2:].strip()
            current = None
            continue
        if not in_fence and stripped.startswith("## "):
            heading = stripped[3:].strip().lower()
            if heading in _KNOWN_SECTIONS:
                current = sections.setdefault(heading, [])
            else:
                # Unrecognised section — keep verbatim so nothing is lost.
                unknown.append(line)
                current = unknown
            continue
        if current is None:
            if stripped:
                unknown.append(line)
            continue
        current.append(line)

    return title, sections, unknown


def _subsection_items(lines: list[str]) -> list[tuple[str, list[str]]]:
    """Group ``###`` blocks, preserving each heading's original case.

    Learning-record titles live in the heading text, so lower-casing the key
    (as :func:`_subsections` does for fixed-label lookups) would destroy the
    title on every save.
    """
    out: list[tuple[str, list[str]]] = []
    current: list[str] | None = None
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("### "):
            current = []
            out.append((stripped[4:].strip(), current))
            continue
        if current is not None:
            current.append(line)
    return out


def _subsections(lines: list[str]) -> dict[str, list[str]]:
    """Group ``###`` blocks within a section, keyed by lower-cased heading.

    For fixed-label lookups only (mission sub-headings). Use
    :func:`_subsection_items` when the heading text itself is data.
    """
    return {heading.lower(): block for heading, block in _subsection_items(lines)}


def _bullets(lines: list[str]) -> list[str]:
    """Extract plain bullet text (ignoring checkbox bullets)."""
    items: list[str] = []
    for line in lines:
        stripped = line.strip()
        if _CHECKBOX_RE.match(stripped):
            continue
        match = _BULLET_RE.match(stripped)
        if match:
            items.append(match.group(1).strip())
    return items


def _prose(lines: list[str]) -> str:
    """Join lines into a paragraph block, reading placeholders back as empty."""
    text = "\n".join(lines).strip()
    if text in _PLACEHOLDERS:
        return ""
    return text


def _parse_mission(lines: list[str]) -> Mission:
    subs = _subsections(lines)
    return Mission(
        why=_prose(subs.get("why", [])),
        success=_bullets(subs.get("success looks like", subs.get("success", []))),
        constraints=_bullets(subs.get("constraints", [])),
        out_of_scope=_bullets(subs.get("out of scope", [])),
    )


def _parse_milestone_line(text: str, *, done: bool) -> Milestone:
    """Parse the text after a ``- [ ]`` checkbox into a Milestone."""
    concepts: list[str] = []
    match = _CONCEPTS_RE.search(text)
    if match:
        concepts = [c.strip() for c in match.group(1).split(",") if c.strip()]
        text = text[: match.start()].strip()
    text = text.strip().rstrip("`").strip()

    title, notes = text, ""
    # Accept em dash, en dash, and '--': learners hand-edit these documents and
    # editors/keyboards produce all three. RUF001 flags the en dash as ambiguous,
    # which is precisely why it is listed — it must still parse.
    for sep in (" — ", " – ", " -- "):  # noqa: RUF001
        if sep in text:
            title, _, notes = text.partition(sep)
            break
    title = _BOLD_RE.sub(r"\1", title).strip()
    return Milestone(title=title, done=done, concepts=concepts, notes=notes.strip())


def _parse_milestones(lines: list[str]) -> list[Milestone]:
    out: list[Milestone] = []
    for line in lines:
        match = _CHECKBOX_RE.match(line.strip())
        if not match:
            continue
        done = match.group(1).lower() == "x"
        out.append(_parse_milestone_line(match.group(2), done=done))
    return out


def _parse_learning_records(lines: list[str]) -> list[LearningRecord]:
    out: list[LearningRecord] = []
    # Case-preserving: the heading text carries the record's title.
    for heading, block in _subsection_items(lines):
        match = _LR_HEADING_RE.match(heading.strip())
        # `Status:` is rendered as its own line above the body. Lift it out
        # here, otherwise it lands in the body and is duplicated on re-render.
        status = "active"
        body_lines: list[str] = []
        for line in block:
            if line.strip().lower().startswith("status:"):
                status = line.split(":", 1)[1].strip() or "active"
                continue
            body_lines.append(line)
        body = _prose(body_lines)
        if match:
            number = int(match.group(1))
            title = (match.group(2) or "").strip()
        else:
            number = len(out) + 1
            title = heading.strip()
        out.append(LearningRecord(number=number, title=title, body=body, status=status))
    return sorted(out, key=lambda r: r.number)


def _parse_resources(lines: list[str]) -> list[Resource]:
    out: list[Resource] = []
    for item in _bullets(lines):
        match = _LINK_RE.match(item)
        if match:
            out.append(
                Resource(
                    label=match.group(1).strip(),
                    url=match.group(2).strip(),
                    note=(match.group(3) or "").strip(),
                )
            )
        else:
            out.append(Resource(label=item, url="", note=""))
    return out


def _split_table_row(row: str) -> list[str]:
    """Split a Markdown table row on *unescaped* pipes only.

    The renderer escapes a literal ``|`` inside a cell as ``\\|`` so it cannot be
    read as a column separator. Splitting on a bare ``|`` would then tear that
    cell in two and shift every later column — silently corrupting the
    checkpoint's summary and study_id on the next save.
    """
    cells = re.split(r"(?<!\\)\|", row.strip().strip("|"))
    return [cell.strip().replace("\\|", "|") for cell in cells]


def _parse_checkpoints(lines: list[str]) -> list[Checkpoint]:
    out: list[Checkpoint] = []
    for line in lines:
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cells = _split_table_row(stripped)
        if len(cells) < 4:
            continue
        when, phase, verdict = cells[0], cells[1].lower(), cells[2]
        if phase not in {"start", "mid", "end"}:
            continue  # header or separator row
        summary = cells[3]
        study_id = cells[4] if len(cells) > 4 else ""
        out.append(
            Checkpoint(
                phase=phase,
                verdict=verdict,
                at=when,
                summary=summary,
                study_id=study_id,
            )
        )
    return out


def _as_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [v.strip() for v in value.strip("[]").split(",") if v.strip()]
    if isinstance(value, (list, tuple)):
        return [str(v).strip() for v in value if str(v).strip()]
    return [str(value)]


def _as_int(value, default: int) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def _as_scalar_str(value) -> str:
    """Stringify a frontmatter scalar without losing ISO-8601 shape.

    ``yaml.safe_load`` eagerly coerces ``2026-08-03T21:53:37+00:00`` into a
    ``datetime``, whose ``str()`` uses a space separator — which would break
    round-trip fidelity on every save.  Dates and datetimes are therefore
    re-serialised with ``isoformat()`` rather than ``str()``.
    """
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value).strip()


def parse_plan(text: str, *, plan_id: str = "") -> StudyPlan:
    """Parse a structured Markdown document into a :class:`StudyPlan`.

    ``plan_id`` is used only when the frontmatter omits ``id`` — callers pass
    the filename stem so a hand-written plan without an id still loads.
    """
    meta, body = _load_frontmatter(text)
    title_from_body, sections, unknown = _split_sections(body)

    title = str(meta.get("title") or title_from_body or "Untitled plan").strip()
    resolved_id = str(meta.get("id") or plan_id or slugify(title)).strip()
    status = str(meta.get("status") or "draft").strip().lower()
    if status not in {"draft", "active", "paused", "complete", "abandoned"}:
        status = "draft"

    notes_lines = sections.get("notes", [])
    notes = _prose(notes_lines)
    if unknown:
        leftover = _prose(unknown)
        notes = f"{notes}\n\n{leftover}".strip() if notes else leftover

    return StudyPlan(
        plan_id=resolved_id,
        title=title,
        status=status,
        created=_as_scalar_str(meta.get("created")) or utc_now_iso(),
        updated=_as_scalar_str(meta.get("updated")) or utc_now_iso(),
        topics=_as_list(meta.get("topics")),
        energy_floor=_as_int(meta.get("energy_floor"), 3),
        target_date=_as_scalar_str(meta.get("target_date")),
        review_cadence_days=_as_int(meta.get("review_cadence_days"), 3),
        mission=_parse_mission(sections.get("mission", [])),
        milestones=_parse_milestones(sections.get("milestones", [])),
        learning_records=_parse_learning_records(sections.get("learning records", [])),
        resources=_parse_resources(sections.get("resources", [])),
        checkpoints=_parse_checkpoints(sections.get("checkpoints", [])),
        notes=notes,
    )


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _render_frontmatter(plan: StudyPlan) -> list[str]:
    lines = [
        "---",
        f"id: {plan.plan_id}",
        f"title: {plan.title}",
        f"status: {plan.status}",
        f"created: {plan.created}",
        f"updated: {plan.updated}",
    ]
    if plan.topics:
        lines.append("topics:")
        lines.extend(f"  - {topic}" for topic in plan.topics)
    else:
        lines.append("topics: []")
    lines.append(f"energy_floor: {plan.energy_floor}")
    lines.append(f"target_date: {plan.target_date}")
    lines.append(f"review_cadence_days: {plan.review_cadence_days}")
    lines.append("---")
    return lines


def _render_bullets(items: list[str], *, empty: str) -> list[str]:
    if not items:
        return [f"_{empty}_", ""]
    return [f"- {item}" for item in items] + [""]


def render_milestone(milestone: Milestone) -> str:
    """Render one milestone as a GitHub-flavoured task-list item."""
    box = "x" if milestone.done else " "
    text = f"**{milestone.title}**"
    if milestone.notes:
        text += f" — {milestone.notes}"
    if milestone.concepts:
        text += f" `(concepts: {', '.join(milestone.concepts)})`"
    return f"- [{box}] {text}"


def _h2(index: int) -> str:
    """Render one ``##`` heading from :data:`PLAN_SECTION_HEADINGS`.

    Indexed rather than named so the renderer cannot emit a heading that is not
    in the constant, which is what keeps the parser's derived
    ``_KNOWN_SECTIONS`` and this output in step.
    """
    return f"## {PLAN_SECTION_HEADINGS[index]}"


def _h3(index: int) -> str:
    """Render one ``###`` heading from :data:`MISSION_SUBSECTION_HEADINGS`."""
    return f"### {MISSION_SUBSECTION_HEADINGS[index]}"


def render_plan(plan: StudyPlan) -> str:
    """Render a :class:`StudyPlan` as its canonical Markdown document."""
    out: list[str] = []
    out.extend(_render_frontmatter(plan))
    out.append("")
    out.append(f"# {plan.title}")
    out.append("")

    out.append(_h2(0))
    out.append("")
    out.append(_h3(0))
    out.append("")
    out.append(plan.mission.why or PLACEHOLDER_WHY)
    out.append("")
    out.append(_h3(1))
    out.append("")
    out.extend(_render_bullets(plan.mission.success, empty=PLACEHOLDER_SUCCESS))
    out.append(_h3(2))
    out.append("")
    out.extend(_render_bullets(plan.mission.constraints, empty=PLACEHOLDER_CONSTRAINTS))
    out.append(_h3(3))
    out.append("")
    out.extend(_render_bullets(plan.mission.out_of_scope, empty=PLACEHOLDER_OUT_OF_SCOPE))

    out.append(_h2(1))
    out.append("")
    if plan.milestones:
        out.extend(render_milestone(m) for m in plan.milestones)
    else:
        out.append(PLACEHOLDER_MILESTONES)
    out.append("")

    out.append(_h2(2))
    out.append("")
    if plan.learning_records:
        for record in plan.learning_records:
            out.append(f"### LR-{record.number:04d} — {record.title}")
            out.append("")
            if record.status and record.status != "active":
                out.append(f"Status: {record.status}")
                out.append("")
            out.append(record.body or PLACEHOLDER_RECORD_BODY)
            out.append("")
    else:
        out.append(PLACEHOLDER_LEARNING_RECORDS)
        out.append("")

    out.append(_h2(3))
    out.append("")
    if plan.resources:
        for resource in plan.resources:
            if resource.url:
                line = f"- [{resource.label}]({resource.url})"
            else:
                line = f"- {resource.label}"
            if resource.note:
                line += f" — {resource.note}"
            out.append(line)
    else:
        out.append(PLACEHOLDER_RESOURCES)
    out.append("")

    out.append(_h2(4))
    out.append("")
    out.append("| When | Phase | Verdict | Summary | Session |")
    out.append("| --- | --- | --- | --- | --- |")
    for checkpoint in plan.checkpoints:
        # A table cell is single-line: escape pipes (so they aren't read as
        # separators) and flatten newlines. _split_table_row unescapes on the
        # way back in, so the pipe survives the round trip.
        summary = checkpoint.summary.replace("|", "\\|").replace("\n", " ").strip()
        out.append(
            f"| {checkpoint.at} | {checkpoint.phase} | {checkpoint.verdict} "
            f"| {summary} | {checkpoint.study_id} |"
        )
    out.append("")

    out.append(_h2(5))
    out.append("")
    out.append(plan.notes or PLACEHOLDER_NOTES)
    out.append("")

    return "\n".join(out)
