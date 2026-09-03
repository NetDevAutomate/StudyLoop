"""Optional second-brain layer: projections of study plans into a vault.

Import boundary, deliberately enforced: this package's ``__init__`` re-exports
from :mod:`studyloop.second_brain.core` and :mod:`studyloop.second_brain.factory`
and NOTHING else. A provider module (``obsidian``, ``obsidian_cli``,
``projection``, ``backlinks``, ``templates``) is imported only inside
:func:`studyloop.second_brain.factory.get_backend`, after the provider has been
selected from configuration.

That is what makes the optionality contract testable instead of aspirational:
``tests/test_second_brain_optionality.py`` asserts against ``sys.modules``, so
a stray top-level import here would fail the suite rather than quietly costing
every ``studyloop --help`` an Obsidian import.

See ``docs/second-brain.md`` for the learner-facing guide and
``docs/architecture/second-brain.md`` for the numbered contract.
"""

from __future__ import annotations

from studyloop.second_brain.core import (
    NOT_CONFIGURED_DETAIL,
    XTILES_STAGE_ONE_DETAIL,
    BrainDescription,
    NullBackend,
    Operation,
    Provider,
    PublishResult,
    PullNotesResult,
    SecondBrain,
    SecondBrainError,
    XtilesStageOneBackend,
)
from studyloop.second_brain.factory import get_backend

__all__ = [
    "NOT_CONFIGURED_DETAIL",
    "XTILES_STAGE_ONE_DETAIL",
    "BrainDescription",
    "NullBackend",
    "Operation",
    "Provider",
    "PublishResult",
    "PullNotesResult",
    "SecondBrain",
    "SecondBrainError",
    "XtilesStageOneBackend",
    "get_backend",
]
