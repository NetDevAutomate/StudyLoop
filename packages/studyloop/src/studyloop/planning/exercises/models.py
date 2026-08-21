"""Dataclasses for the three topic exercise formats.

Every generated topic carries exercises in three shapes:

``blank_slate``
    Requirements only. The learner writes the whole solution.
``completion``
    Requirements *plus* a partial solution. The learner finishes it.
``multiple_choice``
    Questions authored in Markdown, with one or more correct choices.

The two code formats are deliberately **one** model, not two.  They differ by
exactly one field — :attr:`CodeExercise.starter_code` — and are scored by the
same pipeline (:mod:`studyloop.planning.exercises.review`).  "How much starting
code is supplied" is a parameter, not a feature branch.

That parameterisation has a consequence the scorer must honour: a criterion the
starter code already satisfies is *given*, never earned.  Crediting it would let
a completion exercise score 90% for a solution the learner never wrote.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime

from ..models import slugify

#: The three exercise shapes every generated topic must provide.
EXERCISE_KINDS = ("blank_slate", "completion", "multiple_choice")

#: The two shapes that run through the shared review-and-score pipeline.
CODE_KINDS = ("blank_slate", "completion")

#: Confidence vocabulary shared with ``study_progress`` (see history.progress).
CONFIDENCE_LEVELS = ("struggling", "learning", "confident", "mastered")

#: Per-criterion outcomes.  Two of these carry design decisions:
#: ``given`` — the starter code already satisfied it, so it is excluded from the
#: score (a completion attempt must not inherit credit for supplied code).
#: ``unscoreable`` — the criterion has no ``check``/``forbid`` pattern, so nothing
#: can be verified.  Also excluded, because the alternative is worse: a vacuous
#: match awards full marks for any submission at all.
CRITERION_STATUSES = ("met", "unmet", "violated", "given", "unscoreable")

#: Score bands, high → low.  ``(floor, band, confidence)``.
SCORE_BANDS: tuple[tuple[int, str, str], ...] = (
    (90, "strong", "mastered"),
    (70, "solid", "confident"),
    (40, "developing", "learning"),
    (0, "struggling", "struggling"),
)

_TRIVIAL_LINE = re.compile(r"^\s*(#.*|\"\"\".*|'''.*|pass|\.\.\.|\}|\)|\]|)\s*$")


def utc_now_iso() -> str:
    """Current UTC time as a second-precision ISO-8601 string."""
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def band_for(score: int) -> tuple[str, str]:
    """Return ``(band, confidence)`` for a 0-100 ``score``."""
    for floor, band, confidence in SCORE_BANDS:
        if score >= floor:
            return band, confidence
    return "struggling", "struggling"  # pragma: no cover - SCORE_BANDS ends at 0


def substantive_lines(code: str) -> list[str]:
    """Lines of ``code`` that carry meaning, normalised for comparison.

    Blank lines, comments, bare ``pass``/``...`` and lone closing brackets are
    dropped: they are noise when deciding whether a learner actually authored
    anything beyond the scaffold they were handed.
    """
    out: list[str] = []
    for raw in (code or "").splitlines():
        line = raw.strip()
        if not line or _TRIVIAL_LINE.match(line):
            continue
        out.append(re.sub(r"\s+", " ", line))
    return out


@dataclass
class Criterion:
    """One rubric line: what the submission must show, and how to ask about it.

    ``check`` and ``forbid`` are case-insensitive regexes matched against the
    submission.  ``ask`` is the Socratic question raised when the criterion is
    not met — the mentoring path never states the fix, it asks the question that
    leads the learner to find it.
    """

    title: str
    weight: int = 1
    check: str = ""
    forbid: str = ""
    ask: str = ""

    def __post_init__(self) -> None:
        self.weight = max(1, int(self.weight))

    def _search(self, pattern: str, text: str) -> bool:
        if not pattern:
            return False
        try:
            return re.search(pattern, text or "", re.IGNORECASE | re.MULTILINE) is not None
        except re.error:
            # A hand-authored rubric can carry a broken regex.  Fall back to a
            # literal substring so one typo cannot make the whole exercise
            # unscoreable (and never raise into the learner's face).
            return pattern.lower() in (text or "").lower()

    def is_scoreable(self) -> bool:
        """True when this criterion can actually be verified against a submission.

        A criterion with neither ``check`` nor ``forbid`` describes an intention
        nobody automated.  Scoring it as met would hand full marks to an empty
        stub; scoring it as unmet would blame the learner for the author's gap.
        So it is neither — see the ``unscoreable`` status.
        """
        return bool(self.check or self.forbid)

    def is_met(self, text: str) -> bool:
        """True when ``text`` satisfies :attr:`check` (vacuously true if unset).

        Callers must gate this on :meth:`is_scoreable`; it is deliberately
        permissive so a ``forbid``-only criterion (nothing required, one thing
        banned) passes when the ban is respected.
        """
        return True if not self.check else self._search(self.check, text)

    def is_violated(self, text: str) -> bool:
        """True when ``text`` trips :attr:`forbid`."""
        return self._search(self.forbid, text)

    def question(self) -> str:
        """The Socratic prompt for this criterion, always question-shaped."""
        asked = (self.ask or "").strip()
        if not asked:
            asked = f"What in your solution is meant to show “{self.title}”"
        return asked if asked.endswith("?") else f"{asked}?"


@dataclass
class Choice:
    """One multiple-choice option.

    ``why`` on a *distractor* names the misconception it encodes.  That is what
    makes a wrong answer teachable: the review turns the misconception into a
    question instead of announcing the right letter.
    """

    text: str
    correct: bool = False
    why: str = ""


@dataclass
class MultipleChoiceQuestion:
    """A single multiple-choice question, authored in Markdown."""

    prompt: str
    choices: list[Choice] = field(default_factory=list)
    ask: str = ""

    @property
    def correct_indexes(self) -> list[int]:
        return [i for i, choice in enumerate(self.choices) if choice.correct]

    @property
    def is_multi_select(self) -> bool:
        return len(self.correct_indexes) > 1

    def is_answerable(self) -> bool:
        """True when the question has options and at least one correct answer."""
        return len(self.choices) >= 2 and bool(self.correct_indexes)

    def label(self, index: int) -> str:
        """``a``, ``b``, ``c``… for display and for agent transcripts."""
        return chr(ord("a") + index) if 0 <= index < 26 else str(index)


@dataclass
class CodeExercise:
    """A blank-slate *or* completion exercise — the difference is one field.

    ``starter_code`` empty  → blank slate: the learner creates the whole thing.
    ``starter_code`` present → completion: the learner finishes what is given.
    """

    kind: str
    title: str
    requirements: list[str] = field(default_factory=list)
    starter_code: str = ""
    rubric: list[Criterion] = field(default_factory=list)
    reference_solution: str = ""
    language: str = "python"

    def __post_init__(self) -> None:
        if self.kind not in CODE_KINDS:
            msg = f"kind must be one of {CODE_KINDS}, got {self.kind!r}"
            raise ValueError(msg)
        # Canonicalise code blocks to have no leading/trailing blank lines. A
        # fenced Markdown block cannot represent them, so without this the model
        # would hold a value the document can never round-trip back to.
        self.starter_code = self.starter_code.strip("\n")
        self.reference_solution = self.reference_solution.strip("\n")
        if self.kind == "blank_slate" and self.starter_code.strip():
            msg = "a blank_slate exercise cannot supply starter code"
            raise ValueError(msg)

    @property
    def scaffold_ratio(self) -> float:
        """Fraction of the reference solution handed over as starter code.

        0.0 for a blank slate; ~0.4 for a typical completion exercise.  This is
        the knob the design note asks for: one pipeline, parameterised by how
        much starting code is supplied.
        """
        reference = substantive_lines(self.reference_solution)
        if not reference:
            return 0.0
        starter = set(substantive_lines(self.starter_code))
        if not starter:
            return 0.0
        overlap = sum(1 for line in reference if line in starter)
        return round(min(1.0, overlap / len(reference)), 3)

    @property
    def total_weight(self) -> int:
        return sum(c.weight for c in self.rubric)

    def is_ready(self) -> bool:
        """True when the exercise can actually be attempted and scored."""
        return bool(self.requirements) and bool(self.rubric)

    def summary(self) -> dict:
        return {
            "kind": self.kind,
            "title": self.title,
            "language": self.language,
            "requirement_count": len(self.requirements),
            "rubric_count": len(self.rubric),
            "total_weight": self.total_weight,
            "has_starter_code": bool(self.starter_code.strip()),
            "scaffold_ratio": self.scaffold_ratio,
            "ready": self.is_ready(),
        }


@dataclass
class ExerciseSet:
    """All three exercise formats for one topic of a study plan."""

    set_id: str
    topic: str
    title: str = ""
    plan_id: str = ""
    concepts: list[str] = field(default_factory=list)
    created: str = field(default_factory=utc_now_iso)
    updated: str = field(default_factory=utc_now_iso)
    blank_slate: CodeExercise | None = None
    completion: CodeExercise | None = None
    multiple_choice: list[MultipleChoiceQuestion] = field(default_factory=list)
    notes: str = ""

    def __post_init__(self) -> None:
        if not self.title:
            self.title = self.topic
        if not self.set_id:
            self.set_id = slugify(f"{self.plan_id} {self.topic}" if self.plan_id else self.topic)

    def code_exercise(self, kind: str) -> CodeExercise | None:
        """Fetch one code exercise by kind, or None when absent."""
        if kind == "blank_slate":
            return self.blank_slate
        if kind == "completion":
            return self.completion
        return None

    def missing_formats(self) -> list[str]:
        """Which of the three required formats are absent or unusable.

        A topic is only fully exercised when all three shapes are present, so
        this is reported rather than silently tolerated.
        """
        missing: list[str] = []
        for kind in CODE_KINDS:
            exercise = self.code_exercise(kind)
            if exercise is None or not exercise.is_ready():
                missing.append(kind)
        if not any(q.is_answerable() for q in self.multiple_choice):
            missing.append("multiple_choice")
        return missing

    @property
    def is_complete(self) -> bool:
        return not self.missing_formats()

    def summary(self) -> dict:
        return {
            "set_id": self.set_id,
            "plan_id": self.plan_id,
            "topic": self.topic,
            "title": self.title,
            "concepts": list(self.concepts),
            "created": self.created,
            "updated": self.updated,
            "formats": {
                "blank_slate": self.blank_slate.summary() if self.blank_slate else None,
                "completion": self.completion.summary() if self.completion else None,
                "multiple_choice": {
                    "question_count": len(self.multiple_choice),
                    "answerable_count": sum(1 for q in self.multiple_choice if q.is_answerable()),
                },
            },
            "missing_formats": self.missing_formats(),
            "complete": self.is_complete,
        }


@dataclass
class CriterionResult:
    """How one rubric criterion fared against a submission."""

    title: str
    status: str
    weight: int
    question: str = ""

    def __post_init__(self) -> None:
        if self.status not in CRITERION_STATUSES:
            msg = f"status must be one of {CRITERION_STATUSES}, got {self.status!r}"
            raise ValueError(msg)

    @property
    def earned(self) -> int:
        return self.weight if self.status == "met" else 0

    @property
    def assessable(self) -> bool:
        """False for ``given`` (supplied code is not the learner's) and for
        ``unscoreable`` (the author left nothing to verify)."""
        return self.status not in {"given", "unscoreable"}

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "status": self.status,
            "weight": self.weight,
            "question": self.question,
            "earned": self.earned,
        }


@dataclass
class ExerciseReview:
    """The scored result of one attempt, plus the Socratic follow-up.

    :attr:`mentoring` holds questions only.  Nothing here reveals the reference
    solution — see :func:`studyloop.planning.exercises.review.review_code`.
    """

    set_id: str
    kind: str
    topic: str
    score: int
    band: str
    confidence: str
    criteria: list[CriterionResult] = field(default_factory=list)
    mentoring: list[str] = field(default_factory=list)
    strengths: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    authored_line_count: int = 0
    scaffold_ratio: float = 0.0
    at: str = field(default_factory=utc_now_iso)

    @property
    def met(self) -> list[CriterionResult]:
        return [c for c in self.criteria if c.status == "met"]

    @property
    def outstanding(self) -> list[CriterionResult]:
        return [c for c in self.criteria if c.status in {"unmet", "violated"}]

    @property
    def given(self) -> list[CriterionResult]:
        return [c for c in self.criteria if c.status == "given"]

    def to_dict(self) -> dict:
        return {
            "set_id": self.set_id,
            "kind": self.kind,
            "topic": self.topic,
            "score": self.score,
            "band": self.band,
            "confidence": self.confidence,
            "criteria": [c.to_dict() for c in self.criteria],
            "mentoring": list(self.mentoring),
            "strengths": list(self.strengths),
            "warnings": list(self.warnings),
            "authored_line_count": self.authored_line_count,
            "scaffold_ratio": self.scaffold_ratio,
            "given_count": len(self.given),
            "outstanding_count": len(self.outstanding),
            "at": self.at,
        }

    def as_markdown(self) -> str:
        """Agent-pasteable block: score, what held, then questions to ask."""
        out = [
            f"### Exercise review — {self.topic} ({self.kind.replace('_', ' ')})",
            "",
            f"**Score {self.score}/100 — {self.band}** (confidence signal: {self.confidence})",
            "",
        ]
        if self.strengths:
            out.append("**Holding up**")
            out.extend(f"- {item}" for item in self.strengths)
            out.append("")
        if self.given:
            out.append(
                f"_{len(self.given)} criterion(s) were satisfied by the supplied "
                "starter code and are excluded from the score._"
            )
            out.append("")
        if self.mentoring:
            out.append("**Ask, do not tell** — work through these in order")
            out.extend(f"{i}. {q}" for i, q in enumerate(self.mentoring, 1))
            out.append("")
        if self.warnings:
            out.append("**Caveats**")
            out.extend(f"- {item}" for item in self.warnings)
            out.append("")
        return "\n".join(out)


@dataclass
class ChoiceResult:
    """One graded multiple-choice answer."""

    prompt: str
    selected: list[int]
    correct: list[int]
    is_correct: bool
    question: str = ""
    misconceptions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "prompt": self.prompt,
            "selected": list(self.selected),
            "correct_count": len(self.correct),
            "is_correct": self.is_correct,
            "question": self.question,
            "misconceptions": list(self.misconceptions),
        }


@dataclass
class QuizReview:
    """The scored result of a multiple-choice attempt."""

    set_id: str
    topic: str
    score: int
    band: str
    confidence: str
    total: int
    correct_count: int
    results: list[ChoiceResult] = field(default_factory=list)
    mentoring: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    at: str = field(default_factory=utc_now_iso)
    kind: str = "multiple_choice"

    def to_dict(self) -> dict:
        return {
            "set_id": self.set_id,
            "kind": self.kind,
            "topic": self.topic,
            "score": self.score,
            "band": self.band,
            "confidence": self.confidence,
            "total": self.total,
            "correct_count": self.correct_count,
            "results": [r.to_dict() for r in self.results],
            "mentoring": list(self.mentoring),
            "warnings": list(self.warnings),
            "at": self.at,
        }

    def as_markdown(self) -> str:
        out = [
            f"### Quiz review — {self.topic}",
            "",
            f"**{self.correct_count}/{self.total} correct — {self.score}/100, "
            f"{self.band}** (confidence signal: {self.confidence})",
            "",
        ]
        if self.mentoring:
            out.append("**Ask, do not tell**")
            out.extend(f"{i}. {q}" for i, q in enumerate(self.mentoring, 1))
            out.append("")
        if self.warnings:
            out.append("**Caveats**")
            out.extend(f"- {item}" for item in self.warnings)
            out.append("")
        return "\n".join(out)
