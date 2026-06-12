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
    from pathlib import Path

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)
_WIKILINK_RE = re.compile(r"\[\[([^\]|#]+)")
_TAG_RE = re.compile(r"(?<!\w)#([A-Za-z][\w/-]+)")


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


def mastery_graph_mermaid(topic: str, *, max_edges: int | None = None) -> str:
    graph = mastery_graph_json(topic, max_edges=max_edges)
    lines = ["flowchart LR"]
    if not graph["edges"]:
        lines.append(f'  empty["No mastery edges found for {topic} yet"]')
        return "\n".join(lines)
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
    for edge in graph["edges"]:
        source = ids[edge["source_concept"]]
        target = ids[edge["target_concept"]]
        relation = edge["relation_type"].replace('"', "'")
        lines.append(f'  {source} -->|"{relation}"| {target}')
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
