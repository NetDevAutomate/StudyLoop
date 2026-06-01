"""Tests for studyloop.review_loader — flashcard/quiz JSON loading."""

from __future__ import annotations

import json
from pathlib import Path  # noqa: TC003 — used at runtime in fixtures


class TestLoadFlashcards:
    def test_loads_cards_from_json(self, tmp_path: Path) -> None:
        from studyloop.review_loader import load_flashcards

        fc_dir = tmp_path / "flashcards"
        fc_dir.mkdir()
        (fc_dir / "01-intro-flashcards.json").write_text(
            json.dumps(
                {
                    "title": "Intro Flashcards",
                    "cards": [
                        {"front": "What is ETL?", "back": "Extract, Transform, Load"},
                        {"front": "What is a pipeline?", "back": "Automated data workflow"},
                    ],
                }
            )
        )

        cards = load_flashcards(fc_dir)
        assert len(cards) == 2
        assert cards[0].front == "What is ETL?"
        assert cards[0].back == "Extract, Transform, Load"
        assert cards[0].source == "Intro Flashcards"

    def test_empty_directory(self, tmp_path: Path) -> None:
        from studyloop.review_loader import load_flashcards

        assert load_flashcards(tmp_path) == []

    def test_skips_invalid_json(self, tmp_path: Path) -> None:
        from studyloop.review_loader import load_flashcards

        (tmp_path / "bad-flashcards.json").write_text("not json")
        assert load_flashcards(tmp_path) == []

    def test_card_hash_is_stable(self, tmp_path: Path) -> None:
        from studyloop.review_loader import load_flashcards

        fc_dir = tmp_path / "flashcards"
        fc_dir.mkdir()
        (fc_dir / "01-test-flashcards.json").write_text(
            json.dumps({"title": "Test", "cards": [{"front": "Q1", "back": "A1"}]})
        )

        cards = load_flashcards(fc_dir)
        hash1 = cards[0].card_hash
        cards2 = load_flashcards(fc_dir)
        assert cards2[0].card_hash == hash1

    def test_multiple_files_sorted(self, tmp_path: Path) -> None:
        from studyloop.review_loader import load_flashcards

        fc_dir = tmp_path / "flashcards"
        fc_dir.mkdir()
        for i in range(3):
            (fc_dir / f"{i:02d}-section-flashcards.json").write_text(
                json.dumps(
                    {
                        "title": f"Section {i}",
                        "cards": [{"front": f"Q{i}", "back": f"A{i}"}],
                    }
                )
            )

        cards = load_flashcards(fc_dir)
        assert len(cards) == 3
        assert cards[0].source == "Section 0"
        assert cards[2].source == "Section 2"


class TestLoadQuizzes:
    def test_loads_questions_with_options(self, tmp_path: Path) -> None:
        from studyloop.review_loader import load_quizzes

        quiz_dir = tmp_path / "quizzes"
        quiz_dir.mkdir()
        (quiz_dir / "01-intro-quiz.json").write_text(
            json.dumps(
                {
                    "title": "Intro Quiz",
                    "questions": [
                        {
                            "question": "What does ETL stand for?",
                            "answerOptions": [
                                {
                                    "text": "Extract, Transform, Load",
                                    "isCorrect": True,
                                    "rationale": "Correct!",
                                },
                                {"text": "Easy To Learn", "isCorrect": False, "rationale": "Nope"},
                            ],
                            "hint": "Think about data movement",
                        }
                    ],
                }
            )
        )

        questions = load_quizzes(quiz_dir)
        assert len(questions) == 1
        assert questions[0].question == "What does ETL stand for?"
        assert len(questions[0].options) == 2
        assert questions[0].options[0].is_correct is True
        assert questions[0].hint == "Think about data movement"

    def test_empty_directory(self, tmp_path: Path) -> None:
        from studyloop.review_loader import load_quizzes

        assert load_quizzes(tmp_path) == []


