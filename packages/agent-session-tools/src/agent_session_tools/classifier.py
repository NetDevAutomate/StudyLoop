"""Session classification for categorizing session types.

Classifies sessions into categories:
- work: General development, feature implementation
- learning: Tutorials, concept explanations, Q&A learning
- debugging: Bug fixes, error investigation, troubleshooting
- refactoring: Code cleanup, restructuring, optimization
- planning: Architecture discussions, design decisions
"""

import logging
import re
import sqlite3
from collections import Counter
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Classification categories with keywords and patterns
CATEGORIES = {
    "learning": {
        "keywords": [
            "explain",
            "understand",
            "learn",
            "tutorial",
            "teach",
            "concept",
            "how does",
            "what is",
            "why does",
            "can you explain",
            "help me understand",
            "walk me through",
            "beginner",
            "basics",
            "fundamentals",
        ],
        "patterns": [
            r"what\s+(is|are|does)",
            r"how\s+(do|does|can|should)",
            r"why\s+(is|does|do)",
            r"explain\s+\w+",
            r"teach\s+me",
        ],
        "weight": 1.5,  # Boost learning detection
    },
    "debugging": {
        "keywords": [
            "error",
            "bug",
            "fix",
            "issue",
            "broken",
            "failing",
            "crash",
            "exception",
            "traceback",
            "stack trace",
            "not working",
            "doesn't work",
            "debug",
            "troubleshoot",
            "investigate",
        ],
        "patterns": [
            r"error[:\s]",
            r"exception[:\s]",
            r"traceback",
            r"failed\s+to",
            r"cannot\s+\w+",
            r"undefined\s+\w+",
            r"null\s+pointer",
            r"segfault",
        ],
        "weight": 1.3,
    },
    "refactoring": {
        "keywords": [
            "refactor",
            "cleanup",
            "clean up",
            "restructure",
            "reorganize",
            "optimize",
            "improve",
            "simplify",
            "consolidate",
            "extract",
            "rename",
            "move",
            "split",
        ],
        "patterns": [
            r"refactor\s+\w+",
            r"clean\s*up",
            r"extract\s+(method|function|class)",
            r"rename\s+\w+",
        ],
        "weight": 1.2,
    },
    "planning": {
        "keywords": [
            "architecture",
            "design",
            "plan",
            "structure",
            "approach",
            "strategy",
            "decision",
            "trade-off",
            "pros and cons",
            "options",
            "alternatives",
            "proposal",
            "rfc",
            "adr",
        ],
        "patterns": [
            r"should\s+(we|i)\s+use",
            r"which\s+(approach|method|pattern)",
            r"design\s+(decision|pattern)",
            r"architect(ure)?",
        ],
        "weight": 1.1,
    },
    "work": {
        "keywords": [
            "implement",
            "create",
            "add",
            "build",
            "develop",
            "write",
            "make",
            "update",
            "change",
            "modify",
        ],
        "patterns": [
            r"(create|add|implement)\s+\w+",
            r"write\s+(a|the)\s+\w+",
        ],
        "weight": 1.0,  # Base weight
    },
}


@dataclass
class ClassificationResult:
    """Result of session classification."""

    session_id: str
    category: str
    confidence: float
    scores: dict[str, float]
    sample_evidence: list[str]


def classify_text(text: str) -> dict[str, float]:
    """Score text against all categories.

    Args:
        text: Text content to classify

    Returns:
        Dict mapping category names to scores
    """
    text_lower = text.lower()
    scores: dict[str, float] = dict.fromkeys(CATEGORIES, 0.0)

    for category, config in CATEGORIES.items():
        score = 0.0

        # Keyword matching
        for keyword in config["keywords"]:
            count = text_lower.count(keyword)
            if count > 0:
                score += count * 0.1

        # Pattern matching
        for pattern in config["patterns"]:
            matches = len(re.findall(pattern, text_lower))
            if matches > 0:
                score += matches * 0.2

        # Apply category weight
        scores[category] = score * config["weight"]

    return scores


