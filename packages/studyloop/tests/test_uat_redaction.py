"""Unit tests for tests/acceptance/uat/redaction.py -- UNGATED (council D-19/D-26).

Mechanism only: the hash-pin loader and the redact/detect functions, never a
live UAT run, so this runs under the default ``just test`` gate.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_tests_dir = Path(__file__).parent
if str(_tests_dir) not in sys.path:
    sys.path.insert(0, str(_tests_dir))

from acceptance.uat.redaction import (  # noqa: E402
    DEFAULT_REGISTRY_PATH,
    DEFAULT_RULES_PATH,
    RedactionLeakError,
    RedactionRulesTamperedError,
    RedactionRulesUnregisteredVersionError,
    contains_forbidden_content,
    load_redaction_rules,
    redact_summary,
    sha256_of_text,
)


class TestLoadRedactionRules:
    def test_loads_the_committed_v1_rules(self) -> None:
        rules = load_redaction_rules()
        assert rules.version == 1
        assert "run_id" in rules.allowed_fields
        assert "arbitration_note" in rules.allowed_fields
        # never allowlisted: raw evidence
        assert "transcript" not in rules.allowed_fields
        assert "screenshots" not in rules.allowed_fields

    def test_edited_in_place_rules_file_is_rejected_by_hash(self, tmp_path: Path) -> None:
        raw = DEFAULT_RULES_PATH.read_text(encoding="utf-8")
        tampered_path = tmp_path / "redaction_rules_v1.yaml"
        # Same declared version, different content -- an edit made without
        # bumping the version, exactly the tamper this loader must catch.
        tampered_path.write_text(raw + "\n  - a_new_field_snuck_in\n", encoding="utf-8")

        with pytest.raises(RedactionRulesTamperedError):
            load_redaction_rules(tampered_path, DEFAULT_REGISTRY_PATH)

    def test_unregistered_version_is_rejected(self, tmp_path: Path) -> None:
        rules_path = tmp_path / "redaction_rules_v2.yaml"
        rules_path.write_text("version: 2\nallowed_fields:\n  - run_id\n", encoding="utf-8")
        registry_path = tmp_path / "registry.json"
        registry_path.write_text(json.dumps({"1": "irrelevant"}), encoding="utf-8")

        with pytest.raises(RedactionRulesUnregisteredVersionError):
            load_redaction_rules(rules_path, registry_path)

    def test_registry_hash_actually_matches_the_committed_file(self) -> None:
        """Not just 'the loader accepts it' -- the registry's pinned hash for
        version 1 must be exactly this file's sha256, computed independently
        here so a hand-edited registry entry that happens to match nothing
        real would still be caught."""
        raw = DEFAULT_RULES_PATH.read_text(encoding="utf-8")
        registry = json.loads(DEFAULT_REGISTRY_PATH.read_text(encoding="utf-8"))
        assert registry["1"] == sha256_of_text(raw)


class TestForbiddenContentDetectorHasTeeth:
    """Positive control (council TESTS FIRST): the dirty input must fail the
    check FIRST, before any claim that redaction cleans it is trusted."""

    def test_home_path_is_detected(self) -> None:
        violations = contains_forbidden_content({"note": "see /Users/ataylor/secret.txt"})
        assert violations, "detector failed to flag a home path -- it has no teeth"

    def test_fake_key_is_detected(self) -> None:
        violations = contains_forbidden_content({"note": "key=sk-abcdefgh12345678"})
        assert violations, "detector failed to flag a key-shaped token"

    def test_clean_structured_value_is_not_flagged(self) -> None:
        assert contains_forbidden_content({"run_id": "run-0001", "rubric_version": 1}) == []


class TestRedactSummary:
    def _dirty_bundle_summary(self) -> dict[str, object]:
        """A fixture bundle containing a home path, a fake key, and a
        message body alongside the allowlisted fields -- the exact shape
        the TESTS FIRST item describes."""
        return {
            "run_id": "run-0001",
            "date": "2026-09-15T00:00:00Z",
            "repo_sha": "deadbeef",
            "harness": "kiro",
            "harness_version": "1.2.3",
            "actor_backend": "scripted",
            "actor_model": None,
            "rubric_version": 1,
            "rubric_hash": "abc123",
            "journeys": {"session_lifecycle": "passed"},
            "per_criterion_scores": {"pedagogy": 4},
            "arbitration_note": "clean note, no PII here",
            "private_bundle_digest": "sha256:deadbeef",
            # Never allowlisted -- must be dropped, not merely ignored:
            "transcript_path": (
                "/Users/ataylor/.local/share/studyloop/uat/run-0001/transcript.jsonl"
            ),
            "api_key": "sk-ant-fake0000000000000000",  # pragma: allowlist secret
            "last_learner_message": "Can you explain closures again?",
        }

    def test_positive_control_the_dirty_input_itself_fails_the_check_first(self) -> None:
        dirty = self._dirty_bundle_summary()
        violations = contains_forbidden_content(dirty)
        assert violations, (
            "positive control failed: the raw fixture bundle summary must trip "
            "the forbidden-content detector before redaction is ever trusted "
            "to have cleaned it"
        )

    def test_redacted_summary_drops_every_non_allowlisted_field(self) -> None:
        rules = load_redaction_rules()
        dirty = self._dirty_bundle_summary()
        redacted = redact_summary(dirty, rules)

        assert "transcript_path" not in redacted
        assert "api_key" not in redacted
        assert "last_learner_message" not in redacted
        for key in redacted:
            assert key in rules.allowed_fields

    def test_redacted_summary_comes_out_clean(self) -> None:
        rules = load_redaction_rules()
        dirty = self._dirty_bundle_summary()
        redacted = redact_summary(dirty, rules)
        assert contains_forbidden_content(redacted) == []

    def test_allowlisted_field_carrying_a_leaked_home_path_still_raises(self) -> None:
        """The allowlist is filtered first, but the VALUE is still scanned --
        an allowlisted field is not a free pass for its content."""
        rules = load_redaction_rules()
        poisoned = {
            "run_id": "run-0001",
            "arbitration_note": "see /Users/ataylor/private/notes.md for context",
        }
        with pytest.raises(RedactionLeakError):
            redact_summary(poisoned, rules)
