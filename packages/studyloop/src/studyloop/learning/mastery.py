"""Mastery graph and weak-link helpers."""

from __future__ import annotations

import re
import sqlite3
import uuid
from dataclasses import asdict, dataclass
from itertools import pairwise
from typing import TYPE_CHECKING

from studyloop.history import _connection

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)
_WIKILINK_RE = re.compile(r"\[\[([^\]|#]+)")
_TAG_RE = re.compile(r"(?<!\w)#([A-Za-z][\w/-]+)")

# --------------------------------------------------------------------------
# Graph colour categories
# --------------------------------------------------------------------------
# THE NODE SIGNAL IS `study_progress.confidence`, which this module already
# reads in `weak_links_for_topic` — nothing here is invented and no schema
# column is added. Its domain is fixed in three independent places:
#   * planning.exercises.models.CONFIDENCE_LEVELS
#     = ("struggling", "learning", "confident", "mastered")
#   * history.teachback._confidence_from_teachback, the writer, emits exactly
#     those four strings from a teach-back total
#   * history.progress ranks the same four, and cli._review offers them as a
#     click.Choice
# A concept with no `study_progress` row has no evidence at all, which is its
# own honest category rather than a guessed position on the scale — and it is
# the common case, because most nodes are seeded from markdown headings and
# wiki links that were never teach-backed.
#
# COLOURS ARE MEASURED, NOT CHOSEN BY EYE. Every value below was solved against
# the real surfaces — `--bg` and `--bg-card` for all nine palettes plus
# default/light (style.css), and the two surfaces mermaid's own `dark` theme
# paints, since static/index.html initialises `theme: 'dark'`. Verified:
#   * label text on its own fill      4.95-5.06:1   (WCAG AA normal text)
#   * fill vs worst-case backdrop     1.99-2.03:1   (nord --bg-card)
#   * border vs its own fill          2.09-2.39:1
#   * pairwise CIE76 dE between fills 22.9-72.6     (>= 22 = separable)
# Two constraints turned out to be UNSATISFIABLE and are recorded here so the
# next reader does not retry them:
#   * No single edge colour reaches 3:1 against BOTH nord --bg-card (#3b4252)
#     and latte --bg (#eff1f5): the first forces luminance >= 0.2731, the
#     second <= 0.2567. Edges therefore hold 3:1 against the mermaid dark
#     surfaces the graph actually sits on, and >= 1.5:1 against every app
#     backdrop in case the app background shows through the SVG.
#   * A near-neutral grey fill cannot clear 1.5:1 against all of those
#     surfaces either, because the palettes' own backgrounds ARE neutral greys.
#     So "no evidence" cannot recede by being grey; it carries the lowest
#     saturation that clears the gate and signals "provisional" on a
#     non-colour channel instead — a dashed border.
_UNTRACKED_KEY = "untracked"

_NODE_CATEGORIES: tuple[dict[str, str], ...] = (
    {
        "key": "struggling",
        "class_name": "slStruggling",
        "label": "Struggling",
        "colour": "#ac5362",
        "border_colour": "#d897a2",
        "text_colour": "#ffffff",
        "meaning": "Teach-back evidence is weak — start here",
    },
    {
        "key": "learning",
        "class_name": "slLearning",
        "label": "Learning",
        "colour": "#8b6a43",
        "border_colour": "#caa274",
        "text_colour": "#ffffff",
        "meaning": "Partly understood and still consolidating",
    },
    {
        "key": "confident",
        "class_name": "slConfident",
        "label": "Confident",
        "colour": "#3f7692",
        "border_colour": "#71b0d0",
        "text_colour": "#ffffff",
        "meaning": "Recalled reliably — keep it warm",
    },
    {
        "key": "mastered",
        "class_name": "slMastered",
        "label": "Mastered",
        "colour": "#367d4d",
        "border_colour": "#5bc87f",
        "text_colour": "#ffffff",
        "meaning": "Held up under a full review",
    },
    {
        "key": _UNTRACKED_KEY,
        "class_name": "slUntracked",
        "label": "No evidence yet",
        "colour": "#706996",
        "border_colour": "#aaa4cc",
        "text_colour": "#ffffff",
        "dash": "4 3",
        "meaning": "Seeded from your notes, never teach-backed",
    },
)

