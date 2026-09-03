"""Obsidian provider: projections of plans and of today's study into a vault.

This module is imported ONLY from inside
:func:`studyloop.second_brain.factory.get_backend`, after configuration has
selected ``provider: obsidian``. ``tests/test_second_brain_optionality.py``
asserts it is absent from ``sys.modules`` on every disabled path — a real
assertion precisely because the module exists.

The backend is the thin part. It decides WHAT to publish and gathers the data;
the rendering is pure (:mod:`~studyloop.second_brain.projection`), the writing is
one guarded module (:mod:`~studyloop.second_brain.obsidian_writer`), and the
optional CLI is one adapter (:mod:`~studyloop.second_brain.obsidian_cli`). Keeping
those apart is what makes the safety rules testable in isolation from the
question of which notes a wind-down should produce.

Layout inside ``<vault>/<folder>/`` (``Study`` by default)::

    Plans/<plan_id>.md              StudyLoop's, regenerated
    Plans/<plan_id>.notes.md        the learner's, read only on `brain pull`
    Learning Records/<plan_id>/LR-0001.md   StudyLoop's, regenerated
    Today.md                        StudyLoop's, replaced

Nothing here writes to the plan document. That is asserted for every backend by
``tests/test_second_brain_backend_contract.py``.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING

from studyloop.second_brain.core import (
    BrainDescription,
    PublishResult,
    PullNotesResult,
    SecondBrainError,
)
from studyloop.second_brain.obsidian_writer import (
    WriteOutcome,
    projection_path,
    read_user_note,
    write_projection,
)
from studyloop.second_brain.projection import (
    MAX_DUE_CARDS,
    MAX_FOCUS_TOPICS,
    ProjectionIdentity,
    TodayData,
    render_learning_record_projection,
    render_plan_projection,
    render_today,
)

if TYPE_CHECKING:
    from studyloop.planning.models import StudyPlan
    from studyloop.second_brain.obsidian_writer import VaultTarget
    from studyloop.settings import SecondBrainConfig

logger = logging.getLogger(__name__)

#: How the projection records where its content came from.
#:
#: A portable label, deliberately not an absolute path: this string is written
#: into a file that may be synced to a phone, and an absolute path would carry the
#: machine's home directory with it.
SOURCE_LABEL = "STUDYLOOP_PLANS_DIR/{plan_id}.md"

TODAY_RELATIVE = "Today.md"


class ObsidianBackend:
    """Writes StudyLoop-owned notes under ``<vault_path>/<folder>/``.

    Holds the resolved :class:`~studyloop.settings.SecondBrainConfig` rather than
    re-reading settings, so one command cannot see two different vaults if the
    config changes underneath it.
    """

    provider = "obsidian"

    def __init__(self, config: SecondBrainConfig) -> None:
        self._config = config

    # -- introspection ------------------------------------------------------

    @property
    def vault_root(self) -> Path:
        """The vault as configured, expanded but not resolved.

        Deliberately not resolved here: containment is re-checked immediately
        before each write, because a symlink can change between a check and a
        write.
        """
        return Path(self._config.vault_path).expanduser()

    def is_available(self) -> bool:
        """True when the vault is a directory this process can write into.

        A vault on an unmounted drive, or one the learner has moved, is a runtime
        condition to report — never a construction-time failure, because
        ``studyloop brain status`` has to be able to say so.
        """
        root = self.vault_root
        return root.is_dir() and os.access(root, os.W_OK)

    def effective_cli_mode(self) -> str:
        """``"cli"`` or ``"files"`` for this moment.

        Resolved on demand rather than cached: the answer depends on whether the
        desktop app is running, which changes while StudyLoop is not looking.
        """
        from studyloop.second_brain.obsidian_cli import resolve_cli_mode

        return resolve_cli_mode(self._config)

    def describe(self) -> BrainDescription:
        available = self.is_available()
        if available:
            detail = f"Publishing into {self._config.folder}/ inside the configured vault."
        else:
            detail = (
                f"Vault path is not a writable directory: {self.vault_root}. "
                "Mount it, or point second_brain.vault_path somewhere else."
            )
        return BrainDescription(
            provider=self.provider,
            configured=True,
            available=available,
            supports_publish=True,
            supports_pull_notes=True,
            vault_path=str(self.vault_root),
            folder=self._config.folder,
            # The EFFECTIVE mode, not the configured one: `auto` is not an answer
            # a learner can act on. Probed only when the vault is usable, so a
            # status call on a missing vault never spawns anything.
            use_cli=self.effective_cli_mode() == "cli" if available else False,
            detail=detail,
        )

    # -- helpers ------------------------------------------------------------

    def _target(self, relative: str) -> VaultTarget:
        return projection_path(self.vault_root, self._config.folder, relative)

    def _load(self, plan_id: str) -> StudyPlan:
        """Load a plan, turning every store failure into ``SecondBrainError``.

        The CLI maps that to one line and exit 1. A ``PlanNotFoundError`` reaching
        the surface would read as a bug in the second-brain layer rather than a
        mistyped plan id.
        """
        from studyloop.planning.store import (
            InvalidPlanIdError,
            PlanNotFoundError,
            load_plan,
            validate_plan_id,
        )

        try:
            # Normalises case and separators, so two spellings of one id cannot
            # produce two projections of the same plan.
            valid_id = validate_plan_id(plan_id)
            return load_plan(valid_id)
        except InvalidPlanIdError as exc:
            raise SecondBrainError(f"Not a usable plan id: {plan_id!r}.") from exc
        except PlanNotFoundError as exc:
            raise SecondBrainError(f"No such plan: {plan_id!r}.") from exc

    def _identity(self, kind, plan_id: str | None, record: int | None = None) -> ProjectionIdentity:
        return ProjectionIdentity(
            kind=kind,
            plan_id=plan_id,
            learning_record=record,
            source=SOURCE_LABEL.format(plan_id=plan_id) if plan_id else "studyloop",
        )

    def _install(
        self,
        target: VaultTarget,
        rendered: str,
        identity: ProjectionIdentity,
    ) -> tuple[WriteOutcome, tuple[str, ...]]:
        """Write one projection, letting Obsidian create it first when it can.

        When the CLI is usable, an ABSENT note is created through Obsidian so the
        learner's own template and plugin hooks fire; the canonical bytes are then
        installed by the writer regardless. Those hooks are therefore transient by
        design — the final content is always the projection, which is what makes
        the idempotence check meaningful.
        """
        warnings: list[str] = []
        if not target.path.exists() and self.effective_cli_mode() == "cli":
            from studyloop.second_brain.obsidian_cli import create_note

            if not create_note(self._config, target.relative, rendered):
                warnings.append(
                    f"Obsidian could not create '{target.relative}'; wrote the file directly."
                )
        return write_projection(target, rendered, identity), tuple(warnings)

    def _bucket(
        self, outcome: WriteOutcome, target: VaultTarget
    ) -> tuple[tuple[str, ...], tuple[str, ...]]:
        if outcome is WriteOutcome.WRITTEN:
            return (target.relative,), ()
        return (), (target.relative,)

    def _require_available(self) -> None:
        if not self.is_available():
            raise SecondBrainError(
                f"Vault path does not exist or is not writable: {self.vault_root}. "
                "Mount it, or run: studyloop brain enable obsidian --vault <new path>"
            )

    def _backlink_footer(self, plan: StudyPlan) -> str:
        from studyloop.second_brain.backlinks import wikilinks_for

        links = wikilinks_for(plan, self.vault_root, enabled=self._config.backlinks)
        if not links:
            return ""
        return "\n## Related notes\n\n" + "\n".join(f"- {link}" for link in links) + "\n"

    # -- operations ---------------------------------------------------------

    def publish_plan(self, plan_id: str) -> PublishResult:
        """Write the plan's projection, and one note per learning record."""
        self._require_available()
        plan = self._load(plan_id)

        written: list[str] = []
        unchanged: list[str] = []
        warnings: list[str] = []

        identity = self._identity("plan-projection", plan.plan_id)
        rendered = render_plan_projection(plan, identity) + self._backlink_footer(plan)
        target = self._target(f"Plans/{plan.plan_id}.md")
        outcome, notes = self._install(target, rendered, identity)
        warnings.extend(notes)
        first, second = self._bucket(outcome, target)
        written.extend(first)
        unchanged.extend(second)

        for record in plan.learning_records:
            record_identity = self._identity(
                "learning-record-projection", plan.plan_id, record.number
            )
            record_target = self._target(
                f"Learning Records/{plan.plan_id}/LR-{record.number:04d}.md"
            )
            record_outcome, record_notes = self._install(
                record_target,
                render_learning_record_projection(plan, record, record_identity),
                record_identity,
            )
            warnings.extend(record_notes)
            first, second = self._bucket(record_outcome, record_target)
            written.extend(first)
            unchanged.extend(second)

        return PublishResult(
            provider=self.provider,
            operation="publish_plan",
            written=tuple(written),
            unchanged=tuple(unchanged),
            warnings=tuple(warnings),
        )

    def publish_today(self) -> PublishResult:
        """Replace ``Today.md`` with the current next action and due reviews."""
        self._require_available()
        identity = self._identity("today-projection", None)
        target = self._target(TODAY_RELATIVE)
        outcome, warnings = self._install(
            target, render_today(self._today_data(), identity), identity
        )
        written, unchanged = self._bucket(outcome, target)

        extra: list[str] = list(warnings)
        if self._config.daily_note:
            from studyloop.second_brain.obsidian_cli import daily_append
            from studyloop.settings import load_settings

            # The daily note is the learner's file. It is linked, at most once a
            # day, only with both opt-ins in place; the stamp lives in the state
            # directory so no bookkeeping file is written into the vault.
            daily_append(self._config, load_settings().state_dir)

        return PublishResult(
            provider=self.provider,
            operation="publish_today",
            written=written,
            unchanged=unchanged,
            warnings=tuple(extra),
        )

    def publish_learning_record(self, plan_id: str, record_number: int) -> PublishResult:
        """Write one learning record's note."""
        self._require_available()
        plan = self._load(plan_id)
        record = next((r for r in plan.learning_records if r.number == record_number), None)
        if record is None:
            raise SecondBrainError(
                f"Plan {plan.plan_id!r} has no learning record LR-{record_number:04d}."
            )

        identity = self._identity("learning-record-projection", plan.plan_id, record.number)
        target = self._target(f"Learning Records/{plan.plan_id}/LR-{record.number:04d}.md")
        outcome, warnings = self._install(
            target, render_learning_record_projection(plan, record, identity), identity
        )
        written, unchanged = self._bucket(outcome, target)
        return PublishResult(
            provider=self.provider,
            operation="publish_learning_record",
            written=written,
            unchanged=unchanged,
            warnings=warnings,
        )

    def pull_notes(self, plan_id: str) -> PullNotesResult:
        """Read the learner's sibling note for a plan. Never writes anything.

        The sibling file is the learner's half of the conversation: StudyLoop owns
        ``Plans/<id>.md`` and regenerates it, so a learner's own thoughts need a
        place that is never overwritten. It is created by the learner, not by
        StudyLoop — an empty file created "helpfully" would be one more piece of
        StudyLoop clutter in a vault.
        """
        from studyloop.planning.store import validate_plan_id

        try:
            valid_id = validate_plan_id(plan_id)
        except Exception as exc:
            raise SecondBrainError(f"Not a usable plan id: {plan_id!r}.") from exc

        target = self._target(f"Plans/{valid_id}.notes.md")
        text = read_user_note(target)
        if text is None:
            return PullNotesResult(
                provider=self.provider,
                plan_id=valid_id,
                found=False,
                warnings=(f"No user notes at '{target.relative}'",),
            )
        return PullNotesResult(
            provider=self.provider,
            plan_id=valid_id,
            found=True,
            notes=text,
            sources=(target.relative,),
        )

    # -- today's data -------------------------------------------------------

    def _today_data(self) -> TodayData:
        """Gather what ``Today.md`` shows.

        Every source is best-effort. A learner with no review database, no focus
        filter and no history should still get a Today note — one that says there
        is nothing scheduled — rather than an error, because the note's job is to
        lower the cost of starting.
        """
        from studyloop.learning.decision import build_now_plan

        primary = ""
        reason = ""
        minutes = 25
        alternates: tuple[str, ...] = ()
        try:
            now_plan = build_now_plan()
        except Exception as exc:
            logger.debug("could not build a now-plan for Today.md: %s", exc)
        else:
            primary = now_plan.primary.concept
            reason = now_plan.primary.reason
            minutes = now_plan.primary.estimated_minutes
            alternates = tuple(item.concept for item in now_plan.alternates)

        due: tuple[dict, ...] = ()
        try:
            from studyloop.learning.review_service import due_cards

            due = tuple(due_cards(limit=MAX_DUE_CARDS))
        except Exception as exc:
            logger.debug("could not read due cards for Today.md: %s", exc)

        topics: tuple[str, ...] = ()
        try:
            from studyloop.focus import get_focus

            topics = tuple(get_focus().topics)[:MAX_FOCUS_TOPICS]
        except Exception as exc:
            logger.debug("could not read focus topics for Today.md: %s", exc)

        return TodayData(
            primary=primary,
            primary_reason=reason,
            primary_minutes=minutes,
            alternates=tuple(a for a in alternates if a),
            due_cards=due,
            focus_topics=topics,
        )


__all__ = ["SOURCE_LABEL", "TODAY_RELATIVE", "ObsidianBackend"]
