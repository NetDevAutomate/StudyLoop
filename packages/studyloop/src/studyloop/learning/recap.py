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

    def to_json_dict(self) -> dict:
        return asdict(self)

    def speakable_text(self) -> str:
        return (
            f"Win: {self.win}. "
            f"Repair target: {self.repair_target}. "
            f"Due item: {self.due_item}. "
            f"Next action: {self.next_action}."
        )


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
    )
