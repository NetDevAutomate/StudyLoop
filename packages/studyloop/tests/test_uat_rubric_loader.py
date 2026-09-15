"""Unit tests for tests/acceptance/uat/rubric.py -- UNGATED (council D-19/D-26).

Mechanism only: frontmatter parsing and the hash-pin loader, never a live
grading run, so this runs under the default ``just test`` gate.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_tests_dir = Path(__file__).parent
if str(_tests_dir) not in sys.path:
    sys.path.insert(0, str(_tests_dir))

from acceptance.uat.rubric import (  # noqa: E402
    DEFAULT_REGISTRY_PATH,
    DEFAULT_RUBRIC_PATH,
    RubricFormatError,
    RubricTamperedError,
    RubricVersionUnregisteredError,
    load_rubric,
    sha256_of_text,
)


class TestLoadRubric:
    def test_loads_the_committed_v1_rubric(self) -> None:
        rubric = load_rubric()
        assert rubric.version == 1
        criterion_ids = {c.id for c in rubric.criteria}
        assert {"accuracy", "pedagogy", "session_lifecycle"} <= criterion_ids

    def test_reject_if_conditions_are_present_and_non_empty(self) -> None:
        rubric = load_rubric()
        assert rubric.reject_if
        assert any("skip" in reason for reason in rubric.reject_if)

    def test_each_criterion_names_the_evidence_it_cites(self) -> None:
        rubric = load_rubric()
        for criterion in rubric.criteria:
            assert criterion.evidence, f"criterion {criterion.id!r} cites no evidence"

    def test_registry_hash_actually_matches_the_committed_file(self) -> None:
        raw = DEFAULT_RUBRIC_PATH.read_text(encoding="utf-8")
        registry = json.loads(DEFAULT_REGISTRY_PATH.read_text(encoding="utf-8"))
        assert registry["1"] == sha256_of_text(raw)


class TestRubricTamperDetection:
    def test_edited_in_place_rubric_is_rejected_by_hash(self, tmp_path: Path) -> None:
        raw = DEFAULT_RUBRIC_PATH.read_text(encoding="utf-8")
        # Same declared version, changed prose -- an edit made without
        # bumping the version.
        tampered_path = tmp_path / "rubric_v1.md"
        tampered_path.write_text(raw + "\n\nSnuck in an extra paragraph.\n", encoding="utf-8")

        with pytest.raises(RubricTamperedError):
            load_rubric(tampered_path, DEFAULT_REGISTRY_PATH)

    def test_unregistered_version_is_rejected(self, tmp_path: Path) -> None:
        rubric_path = tmp_path / "rubric_v2.md"
        rubric_path.write_text(
            "---\nversion: 2\ncriteria: []\nreject_if: []\n---\nbody\n", encoding="utf-8"
        )
        registry_path = tmp_path / "registry.json"
        registry_path.write_text(json.dumps({"1": "irrelevant"}), encoding="utf-8")

        with pytest.raises(RubricVersionUnregisteredError):
            load_rubric(rubric_path, registry_path)

    def test_missing_frontmatter_block_is_rejected(self, tmp_path: Path) -> None:
        rubric_path = tmp_path / "no_frontmatter.md"
        rubric_path.write_text("# Just prose, no frontmatter\n", encoding="utf-8")

        with pytest.raises(RubricFormatError):
            load_rubric(rubric_path, DEFAULT_REGISTRY_PATH)
