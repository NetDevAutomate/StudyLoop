"""Unit tests for studyctl.content.syllabus."""

import json

import pytest

from studyctl.content.syllabus import (
    ChunkStatus,
    SyllabusChunk,
    SyllabusParseError,
    SyllabusState,
    SyllabusStateError,
    build_fixed_size_chunks,
    build_prompt,
    get_next_chunk,
    has_non_pending_chunks,
    map_sources_to_chapters,
    parse_syllabus_response,
    read_state,
    title_case_name,
    write_state,
)


@pytest.fixture()
def source_map():
    """Standard 5-chapter source mapping."""
    return {1: "s1", 2: "s2", 3: "s3", 4: "s4", 5: "s5"}


@pytest.fixture()
def sample_state(source_map):
    """A SyllabusState with mixed chunk statuses."""
    return SyllabusState(
        notebook_id="nb-123",
        book_name="Test_Book",
        created="2026-03-10T00:00:00Z",
        max_chapters=2,
        generate_audio=True,
        generate_video=True,
        chunks={
            1: SyllabusChunk(
                episode=1,
                title="Foundations",
                chapters=[1, 2],
                source_ids=["s1", "s2"],
                status=ChunkStatus.COMPLETED,
            ),
            2: SyllabusChunk(
                episode=2,
                title="Deep Dive",
                chapters=[3, 4],
                source_ids=["s3", "s4"],
                status=ChunkStatus.PENDING,
            ),
            3: SyllabusChunk(
                episode=3,
                title="Advanced",
                chapters=[5],
                source_ids=["s5"],
                status=ChunkStatus.PENDING,
            ),
        },
    )


class TestBuildPrompt:
    """Tests for build_prompt."""

    def test_includes_source_titles(self):
        sources = [("s1", "chapter_01_intro.pdf"), ("s2", "chapter_02_basics.pdf")]
        prompt = build_prompt(sources, max_chapters=2)
        assert "1. chapter_01_intro.pdf" in prompt
        assert "2. chapter_02_basics.pdf" in prompt

    def test_includes_max_chapters(self):
        sources = [("s1", "ch1.pdf")]
        prompt = build_prompt(sources, max_chapters=3)
        assert "at most 3" in prompt


class TestParseSyllabusResponse:
    """Tests for parse_syllabus_response."""

    def test_clean_parse(self, source_map):
        response = (
            'Episode 1: "Foundations"\n'
            "Chapters: 1, 2\n"
            "Summary: Covers the basics.\n\n"
            'Episode 2: "Intermediate"\n'
            "Chapters: 3, 4\n"
            "Summary: Goes deeper.\n\n"
            'Episode 3: "Advanced"\n'
            "Chapters: 5\n"
            "Summary: Expert topics.\n"
        )
        chunks = parse_syllabus_response(response, source_map)
        assert len(chunks) == 3
        assert chunks[1].title == "Foundations"
        assert chunks[1].chapters == [1, 2]
        assert chunks[1].source_ids == ["s1", "s2"]
        assert chunks[3].chapters == [5]

    def test_empty_response_raises(self, source_map):
        with pytest.raises(SyllabusParseError, match="No episodes found"):
            parse_syllabus_response("", source_map)

    def test_unstructured_text_raises(self, source_map):
        with pytest.raises(SyllabusParseError, match="No episodes found"):
            parse_syllabus_response("Just some random text about chapters.", source_map)

    def test_missing_chapters_raises(self, source_map):
        response = 'Episode 1: "Partial"\nChapters: 1, 2, 3\nSummary: Only covers three.\n'
        with pytest.raises(SyllabusParseError, match="not assigned"):
            parse_syllabus_response(response, source_map)

    def test_with_preamble_text(self, source_map):
        response = (
            "Here is your podcast syllabus:\n\n"
            'Episode 1: "Part One"\n'
            "Chapters: 1, 2, 3\n"
            "Summary: First part.\n\n"
            'Episode 2: "Part Two"\n'
            "Chapters: 4, 5\n"
            "Summary: Second part.\n"
        )
        chunks = parse_syllabus_response(response, source_map)
        assert len(chunks) == 2

    def test_single_chapter_episode(self):
        source_map = {1: "s1"}
        response = 'Episode 1: "Solo"\nChapters: 1\nSummary: Just one chapter.\n'
        chunks = parse_syllabus_response(response, source_map)
        assert chunks[1].chapters == [1]


