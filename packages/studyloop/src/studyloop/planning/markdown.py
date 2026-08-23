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

import html
import re
from datetime import date, datetime

from .learning_map import render_learning_map
from .models import (
    Checkpoint,
    ConceptRef,
    ConceptRelation,
    DecisionRecord,
    EvidenceDisposition,
    EvidenceRef,
    Goal,
    LearningRecord,
    Milestone,
    Mission,
    PlanUnknown,
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

#: Headings the parser understands at ``##`` level, normalised to lower case.
_KNOWN_SECTIONS = {
    "mission",
    "goals",
    "learning map",
    "milestones",
    "evidence ledger",
    "concept mappings",
    "unknowns",
    "learning records",
    "resources",
    "checkpoints",
    "decisions",
    "notes",
}

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
PLACEHOLDER_GOALS = "_No goals yet._"
PLACEHOLDER_EVIDENCE = "_No evidence recorded yet._"
PLACEHOLDER_DISPOSITIONS = "_No evidence dispositions recorded yet._"
PLACEHOLDER_CONCEPTS = "_No concepts recorded yet._"
PLACEHOLDER_RELATIONS = "_No concept mappings recorded yet._"
PLACEHOLDER_UNKNOWNS = "_No unresolved unknowns._"
PLACEHOLDER_LEARNING_RECORDS = "_No learning records yet._"
PLACEHOLDER_RECORD_BODY = "_No detail recorded._"
PLACEHOLDER_RESOURCES = "_No resources gathered yet._"
PLACEHOLDER_DECISIONS = "_No decisions recorded yet._"
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
    table_rows = _parse_table(lines)
    if table_rows and "id" in table_rows[0]:
        out: list[Milestone] = []
        for row in table_rows:
            done = row.get("done", "").lower() in {"true", "yes", "x", "done"}
            milestone = _parse_milestone_line(row.get("milestone", ""), done=done)
            milestone.milestone_id = row.get("id", "")
            milestone.goal_id = row.get("goal id", "")
            out.append(milestone)
        return out

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


def _decode_cell(value: str) -> str:
    return html.unescape(value.strip())


def _parse_table(lines: list[str]) -> list[dict[str, str]]:
    rows = [_split_table_row(line) for line in lines if line.strip().startswith("|")]
    if len(rows) < 2:
        return []
    headers = [_decode_cell(cell).lower() for cell in rows[0]]
    out: list[dict[str, str]] = []
    for cells in rows[1:]:
        if cells and all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells):
            continue
        decoded = [_decode_cell(cell) for cell in cells]
        decoded.extend([""] * (len(headers) - len(decoded)))
        out.append(dict(zip(headers, decoded, strict=False)))
    return out


def _parse_goals(lines: list[str]) -> list[Goal]:
    return [
        Goal(
            goal_id=row.get("id", ""),
            title=row.get("title", ""),
            reason=row.get("reason", ""),
            alignment_rationale=row.get("alignment rationale", ""),
            status=row.get("status", "active") or "active",
        )
        for row in _parse_table(lines)
    ]


def _parse_evidence(lines: list[str]) -> tuple[list[EvidenceRef], list[EvidenceDisposition]]:
    subsections = _subsections(lines)
    evidence = [
        EvidenceRef(
            evidence_id=row.get("id", ""),
            source_kind=row.get("source kind", ""),
            source_native_id=row.get("source native id", ""),
            source_revision=row.get("source revision", ""),
            observed_at=row.get("observed at", ""),
            ingested_at=row.get("ingested at", ""),
            tier=_as_int(row.get("tier"), 4),
            claim_kind=row.get("claim kind", ""),
            subject_ref=row.get("subject ref", ""),
            provenance_digest=row.get("provenance digest", ""),
        )
        for row in _parse_table(subsections.get("evidence references", []))
    ]
    dispositions = [
        EvidenceDisposition(
            evidence_id=row.get("evidence id", ""),
            disposition=row.get("disposition", ""),
            reason=row.get("reason", ""),
        )
        for row in _parse_table(subsections.get("dispositions", []))
    ]
    return evidence, dispositions


def _parse_concept_mappings(
    lines: list[str],
) -> tuple[list[ConceptRef], list[ConceptRelation]]:
    subsections = _subsections(lines)
    concepts = [
        ConceptRef(
            concept_id=row.get("id", ""),
            display_label=row.get("display label", ""),
        )
        for row in _parse_table(subsections.get("concepts", []))
    ]
    relations = [
        ConceptRelation(
            source_ref=row.get("source ref", ""),
            target_ref=row.get("target ref", ""),
            relation=row.get("relation", ""),
            reason=row.get("reason", ""),
            decided_by=row.get("decided by", ""),
        )
        for row in _parse_table(subsections.get("relations", []))
    ]
    return concepts, relations


