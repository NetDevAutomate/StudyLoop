"""Tests for services/content.py — thin service layer over content.storage.

Tests verify that the service functions delegate correctly to storage.
No conftest.py (pluggy conflict) — all fixtures are inline.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from studyctl.services import content as svc


@pytest.fixture
def base_path(tmp_path: Path) -> Path:
    """Base path with two course directories."""
    (tmp_path / "python-basics" / "flashcards").mkdir(parents=True)
    (tmp_path / "networking" / "flashcards").mkdir(parents=True)
    return tmp_path


@pytest.fixture
def course_with_metadata(tmp_path: Path) -> Path:
    """A course directory with a metadata.json file."""
    course = tmp_path / "my-course"
    course.mkdir()
    metadata = {
        "notebook_id": "nb-abc123",
        "syllabus_state": "complete",
        "generation_history": [],
    }
    (course / "metadata.json").write_text(json.dumps(metadata))
    return course


class TestListCourses:
    def test_lists_existing_courses(self, base_path: Path) -> None:
        """list_courses returns all course directories."""
        courses = svc.list_courses(base_path)
        slugs = [c["slug"] for c in courses]
        assert "python-basics" in slugs
        assert "networking" in slugs

    def test_returns_empty_for_empty_base(self, tmp_path: Path) -> None:
        """list_courses on an empty directory returns an empty list."""
        courses = svc.list_courses(tmp_path)
        assert courses == []

    def test_returns_empty_for_nonexistent_base(self, tmp_path: Path) -> None:
        """list_courses on a nonexistent path returns an empty list."""
        missing = tmp_path / "does-not-exist"
        courses = svc.list_courses(missing)
        assert courses == []


class TestGetCourse:
    def test_creates_course_directory(self, tmp_path: Path) -> None:
        """get_course creates the course directory if it doesn't exist."""
        course_dir = svc.get_course(tmp_path, "new-course")
        assert course_dir.exists()
        assert course_dir.is_dir()

    def test_returns_existing_course_directory(self, base_path: Path) -> None:
        """get_course returns the existing directory without error."""
        course_dir = svc.get_course(base_path, "python-basics")
        assert course_dir.exists()


class TestSlugifyTitle:
    def test_converts_spaces_to_hyphens(self) -> None:
        slug = svc.slugify_title("Python Basics")
        assert " " not in slug
        assert "-" in slug

    def test_lowercases_title(self) -> None:
        slug = svc.slugify_title("AWS Networking")
        assert slug == slug.lower()

    def test_removes_special_characters(self) -> None:
        slug = svc.slugify_title("C++: The Good Parts!")
        # Should only contain alphanumeric and hyphens
        for char in slug:
            assert char.isalnum() or char == "-", f"Unexpected char '{char}' in slug '{slug}'"

    def test_handles_already_slugified(self) -> None:
        slug = svc.slugify_title("python-basics")
        assert slug == "python-basics"


class TestGetMetadata:
    def test_loads_existing_metadata(self, course_with_metadata: Path) -> None:
        """get_metadata loads the metadata.json file."""
        metadata = svc.get_metadata(course_with_metadata)
        assert metadata["notebook_id"] == "nb-abc123"
        assert metadata["syllabus_state"] == "complete"

    def test_returns_empty_dict_for_missing_metadata(self, tmp_path: Path) -> None:
        """get_metadata returns an empty dict when no metadata.json exists."""
        course = tmp_path / "empty-course"
        course.mkdir()
        metadata = svc.get_metadata(course)
        assert metadata == {}


class TestSaveMetadata:
    def test_saves_metadata_to_disk(self, tmp_path: Path) -> None:
        """save_metadata writes metadata.json atomically."""
        course = tmp_path / "save-course"
        course.mkdir()
        data = {"notebook_id": "nb-xyz", "tags": ["python", "basics"]}

        svc.save_metadata(course, data)

        metadata_file = course / "metadata.json"
        assert metadata_file.exists()
        loaded = json.loads(metadata_file.read_text())
        assert loaded["notebook_id"] == "nb-xyz"
        assert loaded["tags"] == ["python", "basics"]

    def test_overwrites_existing_metadata(self, course_with_metadata: Path) -> None:
        """save_metadata replaces existing metadata.json."""
        new_data = {"notebook_id": "nb-new", "syllabus_state": "in_progress"}
        svc.save_metadata(course_with_metadata, new_data)

        metadata = svc.get_metadata(course_with_metadata)
        assert metadata["notebook_id"] == "nb-new"
        assert metadata.get("generation_history") is None  # old key gone

    def test_round_trip_save_load(self, tmp_path: Path) -> None:
        """Metadata saved and loaded back is identical."""
        course = tmp_path / "round-trip"
        course.mkdir()
        original = {"key1": "value1", "nested": {"a": 1, "b": [1, 2, 3]}}

        svc.save_metadata(course, original)
        loaded = svc.get_metadata(course)

        assert loaded == original
