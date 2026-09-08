"""ConceptService's public API surface is frozen before B4 depends on it.

design.md "Compatibility seams" / EXECUTION-ERRATA.md correction #5: B4 is
only ever a caller of this seam, never a second implementation of concept
transitions. Any rename, added required parameter, or return-shape change
fails here first, by exact signature string.
"""

from __future__ import annotations

import dataclasses
import inspect

from agent_session_tools.context.concepts import (
    BatchResult,
    BindResult,
    ConceptService,
    TransitionResult,
)
from agent_session_tools.context.okf_import import ImportReport
from agent_session_tools.context.projection import ProjectionReport

FROZEN_SIGNATURES = {
    "__init__": (
        "(self, db: 'Path | None' = None, *, now: 'Callable[[], str] | None' = None, "
        "prepare_schema: 'bool' = True) -> 'None'"
    ),
    "project": (
        "(self, out: 'Path', *, project: 'str | None' = None) -> 'ProjectionReport'"
    ),
    "winddown": (
        "(self, session_id: 'str', document: 'object', *, actor: 'str', "
        "project: 'str | None' = None) -> 'BatchResult'"
    ),
    "transition": (
        "(self, concept_id: 'str', standing: 'TransitionStanding', *, actor: 'str', "
        "reason: 'str', project: 'str | None' = None) -> 'TransitionResult'"
    ),
    "bind_legacy": (
        "(self, concept_id: 'str', document: 'object', *, actor: 'str', "
        "reason: 'str', project: 'str | None' = None) -> 'BindResult'"
    ),
    "import_okf": (
        "(self, root: 'Path', *, actor: 'str', project: 'str | None' = None, "
        "dry_run: 'bool' = False) -> 'ImportReport'"
    ),
}

FROZEN_RESULT_FIELDS = {
    BatchResult: ("writes", "concept_ids", "errors"),
    TransitionResult: ("writes", "concept_id", "standing", "event_id", "errors"),
    BindResult: ("writes", "legacy_concept_id", "concept_id", "assertion_id", "errors"),
}

FROZEN_PROJECTION_FIELDS = (
    "status",
    "selected",
    "rendered",
    "unchanged",
    "created",
    "replaced",
    "deleted",
    "conflicts",
    "skipped_unavailable",
    "skipped_retired",
    "writes",
    "scope",
    "project",
    "policy_digest",
    "access_instance",
    "access_revision",
    "logical_state_hash",
)

FROZEN_IMPORT_COUNTERS = (
    "scanned",
    "parsed",
    "invalid_yaml",
    "invalid_schema",
    "unsafe_path",
    "duplicate_content",
    "already_present",
    "bound",
    "legacy_unbound",
    "missing_session",
    "no_visible_evidence",
    "no_exact_match",
    "ambiguous_match",
    "oversized_evidence",
    "body_description_mismatch",
    "imported",
    "write_failures",
    "writes",
    "errors",
)


def test_public_method_names_are_exactly_the_frozen_seam():
    public = {
        name
        for name in vars(ConceptService)
        if not name.startswith("_") and callable(getattr(ConceptService, name))
    }
    assert public == {"project", "winddown", "transition", "bind_legacy", "import_okf"}


def test_every_frozen_signature_is_unchanged():
    for name, frozen in FROZEN_SIGNATURES.items():
        observed = str(inspect.signature(getattr(ConceptService, name)))
        assert observed == frozen, f"ConceptService.{name} signature moved: {observed}"


def test_result_dataclass_fields_are_unchanged():
    for result_type, frozen in FROZEN_RESULT_FIELDS.items():
        observed = tuple(field.name for field in dataclasses.fields(result_type))
        assert observed == frozen, f"{result_type.__name__} fields moved: {observed}"


def test_projection_report_fields_are_unchanged():
    observed = tuple(field.name for field in dataclasses.fields(ProjectionReport))
    assert observed == FROZEN_PROJECTION_FIELDS


def test_import_report_fields_are_unchanged():
    observed = tuple(field.name for field in dataclasses.fields(ImportReport))
    assert observed == FROZEN_IMPORT_COUNTERS