_EDGE_RELATIONS: tuple[dict[str, str], ...] = (
    {
        "key": "heading_path",
        "label": "Note structure",
        "colour": "#6183b3",
        "meaning": "Consecutive headings in one note — the order it teaches in",
    },
    {
        "key": "backlink",
        "label": "Note link",
        "colour": "#a36bc0",
        "meaning": "A [[wiki link]] pointing from a note to a concept",
    },
    {
        "key": "other",
        "label": "Other relation",
        "colour": "#538b86",
        "meaning": "Tags, knowledge bridges and explicit concept relations",
    },
)

_NODE_CATEGORY_BY_KEY = {category["key"]: category for category in _NODE_CATEGORIES}
_EDGE_RELATION_BY_KEY = {relation["key"]: relation for relation in _EDGE_RELATIONS}
_STYLED_RELATIONS = frozenset({"heading_path", "backlink"})


@dataclass(frozen=True)
class ConceptDependency:
    topic: str
    source_concept: str
    target_concept: str
    relation_type: str
    evidence: str
    source_type: str
    confidence: float

    def to_json_dict(self) -> dict:
        return asdict(self)


def _normalise(value: str) -> str:
    return " ".join(value.replace("_", " ").replace("-", " ").split()).lower()


def _connect():
    try:
        return _connection._connect()
    except Exception:
        return None


def upsert_dependency(edge: ConceptDependency) -> bool:
    conn = _connect()
    if not conn:
        return False
    try:
        conn.execute(
            """
            INSERT INTO concept_dependencies
                (id, topic, source_concept, target_concept, relation_type,
                 evidence, source_type, confidence)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(topic, source_concept, target_concept, relation_type)
            DO UPDATE SET
                evidence = COALESCE(excluded.evidence, evidence),
                source_type = excluded.source_type,
                confidence = MAX(confidence, excluded.confidence),
                updated_at = datetime('now')
            """,
            (
                str(
                    uuid.uuid5(
                        uuid.NAMESPACE_DNS,
                        f"{edge.topic}:{edge.source_concept}:{edge.target_concept}:{edge.relation_type}",
                    )
                ),
                edge.topic,
                edge.source_concept,
                edge.target_concept,
                edge.relation_type,
                edge.evidence,
                edge.source_type,
                edge.confidence,
            ),
        )
        conn.commit()
        return True
    except sqlite3.OperationalError:
        return False
    finally:
        conn.close()


def _markdown_roots() -> list[Path]:
    try:
        from studyloop.settings import load_settings

        settings = load_settings()
        roots = [*settings.content.study_paths, settings.content.base_path]
    except Exception:
        roots = []
    unique: list[Path] = []
    seen: set[Path] = set()
    for root in roots:
        resolved = root.expanduser().resolve()
        if resolved in seen or not resolved.exists():
            continue
        seen.add(resolved)
        unique.append(resolved)
    return unique


def _seed_from_markdown(topic: str, *, max_files: int = 75) -> int:
    topic_key = topic.lower()
    count = 0
    for root in _markdown_roots():
        files = sorted(root.rglob("*.md"))[:max_files]
        for path in files:
            path_text = str(path).lower()
            if (
                topic_key not in path_text
                and topic_key
                not in path.read_text(encoding="utf-8", errors="ignore").lower()[:8000]
            ):
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            headings = [m.group(2).strip() for m in _HEADING_RE.finditer(text)]
            for source, target in pairwise(headings):
                if upsert_dependency(
                    ConceptDependency(
                        topic=topic,
                        source_concept=_normalise(source),
                        target_concept=_normalise(target),
                        relation_type="heading_path",
                        evidence=str(path),
                        source_type="heading",
                        confidence=0.45,
                    )
                ):
                    count += 1
            note_stem = _normalise(path.stem)
            for target in _WIKILINK_RE.findall(text):
                if upsert_dependency(
                    ConceptDependency(
                        topic=topic,
                        source_concept=note_stem,
                        target_concept=_normalise(target),
                        relation_type="backlink",
                        evidence=str(path),
                        source_type="backlink",
                        confidence=0.5,
                    )
                ):
                    count += 1
            for tag in _TAG_RE.findall(text):
                if upsert_dependency(
                    ConceptDependency(
                        topic=topic,
                        source_concept=note_stem,
                        target_concept=_normalise(tag),
                        relation_type="tagged_with",
                        evidence=str(path),
                        source_type="tag",
                        confidence=0.35,
                    )
                ):
                    count += 1
    return count


