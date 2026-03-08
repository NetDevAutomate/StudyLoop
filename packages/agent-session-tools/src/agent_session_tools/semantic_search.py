"""Hybrid FTS5 + vector search for semantic session retrieval.

This module combines:
1. FTS5 keyword search (fast recall, exact matches, porter stemming)
2. Vector similarity search (semantic understanding)
3. Reciprocal Rank Fusion for combining result sets

The hybrid approach captures both:
- Exact keyword matches (important for code, error messages, function names)
- Semantic similarity (important for "find similar problems/solutions")
"""

import logging
import sqlite3
from dataclasses import dataclass, field
from typing import Literal

from .embeddings import (
    EMBEDDINGS_AVAILABLE,
    cosine_similarity,
    generate_embedding,
)

logger = logging.getLogger(__name__)


@dataclass
class SearchResult:
    """A single search result with relevance scores."""

    session_id: str
    project_path: str
    content_preview: str
    message_id: str = ""
    role: str = ""
    timestamp: str = ""
    source: str = ""
    fts_score: float = 0.0
    semantic_score: float = 0.0
    combined_score: float = 0.0
    match_type: Literal["fts", "semantic", "hybrid"] = "fts"

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "session_id": self.session_id,
            "project_path": self.project_path,
            "content_preview": self.content_preview,
            "message_id": self.message_id,
            "role": self.role,
            "timestamp": self.timestamp,
            "source": self.source,
            "fts_score": self.fts_score,
            "semantic_score": self.semantic_score,
            "combined_score": self.combined_score,
            "match_type": self.match_type,
        }


@dataclass
class SearchContext:
    """Context for search filtering and ranking."""

    project_path: str | None = None  # Filter to specific project
    source: str | None = None  # Filter by source (claude_code, kiro_cli, etc.)
    session_type: str | None = None  # Filter by session type (work, learning, etc.)
    since: str | None = None  # Filter by date
    before: str | None = None  # Filter by date
    roles: list[str] = field(default_factory=lambda: ["user", "assistant"])
    exclude_session_ids: list[str] = field(default_factory=list)


def escape_fts_query(query: str) -> str:
    """Escape a query string for FTS5 MATCH.

    With porter stemming enabled, we can use simpler queries that match variants.
    For example: "create" will match "created", "creating", "creates".
    """
    query = query.strip().strip('"').strip("'")

    # If query contains FTS operators (AND, OR, NOT), use as-is
    if any(op in query.upper() for op in [" AND ", " OR ", " NOT "]):
        return query

    # Escape quotes
    escaped = query.replace('"', '""')

    # Multi-word queries become phrases
    if " " in escaped:
        return f'"{escaped}"'

    return escaped


def hybrid_search(
    conn: sqlite3.Connection,
    query: str,
    limit: int = 10,
    context: SearchContext | None = None,
    fts_weight: float = 0.4,
    semantic_weight: float = 0.6,
    fts_only: bool = False,
) -> list[SearchResult]:
    """Search using both FTS5 and vector similarity.

    Args:
        conn: Database connection
        query: Search query text
        limit: Maximum number of results to return
        context: Optional search context for filtering
        fts_weight: Weight for FTS5 scores (0-1)
        semantic_weight: Weight for semantic scores (0-1)
        fts_only: If True, skip vector search (faster, keyword-only)

    Returns:
        List of SearchResult objects ranked by combined relevance
    """
    context = context or SearchContext()

    # 1. FTS5 keyword search (always run - fast and catches exact matches)
    fts_results = _fts_search(conn, query, limit * 3, context)
    logger.debug(f"FTS5 returned {len(fts_results)} results")

    # 2. Vector search (if available and not disabled)
    vector_results = []
    if EMBEDDINGS_AVAILABLE and not fts_only:
        try:
            vector_results = _vector_search(conn, query, limit * 3, context)
            logger.debug(f"Vector search returned {len(vector_results)} results")
        except Exception as e:
            logger.warning(f"Vector search failed, using FTS only: {e}")

    # 3. If only FTS results, return them directly
    if not vector_results:
        return [
            SearchResult(
                session_id=r["session_id"],
                project_path=r["project_path"],
                content_preview=r["preview"],
                message_id=r.get("message_id", ""),
                role=r.get("role", ""),
                timestamp=r.get("timestamp", ""),
                source=r.get("source", ""),
                fts_score=r["score"],
                semantic_score=0.0,
                combined_score=r["score"],
                match_type="fts",
            )
            for r in fts_results[:limit]
        ]

    # 4. Combine and re-rank using Reciprocal Rank Fusion
    combined = _fusion_rank(fts_results, vector_results, fts_weight, semantic_weight)

    return combined[:limit]