def _parse_unknowns(lines: list[str]) -> list[PlanUnknown]:
    return [
        PlanUnknown(
            unknown_id=row.get("id", ""),
            question=row.get("question", ""),
            impact=row.get("impact", ""),
            status=row.get("status", "open") or "open",
        )
        for row in _parse_table(lines)
    ]


def _parse_decisions(lines: list[str]) -> list[DecisionRecord]:
    return [
        DecisionRecord(
            decision_id=row.get("id", ""),
            proposal_id=row.get("proposal id", ""),
            outcome=row.get("outcome", ""),
            actor_kind=row.get("actor kind", ""),
            channel=row.get("channel", ""),
            reason=row.get("reason", ""),
            decided_at=row.get("decided at", ""),
        )
        for row in _parse_table(lines)
    ]


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

    evidence, dispositions = _parse_evidence(sections.get("evidence ledger", []))
    concepts, concept_relations = _parse_concept_mappings(sections.get("concept mappings", []))

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
        goals=_parse_goals(sections.get("goals", [])),
        milestones=_parse_milestones(sections.get("milestones", [])),
        evidence=evidence,
        evidence_dispositions=dispositions,
        concepts=concepts,
        concept_relations=concept_relations,
        unknowns=_parse_unknowns(sections.get("unknowns", [])),
        learning_records=_parse_learning_records(sections.get("learning records", [])),
        resources=_parse_resources(sections.get("resources", [])),
        checkpoints=_parse_checkpoints(sections.get("checkpoints", [])),
        decisions=_parse_decisions(sections.get("decisions", [])),
        notes=notes,
        schema_version=_as_int(meta.get("schema_version"), 1),
        document_revision=_as_int(meta.get("document_revision"), 1),
        structure_revision=_as_int(meta.get("structure_revision"), 1),
        document_digest=_as_scalar_str(meta.get("document_digest")),
        structure_digest=_as_scalar_str(meta.get("structure_digest")),
        brief_context_digest=_as_scalar_str(meta.get("brief_context_digest")),
    )


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _render_frontmatter(plan: StudyPlan) -> list[str]:
    lines = ["---"]
    if plan.schema_version >= 2:
        lines.extend(
            [
                f"schema_version: {plan.schema_version}",
                f"document_revision: {plan.document_revision}",
                f"structure_revision: {plan.structure_revision}",
                f"document_digest: {plan.document_digest}",
                f"structure_digest: {plan.structure_digest}",
                f"brief_context_digest: {plan.brief_context_digest}",
            ]
        )
    lines.extend(
        [
            f"id: {plan.plan_id}",
            f"title: {plan.title}",
            f"status: {plan.status}",
            f"created: {plan.created}",
            f"updated: {plan.updated}",
        ]
    )
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


def _encode_cell(value: object) -> str:
    escaped = html.escape(str(value), quote=True)
    return escaped.replace("|", "&#124;").replace("\n", "&#10;")


def _render_table(
    headers: list[str],
    rows: list[list[object]],
    *,
    empty: str,
) -> list[str]:
    if not rows:
        return [empty, ""]
    lines = [
        f"| {' | '.join(headers)} |",
        f"| {' | '.join('---' for _ in headers)} |",
    ]
    lines.extend(f"| {' | '.join(_encode_cell(cell) for cell in row)} |" for row in rows)
    lines.append("")
    return lines


def _render_goals(plan: StudyPlan) -> list[str]:
    return _render_table(
        ["ID", "Title", "Status", "Reason", "Alignment rationale"],
        [
            [goal.goal_id, goal.title, goal.status, goal.reason, goal.alignment_rationale]
            for goal in plan.goals
        ],
        empty=PLACEHOLDER_GOALS,
    )


def _render_v2_milestones(plan: StudyPlan) -> list[str]:
    return _render_table(
        ["ID", "Goal ID", "Done", "Milestone"],
        [
            [
                milestone.milestone_id,
                milestone.goal_id,
                str(milestone.done).lower(),
                render_milestone(milestone)[6:],
            ]
            for milestone in plan.milestones
        ],
        empty=PLACEHOLDER_MILESTONES,
    )


def _render_evidence_ledger(plan: StudyPlan) -> list[str]:
    lines = ["### Evidence references", ""]
    lines.extend(
        _render_table(
            [
                "ID",
                "Source kind",
                "Source native ID",
                "Source revision",
                "Observed at",
                "Ingested at",
                "Tier",
                "Claim kind",
                "Subject ref",
                "Provenance digest",
            ],
            [
                [
                    item.evidence_id,
                    item.source_kind,
                    item.source_native_id,
                    item.source_revision,
                    item.observed_at,
                    item.ingested_at,
                    item.tier,
                    item.claim_kind,
                    item.subject_ref,
                    item.provenance_digest,
                ]
                for item in plan.evidence
            ],
            empty=PLACEHOLDER_EVIDENCE,
        )
    )
    lines.extend(["### Dispositions", ""])
    lines.extend(
        _render_table(
            ["Evidence ID", "Disposition", "Reason"],
            [
                [item.evidence_id, item.disposition, item.reason]
                for item in plan.evidence_dispositions
            ],
            empty=PLACEHOLDER_DISPOSITIONS,
        )
    )
    return lines