def seed_inferred_dependencies(topic: str) -> int:
    """Infer initial edges from existing graph/bridges and local markdown notes."""
    count = _seed_from_markdown(topic)
    conn = _connect()
    if not conn:
        return count
    try:
        try:
            rows = conn.execute(
                """
                SELECT s.name AS source_name, t.name AS target_name,
                       s.domain AS source_domain, t.domain AS target_domain,
                       r.relation_type, r.confidence
                FROM concept_relations r
                JOIN concepts s ON s.id = r.source_concept_id
                JOIN concepts t ON t.id = r.target_concept_id
                WHERE s.domain = ? OR t.domain = ?
                """,
                (topic, topic),
            ).fetchall()
            for row in rows:
                if upsert_dependency(
                    ConceptDependency(
                        topic=topic,
                        source_concept=row["source_name"],
                        target_concept=row["target_name"],
                        relation_type=row["relation_type"],
                        evidence=f"concept_relations:{row['source_domain']}->{row['target_domain']}",
                        source_type="concept_graph",
                        confidence=float(row["confidence"] or 0.5),
                    )
                ):
                    count += 1
        except sqlite3.OperationalError:
            pass

        try:
            rows = conn.execute(
                """
                SELECT source_concept, target_concept, source_domain, target_domain, quality
                FROM knowledge_bridges
                WHERE source_domain = ? OR target_domain = ?
                """,
                (topic, topic),
            ).fetchall()
            for row in rows:
                quality = row["quality"]
                confidence = 0.75 if quality in {"strong", "effective", "validated"} else 0.45
                if upsert_dependency(
                    ConceptDependency(
                        topic=topic,
                        source_concept=row["source_concept"],
                        target_concept=row["target_concept"],
                        relation_type="bridge",
                        evidence=f"{row['source_domain']}->{row['target_domain']}",
                        source_type="knowledge_bridge",
                        confidence=confidence,
                    )
                ):
                    count += 1
        except sqlite3.OperationalError:
            pass
    finally:
        conn.close()
    return count


def _fetch_dependencies(topic: str) -> list[ConceptDependency]:
    conn = _connect()
    if not conn:
        return []
    try:
        rows = conn.execute(
            """
            SELECT topic, source_concept, target_concept, relation_type,
                   evidence, source_type, confidence
            FROM concept_dependencies
            WHERE topic = ?
            ORDER BY confidence DESC, source_concept, target_concept
            """,
            (topic,),
        ).fetchall()
        return [
            ConceptDependency(
                topic=row["topic"],
                source_concept=row["source_concept"],
                target_concept=row["target_concept"],
                relation_type=row["relation_type"],
                evidence=row["evidence"] or "",
                source_type=row["source_type"] or "explicit",
                confidence=float(row["confidence"] or 0.0),
            )
            for row in rows
        ]
    except sqlite3.OperationalError:
        return []
    finally:
        conn.close()


def list_dependencies(topic: str) -> list[ConceptDependency]:
    edges = _fetch_dependencies(topic)
    if edges:
        return edges
    seed_inferred_dependencies(topic)
    return _fetch_dependencies(topic)


def _progress_by_concept(topic: str) -> dict[str, dict]:
    """Return `study_progress` rows for `topic`, keyed by lowercased concept.

    Deliberately a separate read from the one inside `weak_links_for_topic`
    rather than a refactor of it: that function is covered by its own tests and
    also needs `last_seen`, so the two are left independent. Both tolerate a
    database with no `study_progress` table, which is the case in unit tests
    that build only `concept_dependencies`.
    """
    conn = _connect()
    if not conn:
        return {}
    try:
        rows = conn.execute(
            """
            SELECT concept, confidence, last_teachback_score
            FROM study_progress
            WHERE topic = ?
            """,
            (topic,),
        ).fetchall()
        return {str(row["concept"]).lower(): dict(row) for row in rows}
    except sqlite3.OperationalError:
        return {}
    finally:
        conn.close()


