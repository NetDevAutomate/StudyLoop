"""Tests for the repository-level Playwright evidence contract."""

from __future__ import annotations

from pathlib import Path

from _playwright_paths import (
    PLAYWRIGHT_ARTIFACTS,
    PLAYWRIGHT_ROOT,
    PLAYWRIGHT_SNAPSHOTS,
    REPOSITORY_ROOT,
)


def test_playwright_evidence_is_anchored_to_the_repository() -> None:
    expected_root = Path(__file__).resolve().parents[3] / "playwright"

    assert expected_root.parent == REPOSITORY_ROOT
    assert expected_root == PLAYWRIGHT_ROOT
    assert expected_root / "artifacts" == PLAYWRIGHT_ARTIFACTS
    assert expected_root / "snapshots" == PLAYWRIGHT_SNAPSHOTS