def _fts_search(
    conn: sqlite3.Connection,
    query: str,
    limit: int,
    context: SearchContext,
) -> list[dict]:
    """FTS5 search with BM25 ranking."""
    fts_query = escape_fts_query(query)

    base_query = """
        SELECT
            s.id as session_id,
            s.project_path,
            s.source,
            m.id as message_id,
            m.role,
            m.timestamp,
            substr(m.content, 1, 500) as preview,
            bm25(messages_fts) as score
        FROM messages m
        JOIN sessions s ON m.session_id = s.id
        JOIN messages_fts ON messages_fts.rowid = m.rowid
        WHERE messages_fts MATCH ?
    """
    params: list = [fts_query]

    # Apply filters
    if context.project_path:
        base_query += " AND s.project_path LIKE ?"
        params.append(f"%{context.project_path}%")

    if context.source:
        base_query += " AND s.source = ?"
        params.append(context.source)

    if context.session_type:
        base_query += " AND s.session_type = ?"
        params.append(context.session_type)

    if context.roles:
        placeholders = ",".join("?" * len(context.roles))
        base_query += f" AND m.role IN ({placeholders})"
        params.extend(context.roles)

    if context.exclude_session_ids:
        placeholders = ",".join("?" * len(context.exclude_session_ids))
        base_query += f" AND s.id NOT IN ({placeholders})"
        params.extend(context.exclude_session_ids)

    if context.since:
        base_query += " AND m.timestamp >= ?"
        params.append(context.since)

    if context.before:
        base_query += " AND m.timestamp <= ?"
        params.append(context.before)

    base_query += " ORDER BY score LIMIT ?"
    params.append(limit)

    try:
        results = conn.execute(base_query, params).fetchall()
        return [dict(r) for r in results]
    except sqlite3.OperationalError as e:
        logger.error(f"FTS search failed: {e}")
        return []


def _vector_search(
    conn: sqlite3.Connection,
    query: str,
    limit: int,
    context: SearchContext,
) -> list[dict]:
    """Vector similarity search using embeddings."""
    if not EMBEDDINGS_AVAILABLE:
        return []

    # Generate query embedding
    query_embedding = generate_embedding(query)

    # Build query for embeddings with joins
    base_query = """
        SELECT
            s.id as session_id,
            s.project_path,
            s.source,
            m.id as message_id,
            m.role,
            m.timestamp,
            substr(m.content, 1, 500) as preview,
            e.embedding
        FROM message_embeddings e
        JOIN messages m ON e.message_id = m.id
        JOIN sessions s ON m.session_id = s.id
        WHERE 1=1
    """
    params: list = []

    # Apply filters
    if context.project_path:
        base_query += " AND s.project_path LIKE ?"
        params.append(f"%{context.project_path}%")

    if context.source:
        base_query += " AND s.source = ?"
        params.append(context.source)

    if context.session_type:
        base_query += " AND s.session_type = ?"
        params.append(context.session_type)

    if context.roles:
        placeholders = ",".join("?" * len(context.roles))
        base_query += f" AND m.role IN ({placeholders})"
        params.extend(context.roles)

    if context.exclude_session_ids:
        placeholders = ",".join("?" * len(context.exclude_session_ids))
        base_query += f" AND s.id NOT IN ({placeholders})"
        params.extend(context.exclude_session_ids)

    if context.since:
        base_query += " AND m.timestamp >= ?"
        params.append(context.since)

    if context.before:
        base_query += " AND m.timestamp <= ?"
        params.append(context.before)

    # Note: We fetch all and compute similarity in Python
    # For large DBs, consider sqlite-vec extension for native vector search
    results = []
    for row in conn.execute(base_query, params).fetchall():
        row_dict = dict(row)
        embedding = row_dict.pop("embedding")
        similarity = cosine_similarity(query_embedding, embedding)
        row_dict["score"] = similarity
        results.append(row_dict)

    # Sort by similarity score
    results.sort(key=lambda x: x["score"], reverse=True)

    return results[:limit]