def _category_for_progress(state: dict) -> str:
    """Map one `study_progress` row onto a node category key.

    `confidence` is authoritative when present. When it is missing but a
    teach-back score is not, the score is mapped through the SAME thresholds
    `history.teachback._confidence_from_teachback` uses to produce `confidence`
    in the first place, so the two can never disagree. That mapping's top band
    depends on `review_type`, which `study_progress` does not carry, so the
    score-only path stops at "confident" and never claims mastery.
    """
    confidence = state.get("confidence")
    if isinstance(confidence, str) and confidence in _NODE_CATEGORY_BY_KEY:
        return confidence
    score = state.get("last_teachback_score")
    if isinstance(score, int | float):
        if score < 9:
            return "struggling"
        if score <= 13:
            return "learning"
        return "confident"
    return _UNTRACKED_KEY


def mastery_node_categories(topic: str, nodes: Iterable[str]) -> dict[str, str]:
    """Map each node name to its colour category key.

    Concepts are matched case-insensitively, the same way
    `weak_links_for_topic` matches them, because graph nodes arrive normalised
    from markdown while `study_progress` stores whatever the recorder wrote.
    """
    progress = _progress_by_concept(topic)
    return {node: _category_for_progress(progress.get(node.lower(), {})) for node in nodes}


def mastery_legend() -> list[dict]:
    """Return the graph legend AS DATA, so a rendered legend cannot drift.

    Node categories first, then edge relations. Every entry carries `label`,
    `colour` and `meaning` for display, plus `kind` and `key` so a consumer can
    group or filter without string-matching the label.
    """
    legend: list[dict] = [
        {
            "kind": "node",
            "key": category["key"],
            "label": category["label"],
            "colour": category["colour"],
            "border_colour": category["border_colour"],
            "meaning": category["meaning"],
            "dashed": bool(category.get("dash")),
        }
        for category in _NODE_CATEGORIES
    ]
    legend.extend(
        {
            "kind": "edge",
            "key": relation["key"],
            "label": relation["label"],
            "colour": relation["colour"],
            "meaning": relation["meaning"],
            "dashed": False,
        }
        for relation in _EDGE_RELATIONS
    )
    return legend


def _relation_key(relation_type: str) -> str:
    """Bucket a `relation_type` onto a styled edge category.

    `heading_path` and `backlink` are styled by name. Everything else shares the
    "other" bucket: this module also emits `tagged_with` and `bridge`, and
    `concept_relations` supplies arbitrary types such as `prerequisite`, so a
    catch-all is required for `linkStyle` indices to stay exhaustive.
    """
    return relation_type if relation_type in _STYLED_RELATIONS else "other"


def mastery_graph_json(topic: str, *, max_edges: int | None = None) -> dict:
    edges = list_dependencies(topic)
    selected_edges = edges[:max_edges] if max_edges is not None else edges
    nodes = sorted(
        {edge.source_concept for edge in selected_edges}
        | {edge.target_concept for edge in selected_edges}
    )
    return {
        "topic": topic,
        "nodes": nodes,
        "edges": [edge.to_json_dict() for edge in selected_edges],
        "edge_count_total": len(edges),
        "limited": len(selected_edges) < len(edges),
        # ADDITIVE. `nodes` stays a list of plain strings and no existing key
        # changes meaning, because the panel and its tests already read them.
        # `node_categories` is what lets a CLIENT-BUILT graph carry the same
        # colours as the legend: static/components.js builds its own mermaid
        # from this JSON via `_masteryMermaidFromGraph` rather than using
        # `mastery_graph_mermaid`, so without this map its graph and the legend
        # would disagree.
        "node_categories": mastery_node_categories(topic, nodes),
        "legend": mastery_legend(),
    }


def _mermaid_id(name: str) -> str:
    ident = re.sub(r"[^A-Za-z0-9_]", "_", name).strip("_") or "concept"
    if ident[0].isdigit():
        ident = f"concept_{ident}"
    return ident