class TestBuildFixedSizeChunks:
    """Tests for build_fixed_size_chunks."""

    @pytest.mark.parametrize(
        "num_chapters,chunk_size,expected_count",
        [
            pytest.param(5, 2, 3, id="uneven-split"),
            pytest.param(4, 2, 2, id="even-split"),
            pytest.param(1, 5, 1, id="single-chapter"),
            pytest.param(3, 1, 3, id="chunk-size-one"),
            pytest.param(3, 100, 1, id="chunk-larger-than-input"),
        ],
    )
    def test_chunk_count(self, num_chapters, chunk_size, expected_count):
        source_map = {i + 1: f"s{i + 1}" for i in range(num_chapters)}
        chunks = build_fixed_size_chunks(source_map, chunk_size)
        assert len(chunks) == expected_count

    def test_no_items_lost(self, source_map):
        chunks = build_fixed_size_chunks(source_map, 2)
        all_chapters = []
        for chunk in chunks.values():
            all_chapters.extend(chunk.chapters)
        assert sorted(all_chapters) == [1, 2, 3, 4, 5]

    def test_chunk_size_zero_raises(self, source_map):
        with pytest.raises(ValueError, match="max_chapters must be >= 1"):
            build_fixed_size_chunks(source_map, 0)

    def test_empty_source_map_raises(self):
        with pytest.raises(ValueError, match="source_map is empty"):
            build_fixed_size_chunks({}, 2)

    def test_titles_contain_chapter_range(self, source_map):
        chunks = build_fixed_size_chunks(source_map, 2)
        assert chunks[1].title == "Chapters 1-2"
        assert chunks[3].title == "Chapters 5-5"

    def test_episodes_numbered_sequentially(self, source_map):
        chunks = build_fixed_size_chunks(source_map, 2)
        assert list(chunks.keys()) == [1, 2, 3]


class TestMapSourcesToChapters:
    """Tests for map_sources_to_chapters."""

    def test_standard_format(self):
        sources = [
            ("s1", "book_chapter_01_intro.pdf"),
            ("s2", "book_chapter_02_basics.pdf"),
        ]
        id_map, title_map = map_sources_to_chapters(sources)
        assert id_map == {1: "s1", 2: "s2"}
        assert title_map[1] == "book_chapter_01_intro.pdf"

    def test_case_insensitive(self):
        sources = [("s1", "CHAPTER_01_UPPER.pdf")]
        id_map, _ = map_sources_to_chapters(sources)
        assert id_map == {1: "s1"}

    def test_double_digit(self):
        sources = [("s10", "chapter_10_advanced.pdf")]
        id_map, _ = map_sources_to_chapters(sources)
        assert id_map == {10: "s10"}

    def test_no_match_falls_back_to_positional(self):
        sources = [("s1", "random_document.pdf"), ("s2", "another_file.pdf")]
        id_map, _ = map_sources_to_chapters(sources)
        assert id_map == {1: "s1", 2: "s2"}

    def test_empty_list(self):
        id_map, title_map = map_sources_to_chapters([])
        assert id_map == {}
        assert title_map == {}

    def test_mixed_parseable_unparseable_falls_back(self):
        sources = [
            ("s1", "chapter_01_intro.pdf"),
            ("s2", "appendix.pdf"),
        ]
        id_map, _ = map_sources_to_chapters(sources)
        assert id_map == {1: "s1", 2: "s2"}