def _fusion_rank(
    fts_results: list[dict],
    vector_results: list[dict],
    fts_weight: float,
    semantic_weight: float,
) -> list[SearchResult]:
    """Combine result sets using Reciprocal Rank Fusion (RRF).

    RRF is a simple and effective fusion method that:
    - Doesn't require score normalization
    - Works well across different ranking functions
    - Is robust to outliers
    """
    # k parameter for RRF (standard value)
    k = 60

    # Track scores by unique identifier (session_id + message_id)
    scores: dict[tuple[str, str], dict] = {}

    # Score FTS results
    for rank, result in enumerate(fts_results, 1):
        key = (result["session_id"], result.get("message_id", ""))
        if key not in scores:
            scores[key] = {"data": result, "fts_rank": None, "vec_rank": None}
        scores[key]["fts_rank"] = rank

    # Score vector results
    for rank, result in enumerate(vector_results, 1):
        key = (result["session_id"], result.get("message_id", ""))
        if key not in scores:
            scores[key] = {"data": result, "fts_rank": None, "vec_rank": None}
        scores[key]["vec_rank"] = rank
        # Update data if we have semantic-specific info
        if scores[key]["data"].get("preview", "") == "":
            scores[key]["data"] = result

    # Compute combined scores
    combined = []
    for (session_id, message_id), score_data in scores.items():
        fts_rank = score_data["fts_rank"]
        vec_rank = score_data["vec_rank"]
        data = score_data["data"]

        # RRF formula: 1 / (k + rank) for each result set
        fts_score = 1 / (k + fts_rank) if fts_rank else 0
        vec_score = 1 / (k + vec_rank) if vec_rank else 0

        # Weighted combination
        combined_score = fts_weight * fts_score + semantic_weight * vec_score

        # Determine match type
        if fts_rank and vec_rank:
            match_type = "hybrid"
        elif fts_rank:
            match_type = "fts"
        else:
            match_type = "semantic"

        combined.append(
            SearchResult(
                session_id=session_id,
                project_path=data.get("project_path", ""),
                content_preview=data.get("preview", ""),
                message_id=message_id,
                role=data.get("role", ""),
                timestamp=data.get("timestamp", ""),
                source=data.get("source", ""),
                fts_score=fts_score,
                semantic_score=vec_score,
                combined_score=combined_score,
                match_type=match_type,
            )
        )

    # Sort by combined score (highest first)
    combined.sort(key=lambda x: x.combined_score, reverse=True)

    return combined


def find_similar_sessions(
    conn: sqlite3.Connection,
    session_id: str,
    limit: int = 5,
    exclude_same_project: bool = False,
) -> list[SearchResult]:
    """Find sessions similar to a given session.

    Uses session-level embeddings to find semantically similar sessions.
    Useful for "what have I done before that's like this?"

    Args:
        conn: Database connection
        session_id: ID of the reference session
        limit: Maximum number of results
        exclude_same_project: If True, exclude sessions from the same project

    Returns:
        List of similar sessions ranked by similarity
    """
    if not EMBEDDINGS_AVAILABLE:
        logger.warning("Embeddings not available for similarity search")
        return []

    # Get reference session embedding
    ref_embedding = conn.execute(
        "SELECT embedding FROM session_embeddings WHERE session_id = ?", (session_id,)
    ).fetchone()

    if not ref_embedding:
        logger.warning(f"No embedding found for session {session_id}")
        return []

    ref_embedding = ref_embedding[0]

    # Get reference session's project
    ref_session = conn.execute(
        "SELECT project_path FROM sessions WHERE id = ?", (session_id,)
    ).fetchone()
    ref_project = ref_session[0] if ref_session else None

    # Find similar sessions
    query = """
        SELECT s.id, s.project_path, s.source, s.updated_at, e.embedding
        FROM session_embeddings e
        JOIN sessions s ON e.session_id = s.id
        WHERE s.id != ?
    """
    params: list = [session_id]

    if exclude_same_project and ref_project:
        query += " AND s.project_path != ?"
        params.append(ref_project)

    results = []
    for row in conn.execute(query, params).fetchall():
        similarity = cosine_similarity(ref_embedding, row["embedding"])
        results.append(
            SearchResult(
                session_id=row["id"],
                project_path=row["project_path"],
                content_preview="",  # Session-level, no specific message
                source=row["source"],
                timestamp=row["updated_at"],
                semantic_score=similarity,
                combined_score=similarity,
                match_type="semantic",
            )
        )

    # Sort by similarity
    results.sort(key=lambda x: x.semantic_score, reverse=True)

    return results[:limit]


