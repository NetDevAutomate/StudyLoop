"""Unit tests for studyctl.content.storage."""

import json
from unittest.mock import patch

from studyctl.content.storage import (
    COURSE_SUBDIRS,
    check_content_dependencies,
    get_course_dir,
    list_courses,
    load_course_metadata,
    save_course_metadata,
    slugify,
)


class TestSlugify:
    """Tests for slugify."""

    def test_basic_title(self):
        assert slugify("My First Course") == "my-first-course"

    def test_special_characters_removed(self):
        result = slugify("Hello: World! (2024)")
        assert ":" not in result
        assert "!" not in result
        assert "(" not in result

    def test_uppercase_lowered(self):
        assert slugify("ALL CAPS TITLE") == "all-caps-title"

    def test_underscores_become_hyphens(self):
        assert slugify("my_course_title") == "my-course-title"

    def test_multiple_spaces_collapsed(self):
        assert slugify("Too   Many   Spaces") == "too-many-spaces"

    def test_leading_trailing_whitespace(self):
        result = slugify("  padded  ")
        assert not result.startswith("-")
        assert not result.endswith("-")

    def test_truncation_at_60_chars(self):
        long_name = "a " * 50
        result = slugify(long_name)
        assert len(result) <= 60

    def test_empty_string(self):
        assert slugify("") == ""

    def test_hyphens_preserved(self):
        result = slugify("data-intensive-apps")
        assert result == "data-intensive-apps"

    def test_only_special_chars(self):
        result = slugify("!@#$%")
        assert result == ""


class TestGetCourseDir:
    """Tests for get_course_dir."""

    def test_creates_all_subdirs(self, tmp_path):
        course_dir = get_course_dir(tmp_path, "my-course")
        assert course_dir == tmp_path / "my-course"
        for subdir in COURSE_SUBDIRS:
            assert (course_dir / subdir).is_dir()

    def test_idempotent(self, tmp_path):
        get_course_dir(tmp_path, "my-course")
        # Second call should not raise
        course_dir = get_course_dir(tmp_path, "my-course")
        assert course_dir.is_dir()

    def test_nested_base_path(self, tmp_path):
        deep_base = tmp_path / "a" / "b" / "c"
        course_dir = get_course_dir(deep_base, "test")
        assert course_dir.is_dir()
        assert (course_dir / "chapters").is_dir()


class TestCourseMetadata:
    """Tests for load_course_metadata and save_course_metadata."""

    def test_round_trip(self, tmp_path):
        course_dir = tmp_path / "my-course"
        course_dir.mkdir()
        metadata = {"notebook_id": "nb-123", "title": "My Course", "chapters": 5}

        save_course_metadata(course_dir, metadata)
        loaded = load_course_metadata(course_dir)

        assert loaded == metadata

    def test_load_missing_returns_empty(self, tmp_path):
        course_dir = tmp_path / "no-such-course"
        course_dir.mkdir()
        assert load_course_metadata(course_dir) == {}

    def test_load_corrupt_json_returns_empty(self, tmp_path):
        course_dir = tmp_path / "bad-course"
        course_dir.mkdir()
        meta_path = course_dir / "metadata.json"
        meta_path.write_text("{bad json", encoding="utf-8")
        assert load_course_metadata(course_dir) == {}

    def test_save_creates_parent_dirs(self, tmp_path):
        course_dir = tmp_path / "deep" / "nested" / "course"
        save_course_metadata(course_dir, {"key": "value"})
        assert (course_dir / "metadata.json").is_file()

    def test_atomic_write_no_temp_left(self, tmp_path):
        course_dir = tmp_path / "clean-course"
        course_dir.mkdir()
        save_course_metadata(course_dir, {"a": 1})
        files = [f.name for f in course_dir.iterdir()]
        assert files == ["metadata.json"]

    def test_json_is_readable(self, tmp_path):
        course_dir = tmp_path / "readable-course"
        course_dir.mkdir()
        save_course_metadata(course_dir, {"notebook_id": "nb-456"})
        data = json.loads((course_dir / "metadata.json").read_text())
        assert data["notebook_id"] == "nb-456"


class TestListCourses:
    """Tests for list_courses."""

    def test_discovers_courses(self, tmp_path):
        for slug in ("course-a", "course-b"):
            d = tmp_path / slug
            d.mkdir()
            save_course_metadata(d, {"title": slug})

        courses = list_courses(tmp_path)
        assert len(courses) == 2
        slugs = [c["slug"] for c in courses]
        assert "course-a" in slugs
        assert "course-b" in slugs

    def test_empty_base_path(self, tmp_path):
        assert list_courses(tmp_path) == []

    def test_nonexistent_base_path(self, tmp_path):
        assert list_courses(tmp_path / "nonexistent") == []

    def test_ignores_hidden_dirs(self, tmp_path):
        (tmp_path / ".hidden").mkdir()
        (tmp_path / "visible").mkdir()
        courses = list_courses(tmp_path)
        assert len(courses) == 1
        assert courses[0]["slug"] == "visible"

    def test_ignores_files(self, tmp_path):
        (tmp_path / "not-a-dir.txt").write_text("hello")
        (tmp_path / "real-course").mkdir()
        courses = list_courses(tmp_path)
        assert len(courses) == 1

    def test_includes_metadata(self, tmp_path):
        course_dir = tmp_path / "with-meta"
        course_dir.mkdir()
        save_course_metadata(course_dir, {"title": "With Meta", "chapters": 3})

        courses = list_courses(tmp_path)
        assert courses[0]["metadata"]["title"] == "With Meta"


class TestCheckContentDependencies:
    """Tests for check_content_dependencies."""

    def test_returns_list(self):
        result = check_content_dependencies()
        assert isinstance(result, list)

    def test_all_present(self):
        with patch("shutil.which", return_value="/usr/bin/fake"):
            result = check_content_dependencies()
        assert result == []

    def test_pandoc_missing(self):
        def mock_which(cmd):
            return None if cmd == "pandoc" else "/usr/bin/fake"

        with patch("shutil.which", side_effect=mock_which):
            result = check_content_dependencies()
        assert any("pandoc" in item for item in result)

    def test_mmdc_missing(self):
        def mock_which(cmd):
            return None if cmd == "mmdc" else "/usr/bin/fake"

        with patch("shutil.which", side_effect=mock_which):
            result = check_content_dependencies()
        assert any("mmdc" in item for item in result)