class TestReadWriteState:
    """Tests for read_state and write_state."""

    def test_round_trip(self, tmp_path, sample_state):
        state_path = tmp_path / "state.json"
        write_state(sample_state, state_path)
        loaded = read_state(state_path)

        assert loaded.notebook_id == sample_state.notebook_id
        assert loaded.book_name == sample_state.book_name
        assert len(loaded.chunks) == len(sample_state.chunks)
        assert loaded.chunks[1].title == "Foundations"
        assert loaded.chunks[1].status == ChunkStatus.COMPLETED

    def test_atomic_write_no_temp_left(self, tmp_path, sample_state):
        state_path = tmp_path / "state.json"
        write_state(sample_state, state_path)
        files = list(tmp_path.iterdir())
        assert len(files) == 1
        assert files[0].name == "state.json"

    def test_read_missing_file_raises(self, tmp_path):
        with pytest.raises(SyllabusStateError, match="No syllabus found"):
            read_state(tmp_path / "nonexistent.json")

    def test_read_corrupt_json_raises(self, tmp_path):
        bad_file = tmp_path / "state.json"
        bad_file.write_text("{bad json", encoding="utf-8")
        with pytest.raises(SyllabusStateError, match="Cannot read state file"):
            read_state(bad_file)

    def test_read_missing_keys_raises(self, tmp_path):
        bad_file = tmp_path / "state.json"
        bad_file.write_text('{"chunks": [{}]}', encoding="utf-8")
        with pytest.raises(SyllabusStateError):
            read_state(bad_file)

    def test_write_creates_parent_dirs(self, tmp_path, sample_state):
        deep_path = tmp_path / "a" / "b" / "state.json"
        write_state(sample_state, deep_path)
        assert deep_path.is_file()

    def test_json_is_readable(self, tmp_path, sample_state):
        state_path = tmp_path / "state.json"
        write_state(sample_state, state_path)
        data = json.loads(state_path.read_text())
        assert data["notebook_id"] == "nb-123"
        assert isinstance(data["chunks"], list)
        assert data["chunks"][0]["episode"] == 1


class TestGetNextChunk:
    """Tests for get_next_chunk."""

    def test_returns_pending_chunk(self, sample_state):
        chunk = get_next_chunk(sample_state)
        assert chunk is not None
        assert chunk.episode == 2
        assert chunk.status == ChunkStatus.PENDING

    def test_generating_has_priority_over_pending(self, sample_state):
        sample_state.chunks[3].status = ChunkStatus.GENERATING
        chunk = get_next_chunk(sample_state)
        assert chunk is not None
        assert chunk.episode == 3

    def test_failed_has_priority_over_pending(self, sample_state):
        sample_state.chunks[3].status = ChunkStatus.FAILED
        chunk = get_next_chunk(sample_state)
        assert chunk is not None
        assert chunk.episode == 3

    def test_generating_has_priority_over_failed(self, sample_state):
        sample_state.chunks[2].status = ChunkStatus.FAILED
        sample_state.chunks[3].status = ChunkStatus.GENERATING
        chunk = get_next_chunk(sample_state)
        assert chunk is not None
        assert chunk.episode == 3

    def test_all_completed_returns_none(self, sample_state):
        for c in sample_state.chunks.values():
            c.status = ChunkStatus.COMPLETED
        assert get_next_chunk(sample_state) is None

    def test_empty_chunks_returns_none(self):
        state = SyllabusState(
            notebook_id="nb",
            book_name="book",
            created="",
            max_chapters=2,
            generate_audio=True,
            generate_video=True,
            chunks={},
        )
        assert get_next_chunk(state) is None


class TestHasNonPendingChunks:
    """Tests for has_non_pending_chunks."""

    def test_all_pending_returns_false(self, sample_state):
        for c in sample_state.chunks.values():
            c.status = ChunkStatus.PENDING
        assert not has_non_pending_chunks(sample_state)

    def test_one_completed_returns_true(self, sample_state):
        assert has_non_pending_chunks(sample_state)


class TestTitleCaseName:
    """Tests for title_case_name."""

    @pytest.mark.parametrize(
        "input_name,expected",
        [
            pytest.param("setting the stage", "Setting The Stage", id="lowercase"),
            pytest.param("ARCHITECTURE AND DESIGN", "Architecture And Design", id="uppercase"),
            pytest.param("data   storage", "Data Storage", id="extra-whitespace"),
            pytest.param("hello! world?", "Hello World", id="special-chars-removed"),
            pytest.param("", "", id="empty"),
            pytest.param("   ", "", id="whitespace-only"),
            pytest.param("single", "Single", id="single-word"),
        ],
    )
    def test_title_case(self, input_name, expected):
        assert title_case_name(input_name) == expected

    def test_truncates_at_100_chars(self):
        long_name = "a " * 100
        result = title_case_name(long_name)
        assert len(result) <= 100
