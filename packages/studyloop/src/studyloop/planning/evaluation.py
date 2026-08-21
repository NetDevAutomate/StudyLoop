"""Evaluate a study plan against real evidence, at three session checkpoints.

A plan that is never checked against reality becomes a wish list.  This module
is the corrective: it reads what the learner actually did and reports whether
the plan still describes it.

Evidence comes from both table families in ``sessions.db``:

*StudyLoop tables* (the active-learning store)
    ``study_progress`` — per-concept confidence, via
    :func:`studyloop.history.spaced_repetition_due` and
    ``get_struggling_topics``; ``study_sessions`` — session cadence, via
    ``get_study_session_stats``.

*Session-DB tables* (the cross-harness conversation archive)
    ``messages`` / ``messages_fts`` — what was actually discussed, via
    :func:`studyloop.history.topic_frequency` and ``struggle_topics``.

Three phases, three questions:

``start``
    Is this plan still the right thing to work on, and what is next?
``mid``
    Is this session drifting off the plan?
``end``
    What did this session move, and what does the plan owe next time?
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime

from .models import CHECKPOINT_PHASES, Checkpoint, StudyPlan, utc_now_iso

logger = logging.getLogger(__name__)

#: A plan untouched for longer than this is treated as stalled.
STALE_DAYS = 14

#: Milestones marked done whose concepts carry no confidence evidence.
UNVERIFIED_LABEL = "claimed-done-without-evidence"


@dataclass
class ConceptEvidence:
    """What the databases know about one plan concept."""

    concept: str
    confidence: str = ""
    last_studied: str = ""
    days_ago: int | None = None
    mentions: int = 0
    struggling: bool = False
    source: str = "none"

    @property
    def has_evidence(self) -> bool:
        return bool(self.confidence) or self.mentions > 0


@dataclass
class PlanEvaluation:
    """The result of assessing a plan at one checkpoint."""

    plan_id: str
    plan_title: str
    phase: str
    verdict: str = "on-track"
    headline: str = ""
    at: str = field(default_factory=utc_now_iso)
    study_id: str = ""
    progress_pct: int = 0
    milestone_total: int = 0
    milestone_done: int = 0
    next_milestone: str = ""
    next_concepts: list[str] = field(default_factory=list)
    days_since_activity: int | None = None
    days_until_target: int | None = None
    due_reviews: list[dict] = field(default_factory=list)
    struggles: list[dict] = field(default_factory=list)
    concept_evidence: list[ConceptEvidence] = field(default_factory=list)
    unverified_milestones: list[str] = field(default_factory=list)
    drift_topics: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """JSON-serialisable view, used by the API and the checkpoint log."""
        data = asdict(self)
        data["concept_evidence"] = [asdict(c) for c in self.concept_evidence]
        return data

    def as_markdown(self) -> str:
        """Render the evaluation as the Markdown block agents paste into chat."""
        lines = [
            f"### Plan checkpoint — {self.plan_title} ({self.phase})",
            "",
            f"**Verdict:** {self.verdict} — {self.headline}",
            "",
            f"**Progress:** {self.milestone_done}/{self.milestone_total} milestones "
            f"({self.progress_pct}%)",
        ]
        if self.next_milestone:
            concepts = ", ".join(self.next_concepts) if self.next_concepts else "none listed"
            lines += ["", f"**Next milestone:** {self.next_milestone} (concepts: {concepts})"]
        if self.due_reviews:
            lines += ["", "**Due for review:**"]
            lines += [
                f"- {item.get('concept') or item.get('topic')} — {item.get('review_type', '')}"
                for item in self.due_reviews[:5]
            ]
        if self.struggles:
            lines += ["", "**Struggle signal:**"]
            lines += [f"- {item.get('topic')}" for item in self.struggles[:5]]
        if self.unverified_milestones:
            lines += ["", "**Marked done without evidence:**"]
            lines += [f"- {title}" for title in self.unverified_milestones]
        if self.drift_topics:
            lines += ["", f"**Off-plan topics seen:** {', '.join(self.drift_topics)}"]
        if self.recommendations:
            lines += ["", "**Do next:**"]
            lines += [f"{i}. {rec}" for i, rec in enumerate(self.recommendations, 1)]
        if self.warnings:
            lines += ["", "**Data gaps:**"]
            lines += [f"- {warning}" for warning in self.warnings]
        return "\n".join(lines) + "\n"

    def to_checkpoint(self) -> Checkpoint:
        """Convert to the Checkpoint row appended to the plan document."""
        return Checkpoint(
            phase=self.phase,
            verdict=self.verdict,
            at=self.at,
            summary=self.headline,
            study_id=self.study_id,
        )


# ---------------------------------------------------------------------------
# Evidence gathering — every reader is individually guarded so a missing table
# degrades the evaluation into a warning instead of an exception.
# ---------------------------------------------------------------------------


def _safe(label: str, fn, default, warnings: list[str]):
    try:
        return fn()
    except Exception:
        logger.debug("plan evaluation: %s unavailable", label, exc_info=True)
        warnings.append(f"{label} unavailable — evaluation is partial")
        return default


def _days_since(timestamp: str | None) -> int | None:
    if not timestamp:
        return None
    try:
        parsed = datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return max(0, (datetime.now(UTC) - parsed).days)


def _gather_concept_evidence(
    plan: StudyPlan, warnings: list[str]
) -> tuple[list[ConceptEvidence], list[dict], list[dict]]:
    """Return ``(concept_evidence, due_reviews, struggles)`` for a plan."""
    from studyloop import history

    keywords = plan.keywords() or [plan.title]

    due_all = _safe(
        "study_progress review dates",
        lambda: history.spaced_repetition_due(
            {t: plan.keywords() for t in plan.topics or ["plan"]}
        ),
        [],
        warnings,
    )
    struggles_all = _safe(
        "study_progress struggles",
        lambda: history.progress.get_struggling_topics(days=30),
        [],
        warnings,
    )
    mentions = _safe(
        "session message archive",
        lambda: history.topic_frequency(keywords, days=90),
        [],
        warnings,
    )

    plan_concepts = plan.all_concepts()
    lowered = {c.lower(): c for c in plan_concepts}

    # Only keep due/struggle rows that actually touch this plan.
    def _relevant(row: dict) -> bool:
        haystack = " ".join(
            str(row.get(key, "") or "") for key in ("topic", "concept", "source_section")
        ).lower()
        if any(word.lower() in haystack for word in plan.topics):
            return True
        return any(concept in haystack for concept in lowered)

    due_reviews = [row for row in due_all if _relevant(row)]
    struggles = [row for row in struggles_all if _relevant(row)]

    mention_counts: dict[str, int] = {}
    for row in mentions:
        snippet = str(row.get("snippet", "")).lower()
        for concept_lower in lowered:
            if concept_lower in snippet:
                mention_counts[concept_lower] = mention_counts.get(concept_lower, 0) + 1

    struggling_terms = {str(row.get("topic", "")).lower() for row in struggles if row.get("topic")}

    evidence: list[ConceptEvidence] = []
    for concept_lower, concept in lowered.items():
        due_row = next(
            (row for row in due_all if str(row.get("concept") or "").lower() == concept_lower),
            None,
        )
        item = ConceptEvidence(concept=concept)
        if due_row:
            item.confidence = str(due_row.get("confidence") or "")
            item.last_studied = str(due_row.get("last_studied") or "")
            days_ago = due_row.get("days_ago")
            item.days_ago = int(days_ago) if isinstance(days_ago, int) else None
            item.source = "study_progress"
        item.mentions = mention_counts.get(concept_lower, 0)
        if item.mentions and item.source == "none":
            item.source = "session_messages"
        item.struggling = item.confidence == "struggling" or any(
            term and (term in concept_lower or concept_lower in term) for term in struggling_terms
        )
        evidence.append(item)

    return evidence, due_reviews, struggles


def _detect_drift(plan: StudyPlan, warnings: list[str]) -> list[str]:
    """Topics dominating recent sessions that the plan does not claim."""
    from studyloop import history

    recent = _safe(
        "cross-session struggle topics",
        lambda: history.struggle_topics(days=14, min_sessions=2),
        [],
        warnings,
    )
    owned = {word.lower() for word in plan.keywords()}
    drift: list[str] = []
    for row in recent:
        topic = str(row.get("topic", "")).strip()
        if not topic:
            continue
        low = topic.lower()
        if any(low in word or word in low for word in owned):
            continue
        drift.append(topic)
    return drift[:5]


# ---------------------------------------------------------------------------
# Verdict + recommendations
# ---------------------------------------------------------------------------


def _decide_verdict(
    plan: StudyPlan,
    *,
    days_since_activity: int | None,
    unverified: list[str],
    struggles: list[dict],
) -> tuple[str, str]:
    """Return ``(verdict, headline)`` from the gathered signals."""
    if plan.status == "complete" or (
        plan.milestones and plan.milestone_done == plan.milestone_total
    ):
        return "complete", "Every milestone is checked off — time to close or extend the plan."

    if days_since_activity is not None and days_since_activity >= STALE_DAYS:
        return (
            "stalled",
            f"No plan-related activity for {days_since_activity} days — restart small.",
        )

    days_left = plan.days_until_target()
    remaining = plan.milestone_total - plan.milestone_done
    if days_left is not None and days_left < 0:
        return "at-risk", f"Target date passed {abs(days_left)} days ago with {remaining} left."
    if days_left is not None and remaining > 0 and days_left < remaining:
        return (
            "at-risk",
            f"{remaining} milestones left but only {days_left} days to target.",
        )
    if unverified:
        return (
            "at-risk",
            f"{len(unverified)} milestone(s) marked done with no confidence evidence.",
        )
    if struggles:
        return "at-risk", f"Struggle signal on {len(struggles)} plan topic(s)."
    if plan.milestone_total == 0:
        return "at-risk", "Plan has no milestones — it cannot be tracked yet."
    return "on-track", f"{plan.progress_pct}% complete and moving."


def _recommend(
    plan: StudyPlan,
    phase: str,
    evaluation: PlanEvaluation,
) -> list[str]:
    """Concrete next actions, ordered — never more than four (working memory)."""
    recs: list[str] = []

    if phase == "start":
        if not plan.mission.is_populated():
            recs.append("Interview the learner for the mission — why this plan exists.")
        if plan.milestone_total == 0:
            recs.append("Break the mission into 3-6 checkable milestones before teaching.")
        for item in evaluation.due_reviews[:2]:
            label = item.get("concept") or item.get("topic")
            recs.append(
                f"Open with retrieval practice on '{label}' ({item.get('review_type', '')})."
            )
        nxt = plan.next_milestone()
        if nxt:
            recs.append(f"Then work the next milestone: {nxt.title}.")
        if evaluation.verdict == "stalled":
            recs.append("Pick the smallest possible win to rebuild momentum.")

    elif phase == "mid":
        nxt = plan.next_milestone()
        if evaluation.drift_topics:
            recs.append(
                "Session is drifting toward "
                f"{', '.join(evaluation.drift_topics[:2])} — park it or re-scope the plan."
            )
        if nxt:
            recs.append(f"Check progress against the current milestone: {nxt.title}.")
        recs.append("Ask for a teach-back on what has been covered so far.")

    else:  # end
        recs.append("Record per-concept confidence with `studyloop progress`.")
        if evaluation.unverified_milestones:
            recs.append("Verify or un-check: " + ", ".join(evaluation.unverified_milestones[:2]))
        nxt = plan.next_milestone()
        if nxt:
            recs.append(f"Set next session's target: {nxt.title}.")
        recs.append(f"Schedule the next plan review in {plan.review_cadence_days} day(s).")
        if evaluation.verdict == "complete":
            recs.append("Close the plan or extend it with a follow-on mission.")

    return recs[:4]


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def evaluate_plan(
    plan: StudyPlan,
    phase: str = "start",
    *,
    study_id: str = "",
) -> PlanEvaluation:
    """Evaluate ``plan`` at ``phase`` against the study and session databases.

    Never raises for missing data: unavailable evidence lands in
    :attr:`PlanEvaluation.warnings` so the caller can still act on what is
    known.
    """
    if phase not in CHECKPOINT_PHASES:
        msg = f"phase must be one of {CHECKPOINT_PHASES}, got {phase!r}"
        raise ValueError(msg)

    warnings: list[str] = []
    evidence, due_reviews, struggles = _gather_concept_evidence(plan, warnings)

    from studyloop import history

    last_activity = _safe(
        "last-studied lookup",
        lambda: history.last_studied(plan.keywords() or [plan.title]),
        None,
        warnings,
    )
    days_since_activity = _days_since(last_activity)

    by_concept = {item.concept.lower(): item for item in evidence}
    unverified = [
        milestone.title
        for milestone in plan.milestones
        if milestone.done
        and milestone.concept_set()
        and not any(
            by_concept.get(concept, ConceptEvidence(concept)).has_evidence
            for concept in milestone.concept_set()
        )
    ]

    drift = _detect_drift(plan, warnings) if phase in {"mid", "end"} else []

    verdict, headline = _decide_verdict(
        plan,
        days_since_activity=days_since_activity,
        unverified=unverified,
        struggles=struggles,
    )

    nxt = plan.next_milestone()
    evaluation = PlanEvaluation(
        plan_id=plan.plan_id,
        plan_title=plan.title,
        phase=phase,
        verdict=verdict,
        headline=headline,
        study_id=study_id,
        progress_pct=plan.progress_pct,
        milestone_total=plan.milestone_total,
        milestone_done=plan.milestone_done,
        next_milestone=nxt.title if nxt else "",
        next_concepts=list(nxt.concepts) if nxt else [],
        days_since_activity=days_since_activity,
        days_until_target=plan.days_until_target(),
        due_reviews=due_reviews[:10],
        struggles=struggles[:10],
        concept_evidence=evidence,
        unverified_milestones=unverified,
        drift_topics=drift,
        warnings=warnings,
    )
    evaluation.recommendations = _recommend(plan, phase, evaluation)
    return evaluation


def evaluate_and_record(
    plan: StudyPlan,
    phase: str = "start",
    *,
    study_id: str = "",
    append_to_plan: bool = True,
) -> PlanEvaluation:
    """Evaluate a plan, log the checkpoint, and append it to the document.

    The DB write and the Markdown write are independent: either can fail
    without losing the other, and the evaluation is always returned.
    """
    evaluation = evaluate_plan(plan, phase, study_id=study_id)

    try:
        from .index import record_checkpoint

        record_checkpoint(evaluation, study_id=study_id)
    except Exception:
        logger.debug("checkpoint DB write failed", exc_info=True)
        evaluation.warnings.append("checkpoint not saved to the database")

    if append_to_plan:
        try:
            from .store import save_plan

            plan.checkpoints.append(evaluation.to_checkpoint())
            save_plan(plan)
        except Exception:
            logger.debug("checkpoint markdown write failed", exc_info=True)
            evaluation.warnings.append("checkpoint not appended to the plan document")

    return evaluation
