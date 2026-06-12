"""Concept mastery graph API routes."""

from __future__ import annotations

from fastapi import APIRouter, Query
from fastapi.responses import PlainTextResponse

from studyloop.learning.mastery import (
    mastery_graph_json,
    mastery_graph_mermaid,
    weak_links_for_topic,
)

router = APIRouter()


@router.get("/mastery/graph", response_model=None)
def get_mastery_graph(
    topic: str = Query(..., min_length=1, max_length=120),
    output_format: str = Query("json", alias="format", pattern="^(json|mermaid)$"),
    limit: int = Query(80, ge=1, le=250),
):
    """Return a mastery graph as JSON or Mermaid."""
    cleaned = topic.strip()
    if output_format == "mermaid":
        return PlainTextResponse(
            mastery_graph_mermaid(cleaned, max_edges=limit),
            media_type="text/plain",
        )
    return mastery_graph_json(cleaned, max_edges=limit)


@router.get("/mastery/weak-links")
def get_mastery_weak_links(
    topic: str = Query(..., min_length=1, max_length=120),
    limit: int = Query(12, ge=1, le=50),
) -> dict:
    """Return weak prerequisite links for a topic."""
    cleaned = topic.strip()
    links = weak_links_for_topic(cleaned)
    return {
        "topic": cleaned,
        "weak_links": links[:limit],
        "weak_link_count_total": len(links),
        "limited": len(links) > limit,
    }
