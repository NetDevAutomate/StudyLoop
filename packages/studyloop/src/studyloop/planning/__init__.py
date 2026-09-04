"""Study-plan authoring, storage, and evaluation.

Structured Markdown documents are the source of truth; the sessions DB holds a
derived index plus an append-only checkpoint log.  A plan is evaluated at three
points in every session that runs against it: ``start``, ``mid``, ``end``.

Shape credit: Matt Pocock's ``teach`` skill
(https://github.com/mattpocock/skills/tree/main/skills/productivity/teach) —
mission-first, learning records as ADRs, primary sources over recall.
"""

from __future__ import annotations

from .authoring import (
    INTERVIEW,
    InterviewQuestion,
    draft_plan,
    interview_spec,
    readiness,
    seed_from_history,
)
from .evaluation import (
    CHECKPOINT_PHASES,
    ConceptEvidence,
    PlanEvaluation,
    evaluate_and_record,
    evaluate_plan,
)
from .index import checkpoint_history, indexed_plans, reindex_all
from .markdown import (
    MISSION_SUBSECTION_HEADINGS,
    PLAN_SECTION_HEADINGS,
    parse_plan,
    render_plan,
)
from .models import (
    PLAN_STATUSES,
    Checkpoint,
    LearningRecord,
    Milestone,
    Mission,
    Resource,
    StudyPlan,
    slugify,
)
from .multiplexer import (
    HerdrBackend,
    Multiplexer,
    TmuxBackend,
    available_backends,
    preferred_backend,
)
from .store import (
    InvalidPlanIdError,
    PlanExistsError,
    PlanNotFoundError,
    create_plan,
    delete_plan,
    list_plan_ids,
    list_plans,
    load_plan,
    load_plan_text,
    plan_path,
    plans_dir,
    save_plan,
    unique_plan_id,
)

__all__ = [
    "CHECKPOINT_PHASES",
    "INTERVIEW",
    "MISSION_SUBSECTION_HEADINGS",
    "PLAN_SECTION_HEADINGS",
    "PLAN_STATUSES",
    "Checkpoint",
    "ConceptEvidence",
    "HerdrBackend",
    "InterviewQuestion",
    "InvalidPlanIdError",
    "LearningRecord",
    "Milestone",
    "Mission",
    "Multiplexer",
    "PlanEvaluation",
    "PlanExistsError",
    "PlanNotFoundError",
    "Resource",
    "StudyPlan",
    "TmuxBackend",
    "available_backends",
    "checkpoint_history",
    "create_plan",
    "delete_plan",
    "draft_plan",
    "evaluate_and_record",
    "evaluate_plan",
    "indexed_plans",
    "interview_spec",
    "list_plan_ids",
    "list_plans",
    "load_plan",
    "load_plan_text",
    "parse_plan",
    "plan_path",
    "plans_dir",
    "preferred_backend",
    "readiness",
    "reindex_all",
    "render_plan",
    "save_plan",
    "seed_from_history",
    "slugify",
    "unique_plan_id",
]