def _mermaid_label(name: str) -> str:
    return (
        name.replace('"', "'")
        .replace("`", "'")
        .replace("[", "(")
        .replace("]", ")")
        .replace("\n", " ")
    )


def _classdef_line(category: dict[str, str]) -> str:
    styles = [
        f"fill:{category['colour']}",
        f"stroke:{category['border_colour']}",
        f"color:{category['text_colour']}",
        "stroke-width:1px",
    ]
    dash = category.get("dash")
    if dash:
        # Space-separated on purpose: a comma here would end the style list.
        styles.append(f"stroke-dasharray:{dash}")
    return f"  classDef {category['class_name']} {','.join(styles)};"


def mastery_graph_mermaid(topic: str, *, max_edges: int | None = None) -> str:
    graph = mastery_graph_json(topic, max_edges=max_edges)
    lines = ["flowchart LR"]
    if not graph["edges"]:
        lines.append(f'  empty["No mastery edges found for {topic} yet"]')
        return "\n".join(lines)
    lines.extend(_classdef_line(category) for category in _NODE_CATEGORIES)
    ids: dict[str, str] = {}
    for node in graph["nodes"]:
        base = _mermaid_id(node)
        ident = base
        suffix = 2
        while ident in ids.values():
            ident = f"{base}_{suffix}"
            suffix += 1
        ids[node] = ident
        label = _mermaid_label(node)
        lines.append(f'  {ident}["{label}"]')
    # linkStyle addresses edges by their emission index, and mermaid raises if
    # an index is out of bounds, so the indices are collected from the very loop
    # that writes the edges rather than recomputed afterwards.
    relation_indices: dict[str, list[int]] = {}
    for index, edge in enumerate(graph["edges"]):
        source = ids[edge["source_concept"]]
        target = ids[edge["target_concept"]]
        relation = edge["relation_type"].replace('"', "'")
        lines.append(f'  {source} -->|"{relation}"| {target}')
        relation_indices.setdefault(_relation_key(edge["relation_type"]), []).append(index)
    categories = graph["node_categories"]
    for category in _NODE_CATEGORIES:
        members = [ids[node] for node in graph["nodes"] if categories.get(node) == category["key"]]
        if members:
            lines.append(f"  class {','.join(members)} {category['class_name']};")
    for relation in _EDGE_RELATIONS:
        indices = relation_indices.get(relation["key"])
        if indices:
            joined = ",".join(str(index) for index in indices)
            lines.append(f"  linkStyle {joined} stroke:{relation['colour']},stroke-width:2px;")
    return "\n".join(lines)


def weak_links_for_topic(topic: str) -> list[dict]:
    """Return struggling/low-score concepts that block downstream edges."""
    edges = list_dependencies(topic)
    conn = _connect()
    progress: dict[str, dict] = {}
    if conn:
        try:
            rows = conn.execute(
                """
                SELECT concept, confidence, last_teachback_score, last_seen
                FROM study_progress
                WHERE topic = ?
                """,
                (topic,),
            ).fetchall()
            progress = {str(row["concept"]).lower(): dict(row) for row in rows}
        except sqlite3.OperationalError:
            progress = {}
        finally:
            conn.close()

    items: list[dict] = []
    for edge in edges:
        source_key = edge.source_concept.lower()
        state = progress.get(source_key, {})
        confidence = state.get("confidence")
        score = state.get("last_teachback_score")
        weak = confidence in {"struggling", "learning"} or (
            isinstance(score, int | float) and score < 14
        )
        if not weak:
            continue
        rank = 0 if confidence == "struggling" else 1
        if isinstance(score, int | float):
            rank -= max(0, 14 - int(score))
        items.append(
            {
                "topic": topic,
                "concept": edge.source_concept,
                "dependency": edge.target_concept,
                "source": edge.evidence,
                "reason": (
                    f"{edge.source_concept} is {confidence or 'low-score'} "
                    f"and feeds {edge.target_concept}"
                ),
                "confidence": confidence,
                "last_teachback_score": score,
                "_rank": rank,
            }
        )
    return [
        {k: v for k, v in item.items() if k != "_rank"}
        for item in sorted(items, key=lambda item: item["_rank"])
    ]