class TestDiscoverDirectories:
    def test_finds_course_with_flashcards(self, tmp_path: Path) -> None:
        from studyloop.review_loader import discover_directories

        fc_dir = tmp_path / "flashcards"
        fc_dir.mkdir()
        (fc_dir / "01-test-flashcards.json").write_text(
            json.dumps({"title": "T", "cards": [{"front": "Q", "back": "A"}]})
        )

        courses = discover_directories([str(tmp_path)])
        assert len(courses) == 1
        assert courses[0][0] == tmp_path.name

    def test_finds_downloads_subdir(self, tmp_path: Path) -> None:
        from studyloop.review_loader import discover_directories

        downloads = tmp_path / "downloads" / "flashcards"
        downloads.mkdir(parents=True)
        (downloads / "01-test-flashcards.json").write_text(
            json.dumps({"title": "T", "cards": [{"front": "Q", "back": "A"}]})
        )

        courses = discover_directories([str(tmp_path)])
        assert len(courses) == 1

    def test_empty_config(self) -> None:
        from studyloop.review_loader import discover_directories

        assert discover_directories(None) == []
        assert discover_directories([]) == []

    def test_nonexistent_directory(self) -> None:
        from studyloop.review_loader import discover_directories

        assert discover_directories(["/nonexistent/path"]) == []

    def test_finds_course_three_levels_deep(self, tmp_path: Path) -> None:
        # The real vault is base/<publisher>/<course>/flashcards/ — discovery
        # must descend past the publisher level to find the course.
        from studyloop.review_loader import discover_directories

        course = tmp_path / "CodeWithMosh" / "Complete_SQL_Mastery"
        fc_dir = course / "flashcards"
        fc_dir.mkdir(parents=True)
        (fc_dir / "getting-started-flashcards.json").write_text(
            json.dumps({"title": "Getting Started", "cards": [{"front": "Q", "back": "A"}]})
        )

        courses = discover_directories([str(tmp_path)])
        assert len(courses) == 1
        name, path = courses[0]
        assert name == "Complete_SQL_Mastery"
        assert path == course

    def test_finds_multiple_courses_under_multiple_publishers(self, tmp_path: Path) -> None:
        from studyloop.review_loader import discover_directories

        for pub, crs in [
            ("CodeWithMosh", "Complete_SQL_Mastery"),
            ("CodeWithMosh", "The_Ultimate_Git_Course"),
            ("ArjanCodes", "The_Software_Designer_Mindset"),
        ]:
            quiz_dir = tmp_path / pub / crs / "quizzes"
            quiz_dir.mkdir(parents=True)
            (quiz_dir / f"{crs}-quiz.json").write_text(
                json.dumps(
                    {
                        "title": crs,
                        "questions": [
                            {"question": "Q?", "answerOptions": [{"text": "A", "isCorrect": True}]}
                        ],
                    }
                )
            )

        courses = discover_directories([str(tmp_path)])
        names = sorted(n for n, _ in courses)
        assert names == [
            "Complete_SQL_Mastery",
            "The_Software_Designer_Mindset",
            "The_Ultimate_Git_Course",
        ]

    def test_does_not_descend_into_deck_subdirs(self, tmp_path: Path) -> None:
        # A content-bearing course is a leaf: its flashcards/ subdir must not
        # be reported as a separate course.
        from studyloop.review_loader import discover_directories

        course = tmp_path / "Pub" / "Course"
        fc_dir = course / "flashcards"
        fc_dir.mkdir(parents=True)
        (fc_dir / "x-flashcards.json").write_text(
            json.dumps({"title": "X", "cards": [{"front": "Q", "back": "A"}]})
        )

        courses = discover_directories([str(tmp_path)])
        assert len(courses) == 1
        assert courses[0][1] == course

    def test_empty_deck_dirs_not_discovered(self, tmp_path: Path) -> None:
        # get_course_dir eagerly mkdirs flashcards/ + quizzes/; an course with
        # only empty deck dirs (no JSON yet) must NOT surface as ready content.
        from studyloop.review_loader import discover_directories

        course = tmp_path / "Pub" / "EmptyCourse"
        (course / "flashcards").mkdir(parents=True)
        (course / "quizzes").mkdir(parents=True)

        assert discover_directories([str(tmp_path)]) == []


class TestFindContentDirs:
    def test_finds_subdirectories(self, tmp_path: Path) -> None:
        from studyloop.review_loader import find_content_dirs

        fc_dir = tmp_path / "flashcards"
        fc_dir.mkdir()
        (fc_dir / "01-test-flashcards.json").write_text("{}")

        quiz_dir = tmp_path / "quizzes"
        quiz_dir.mkdir()
        (quiz_dir / "01-test-quiz.json").write_text("{}")

        fc, qz = find_content_dirs(tmp_path)
        assert fc == fc_dir
        assert qz == quiz_dir

    def test_finds_flat_directory(self, tmp_path: Path) -> None:
        from studyloop.review_loader import find_content_dirs

        (tmp_path / "01-test-flashcards.json").write_text("{}")
        fc, qz = find_content_dirs(tmp_path)
        assert fc == tmp_path
        assert qz is None


class TestShuffleItems:
    def test_shuffle_returns_same_length(self) -> None:
        from studyloop.review_loader import shuffle_items

        items = [1, 2, 3, 4, 5]
        result = shuffle_items(items, enabled=True)
        assert len(result) == 5
        assert set(result) == set(items)

    def test_no_shuffle_preserves_order(self) -> None:
        from studyloop.review_loader import shuffle_items

        items = [1, 2, 3, 4, 5]
        result = shuffle_items(items, enabled=False)
        assert result == items

    def test_does_not_mutate_original(self) -> None:
        from studyloop.review_loader import shuffle_items

        items = [1, 2, 3]
        shuffle_items(items, enabled=True)
        assert items == [1, 2, 3]