def format_suggested_context(
    results: list[SearchResult],
    query: str,
    max_results: int = 5,
    include_code_snippets: bool = True,
) -> str:
    """Format search results as suggested context for Claude.

    This format is optimized for Claude to reason about and selectively
    incorporate relevant historical context. Based on multi-model review
    recommendations for structured output with rich metadata.

    Args:
        results: Search results to format
        query: Original search query
        max_results: Maximum number of results to include
        include_code_snippets: Whether to extract and show code blocks

    Returns:
        Formatted string for Claude to process
    """
    if not results:
        return f'No historical sessions found matching: "{query}"'

    lines = []
    lines.append("## Suggested Historical Context\n")
    lines.append(
        f'Based on your query "{query}", I found {len(results)} potentially relevant past sessions:\n'
    )

    # Group by confidence level (thresholds based on RRF scoring)
    high_confidence = [r for r in results if r.combined_score > 0.015]
    medium_confidence = [r for r in results if 0.008 <= r.combined_score <= 0.015]

    # Determine overall confidence indicator
    if high_confidence:
        lines.append("**Overall Confidence:** High - found strong matches\n")
    elif medium_confidence:
        lines.append("**Overall Confidence:** Medium - found related content\n")
    else:
        lines.append("**Overall Confidence:** Low - only weak matches found\n")

    if high_confidence:
        lines.append("### Most Relevant (high confidence)\n")
        for i, result in enumerate(high_confidence[:3], 1):
            lines.append(_format_single_result(result, i, include_code_snippets))

    if medium_confidence:
        lines.append("\n### Also Relevant (medium confidence)\n")
        for i, result in enumerate(medium_confidence[:2], 1):
            lines.append(_format_single_result(result, i, include_code_snippets))

    # Add usage guidance
    lines.append("\n---")
    lines.append("### How to Use This Context")
    lines.append(
        "- **High confidence** results are likely directly relevant - review code and approach"
    )
    lines.append(
        "- **Medium confidence** may have useful patterns but verify applicability"
    )
    lines.append("- Historical context should be **adapted**, not copied blindly")
    lines.append("")
    lines.append("**Would you like me to:**")
    lines.append("1. Incorporate specific code patterns from these results?")
    lines.append("2. Show the full session context for any result?")
    lines.append("3. Search with different terms?")

    return "\n".join(lines)


def _format_single_result(
    result: SearchResult,
    index: int,
    include_code: bool = True,
) -> str:
    """Format a single search result with rich metadata.

    Based on multi-model review: include structured metadata,
    code snippets, and relevance indicators.
    """
    lines = []

    # Project name (extract last component for readability)
    project_name = (
        result.project_path.split("/")[-1] if result.project_path else "Unknown"
    )
    full_path = result.project_path or "Unknown"

    lines.append(f"**{index}. {project_name}**")
    lines.append(f"- **Path:** `{full_path}`")
    lines.append(f"- **Source:** {result.source}")

    # Format timestamp nicely
    if result.timestamp:
        lines.append(f"- **When:** {result.timestamp}")

    # Show match type with explanation
    match_explanations = {
        "hybrid": "matched both keywords and meaning",
        "fts": "matched keywords",
        "semantic": "matched meaning/context",
    }
    match_desc = match_explanations.get(result.match_type, result.match_type)
    lines.append(f"- **Match:** {match_desc} (score: {result.combined_score:.4f})")

    # Extract and format content
    if result.content_preview:
        preview = result.content_preview

        # Extract code blocks if present and requested
        if include_code and "```" in preview:
            code_start = preview.find("```")
            code_end = preview.find("```", code_start + 3)
            if code_end > code_start:
                code_block = preview[code_start : code_end + 3]
                lines.append(f"\n**Code Snippet:**\n{code_block}\n")

                # Also show non-code context if there's meaningful text
                non_code = preview[:code_start].strip()
                if len(non_code) > 50:
                    lines.append(f"**Context:** {non_code[:200]}...")
        else:
            # Clean up preview for display
            clean_preview = preview.replace("\n", " ").strip()[:300]
            lines.append(f"- **Preview:** {clean_preview}...")

    lines.append("")
    return "\n".join(lines)
