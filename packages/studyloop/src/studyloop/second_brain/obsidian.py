"""Obsidian provider: projections of plans and of today's study into a vault.

This module is imported ONLY from inside
:func:`studyloop.second_brain.factory.get_backend`, after configuration has
selected ``provider: obsidian``. ``tests/test_second_brain_optionality.py``
asserts it is absent from ``sys.modules`` on every disabled path — which is a
real assertion precisely because the module exists.

What lands here in this commit is the part that answers questions: whether the
configured vault is reachable, and what the backend can do. The writer — path
containment, the ownership marker, atomic replacement, idempotence — arrives
with the projection renderers in the next step, so the operations below refuse
rather than half-write.
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

if TYPE_CHECKING:
    from studyloop.settings import SecondBrainConfig

logger = logging.getLogger(__name__)

_WRITER_PENDING = "Obsidian publishing is not available in this build."


class ObsidianBackend:
    """Writes StudyLoop-owned notes under ``<vault_path>/<folder>/``.

    Holds the resolved :class:`~studyloop.settings.SecondBrainConfig` rather
        than re-reading settings, so one command cannot see two different vaults
    if the config changes underneath it.
    """

    provider = "obsidian"

    def __init__(self, config: SecondBrainConfig) -> None:
        self._config = config

    # -- introspection ------------------------------------------------------

    @property
    def vault_root(self) -> Path:
        """The vault as configured, expanded but not resolved.

        Deliberately not ``resolve()``d here: containment checks re-resolve
        immediately before each write, because a symlink can change between a
        check and a write.
        """
        return Path(self._config.vault_path).expanduser()

    def is_available(self) -> bool:
        """True when the vault is a directory this process can write into.

        A vault on an unmounted drive, or one the learner has moved, is a
        runtime condition to report — never an import-time or construction-time
        failure, because ``studyloop brain status`` has to be able to say so.
        """
        root = self.vault_root
        return root.is_dir() and os.access(root, os.W_OK)

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
            # The EFFECTIVE mode, not the configured one. The optional CLI
            # adapter that resolves ``auto`` lands with the writer; until then
            # the file writer is always what runs, so reporting anything else
            # here would be a claim the code cannot honour.
            use_cli=False,
            detail=detail,
        )

    # -- operations ---------------------------------------------------------

    def publish_plan(self, plan_id: str) -> PublishResult:
        raise SecondBrainError(_WRITER_PENDING)

    def publish_today(self) -> PublishResult:
        raise SecondBrainError(_WRITER_PENDING)

    def publish_learning_record(self, plan_id: str, record_number: int) -> PublishResult:
        raise SecondBrainError(_WRITER_PENDING)

    def pull_notes(self, plan_id: str) -> PullNotesResult:
        raise SecondBrainError(_WRITER_PENDING)


__all__ = ["ObsidianBackend"]
