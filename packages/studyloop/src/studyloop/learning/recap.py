"""Daily learning recap synthesis."""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class DailyRecap:
    win: str
    repair_target: str
    due_item: str
    next_action: str
    has_data: bool
    #: How the next action relates to the learner's active study plans, and
    #: which plan milestones today's energy deferred — rendering of what the
    #: decision engine already ranked, never a second ranking. Empty when no
    #: plan is active, and then absent from :meth:`to_json_dict` and
    #: :meth:`speakable_text` so a plan-less recap is what it always was.
    plan_context: str = ""

    def to_json_dict(self) -> dict:
        data = asdict(self)
        if not self.plan_context:
            del data["plan_context"]
        return data

    def speakable_text(self) -> str:
        text = (
            f"Win: {self.win}. "
            f"Repair target: {self.repair_target}. "
            f"Due item: {self.due_item}. "
            f"Next action: {self.next_action}."
        )
        if self.plan_context:
            text += f" Plan: {self.plan_context}"
        return text


def _plan_context(plan) -> str:
    """Describe the engine's plan guidance for the recap — show, do not re-rank.

    Reads the additive ``NowPlan`` fields defensively so a plan object from
    an older caller or a test double without them renders an empty context.
    """
    plans = {entry.plan_id: entry for entry in getattr(plan, "active_plans", ())}
    sentences: list[str] = []

    advances: list[str] = []
    for ref in getattr(getattr(plan, "primary", None), "plan_refs", ()):
        entry = plans.get(ref.plan_id)
        label = entry.title if entry is not None else ref.plan_id
        if ref.milestone_index is not None:
            label += f" (milestone {ref.milestone_index + 1}"
            if entry is not None and entry.next_milestone_index == ref.milestone_index:
                label += f", {entry.next_milestone}"
            label += ")"
        advances.append(label)
    if advances:
        sentences.append(f"The next action advances {'; '.join(advances)}.")

    for deferred in getattr(plan, "energy_deferred", ()):
        sentences.append(
            f"Milestone {deferred.milestone_index + 1} of {deferred.plan_title}, "
            f"{deferred.title}, waits for more energy: it needs {deferred.energy_floor} of 10 "
            f"and today's energy carries {deferred.energy_capability}."
        )
    for completion in getattr(plan, "completion_actions", ()):
        sentences.append(completion.action)
    return " ".join(sentences)


def build_daily_recap() -> DailyRecap:
    """Build today's compact recap from progress, review, and now signals."""
    try:
        from studyloop.cli._shared import TOPIC_KEYWORDS
        from studyloop.history import get_wins, spaced_repetition_due
        from studyloop.history.progress import get_struggling_topics
        from studyloop.learning.decision import build_now_plan
    except Exception:
        return DailyRecap(
            win="No local learning data was available",
            repair_target="Pick one tiny concept to retrieve",
            due_item="No due item found",
            next_action="Run studyloop now",
            has_data=False,
        )

    wins = get_wins(days=1)
    struggles = get_struggling_topics(days=7)
    due = spaced_repetition_due(TOPIC_KEYWORDS)
    plan = build_now_plan()

    has_data = bool(wins or struggles or due or not plan.starter)
    win = (
        f"{wins[0]['concept']} in {wins[0]['topic']}"
        if wins
        else "You kept the loop alive by checking in"
    )
    repair = f"{struggles[0]['topic']}" if struggles else plan.primary.concept
    due_item = (
        f"{due[0].get('concept') or due[0].get('topic')} ({due[0].get('review_type')})"
        if due
        else "Nothing overdue"
    )
    return DailyRecap(
        win=win,
        repair_target=repair,
        due_item=due_item,
        next_action=plan.primary.evidence_command,
        has_data=has_data,
        plan_context=_plan_context(plan),
    )