def classify_session(
    conn: sqlite3.Connection,
    session_id: str,
    message_limit: int = 50,
) -> ClassificationResult:
    """Classify a session based on its message content.

    Args:
        conn: Database connection
        session_id: ID of session to classify
        message_limit: Max messages to analyze

    Returns:
        ClassificationResult with category and confidence
    """
    # Get session messages (focus on user messages for intent)
    messages = conn.execute(
        """
        SELECT role, content FROM messages
        WHERE session_id = ?
          AND role IN ('user', 'assistant')
          AND content IS NOT NULL
        ORDER BY seq, timestamp
        LIMIT ?
        """,
        (session_id, message_limit),
    ).fetchall()

    if not messages:
        return ClassificationResult(
            session_id=session_id,
            category="work",
            confidence=0.0,
            scores={},
            sample_evidence=[],
        )

    # Aggregate scores from all messages (user messages weighted higher)
    total_scores: dict[str, float] = dict.fromkeys(CATEGORIES, 0.0)
    evidence: list[str] = []

    for role, content in messages:
        weight = 1.5 if role == "user" else 1.0
        text_scores = classify_text(content)

        for category, score in text_scores.items():
            total_scores[category] += score * weight

        # Collect evidence snippets
        if any(score > 0.1 for score in text_scores.values()):
            snippet = content[:100].replace("\n", " ").strip()
            if snippet and len(evidence) < 5:
                evidence.append(snippet)

    # Normalize scores
    max_score = max(total_scores.values()) if total_scores.values() else 1.0
    if max_score > 0:
        normalized = {k: v / max_score for k, v in total_scores.items()}
    else:
        normalized = total_scores

    # Determine winning category
    if max_score == 0:
        category = "work"
        confidence = 0.5
    else:
        category = max(total_scores, key=lambda k: total_scores[k])
        confidence = min(normalized[category], 1.0)

    return ClassificationResult(
        session_id=session_id,
        category=category,
        confidence=confidence,
        scores=normalized,
        sample_evidence=evidence,
    )


def classify_all_sessions(
    conn: sqlite3.Connection,
    update_db: bool = True,
    session_limit: int | None = None,
) -> dict[str, int]:
    """Classify all sessions and optionally update the database.

    Args:
        conn: Database connection
        update_db: Whether to update session_type in database
        session_limit: Max sessions to process (None for all)

    Returns:
        Dict with category counts
    """
    query = "SELECT id FROM sessions"
    if session_limit:
        query += f" LIMIT {session_limit}"

    sessions = conn.execute(query).fetchall()
    category_counts: Counter = Counter()

    for (session_id,) in sessions:
        result = classify_session(conn, session_id)
        category_counts[result.category] += 1

        if update_db:
            conn.execute(
                "UPDATE sessions SET session_type = ? WHERE id = ?",
                (result.category, session_id),
            )

    if update_db:
        conn.commit()
        logger.info(f"Updated {len(sessions)} sessions with classifications")

    return dict(category_counts)


def reclassify_sessions(
    conn: sqlite3.Connection,
    dry_run: bool = True,
) -> dict:
    """Reclassify all sessions and show changes.

    Args:
        conn: Database connection
        dry_run: If True, don't update database

    Returns:
        Dict with statistics about changes
    """
    sessions = conn.execute("SELECT id, session_type FROM sessions").fetchall()

    changes = []
    category_counts: Counter = Counter()

    for session_id, current_type in sessions:
        result = classify_session(conn, session_id)
        category_counts[result.category] += 1

        if result.category != current_type:
            changes.append(
                {
                    "session_id": session_id,
                    "from": current_type,
                    "to": result.category,
                    "confidence": result.confidence,
                }
            )

    if not dry_run:
        for change in changes:
            conn.execute(
                "UPDATE sessions SET session_type = ? WHERE id = ?",
                (change["to"], change["session_id"]),
            )
        conn.commit()

    return {
        "total_sessions": len(sessions),
        "changes": len(changes),
        "category_distribution": dict(category_counts),
        "sample_changes": changes[:10],
    }