def _render_concept_mappings(plan: StudyPlan) -> list[str]:
    lines = ["### Concepts", ""]
    lines.extend(
        _render_table(
            ["ID", "Display label"],
            [[concept.concept_id, concept.display_label] for concept in plan.concepts],
            empty=PLACEHOLDER_CONCEPTS,
        )
    )
    lines.extend(["### Relations", ""])
    lines.extend(
        _render_table(
            ["Source ref", "Target ref", "Relation", "Reason", "Decided by"],
            [
                [
                    relation.source_ref,
                    relation.target_ref,
                    relation.relation,
                    relation.reason,
                    relation.decided_by,
                ]
                for relation in plan.concept_relations
            ],
            empty=PLACEHOLDER_RELATIONS,
        )
    )
    return lines


def _render_unknowns(plan: StudyPlan) -> list[str]:
    return _render_table(
        ["ID", "Question", "Impact", "Status"],
        [
            [unknown.unknown_id, unknown.question, unknown.impact, unknown.status]
            for unknown in plan.unknowns
        ],
        empty=PLACEHOLDER_UNKNOWNS,
    )


def _render_decisions(plan: StudyPlan) -> list[str]:
    return _render_table(
        ["ID", "Proposal ID", "Outcome", "Actor kind", "Channel", "Reason", "Decided at"],
        [
            [
                decision.decision_id,
                decision.proposal_id,
                decision.outcome,
                decision.actor_kind,
                decision.channel,
                decision.reason,
                decision.decided_at,
            ]
            for decision in plan.decisions
        ],
        empty=PLACEHOLDER_DECISIONS,
    )


def render_milestone(milestone: Milestone) -> str:
    """Render one milestone as a GitHub-flavoured task-list item."""
    box = "x" if milestone.done else " "
    text = f"**{milestone.title}**"
    if milestone.notes:
        text += f" — {milestone.notes}"
    if milestone.concepts:
        text += f" `(concepts: {', '.join(milestone.concepts)})`"
    return f"- [{box}] {text}"


def render_plan(plan: StudyPlan) -> str:
    """Render a :class:`StudyPlan` as its canonical Markdown document."""
    out: list[str] = []
    out.extend(_render_frontmatter(plan))
    out.append("")
    out.append(f"# {plan.title}")
    out.append("")

    out.append("## Mission")
    out.append("")
    out.append("### Why")
    out.append("")
    out.append(plan.mission.why or PLACEHOLDER_WHY)
    out.append("")
    out.append("### Success looks like")
    out.append("")
    out.extend(_render_bullets(plan.mission.success, empty=PLACEHOLDER_SUCCESS))
    out.append("### Constraints")
    out.append("")
    out.extend(_render_bullets(plan.mission.constraints, empty=PLACEHOLDER_CONSTRAINTS))
    out.append("### Out of scope")
    out.append("")
    out.extend(_render_bullets(plan.mission.out_of_scope, empty=PLACEHOLDER_OUT_OF_SCOPE))

    if plan.schema_version >= 2:
        out.append("## Goals")
        out.append("")
        out.extend(_render_goals(plan))

        out.append("## Learning Map")
        out.append("")
        out.extend(render_learning_map(plan).splitlines())
        out.append("")

        out.append("## Milestones")
        out.append("")
        out.extend(_render_v2_milestones(plan))

        out.append("## Evidence Ledger")
        out.append("")
        out.extend(_render_evidence_ledger(plan))

        out.append("## Concept Mappings")
        out.append("")
        out.extend(_render_concept_mappings(plan))

        out.append("## Unknowns")
        out.append("")
        out.extend(_render_unknowns(plan))
    else:
        out.append("## Milestones")
        out.append("")
        if plan.milestones:
            out.extend(render_milestone(m) for m in plan.milestones)
        else:
            out.append(PLACEHOLDER_MILESTONES)
        out.append("")

    out.append("## Learning Records")
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

    out.append("## Resources")
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

    out.append("## Checkpoints")
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

    if plan.schema_version >= 2:
        out.append("## Decisions")
        out.append("")
        out.extend(_render_decisions(plan))

    out.append("## Notes")
    out.append("")
    out.append(plan.notes or PLACEHOLDER_NOTES)
    out.append("")

    return "\n".join(out)
