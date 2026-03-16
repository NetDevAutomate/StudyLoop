"""Unit tests for studyctl.content.splitter."""

pymupdf = __import__("pytest").importorskip("pymupdf")

from pathlib import Path  # noqa: E402

import pytest  # noqa: E402

from studyctl.content.splitter import sanitize_filename, split_pdf_by_chapters  # noqa: E402


@pytest.fixture
def sample_pdf(tmp_path: Path) -> Path:
    doc = pymupdf.open()
    for i in range(10):
        page = doc.new_page()
        page.insert_text((72, 72), f"Page {i + 1} content")
    toc = [
        [1, "Chapter 1: Introduction", 1],
        [2, "1.1 Background", 1],
        [2, "1.2 Overview", 2],
        [1, "Chapter 2: Core Concepts", 4],
        [2, "2.1 Fundamentals", 4],
        [2, "2.2 Advanced Topics", 6],
        [1, "Chapter 3: Conclusion", 8],
        [2, "3.1 Summary", 8],
        [2, "3.2 Next Steps", 9],
    ]
    doc.set_toc(toc)
    pdf_path = tmp_path / "test_book.pdf"
    doc.ez_save(str(pdf_path))
    doc.close()
    return pdf_path


@pytest.fixture
def sample_pdf_no_toc(tmp_path: Path) -> Path:
    doc = pymupdf.open()
    for i in range(3):
        page = doc.new_page()
        page.insert_text((72, 72), f"Page {i + 1}")
    pdf_path = tmp_path / "no_toc.pdf"
    doc.ez_save(str(pdf_path))
    doc.close()
    return pdf_path


@pytest.fixture
def output_dir(tmp_path: Path) -> Path:
    out = tmp_path / "output"
    out.mkdir()
    return out


class TestSanitizeFilename:
    """Tests for sanitize_filename."""

    def test_basic_title(self):
        assert sanitize_filename("Chapter 1") == "chapter_1"

    def test_special_characters_removed(self):
        assert sanitize_filename("Hello: World! (2024)") == "hello_world_2024"

    def test_colons_and_semicolons(self):
        result = sanitize_filename("Part 1: The Beginning; A Story")
        assert ":" not in result
        assert ";" not in result

    def test_multiple_spaces_collapsed(self):
        assert sanitize_filename("Too   Many   Spaces") == "too_many_spaces"

    def test_leading_trailing_whitespace(self):
        assert sanitize_filename("  padded  ") == "padded"

    def test_truncation_at_80_chars(self):
        long_name = "A" * 100
        result = sanitize_filename(long_name)
        assert len(result) <= 80

    def test_empty_string(self):
        assert sanitize_filename("") == ""

    def test_hyphens_preserved(self):
        result = sanitize_filename("Data-Intensive Applications")
        assert "-" in result

    def test_underscores_preserved(self):
        assert sanitize_filename("my_chapter_title") == "my_chapter_title"


class TestSplitPdfByChapters:
    """Tests for split_pdf_by_chapters."""

    def test_splits_correct_number(self, sample_pdf, output_dir):
        result = split_pdf_by_chapters(sample_pdf, output_dir, "test_book", level=1)
        assert len(result) == 3

    def test_output_files_exist(self, sample_pdf, output_dir):
        result = split_pdf_by_chapters(sample_pdf, output_dir, "test_book", level=1)
        for path in result:
            assert path.exists()
            assert path.suffix == ".pdf"

    def test_filenames_contain_chapter_number(self, sample_pdf, output_dir):
        result = split_pdf_by_chapters(sample_pdf, output_dir, "test_book", level=1)
        assert "chapter_01" in result[0].name
        assert "chapter_02" in result[1].name
        assert "chapter_03" in result[2].name

    def test_output_files_are_valid_pdfs(self, sample_pdf, output_dir):
        result = split_pdf_by_chapters(sample_pdf, output_dir, "test_book", level=1)
        for path in result:
            doc = pymupdf.open(path)
            assert doc.page_count > 0
            doc.close()

    def test_chapter_page_counts(self, sample_pdf, output_dir):
        """Ch1=p1-3 (3pp), Ch2=p4-7 (4pp), Ch3=p8-10 (3pp)."""
        result = split_pdf_by_chapters(sample_pdf, output_dir, "test_book", level=1)
        counts = []
        for path in result:
            doc = pymupdf.open(path)
            counts.append(doc.page_count)
            doc.close()
        assert counts == [3, 4, 3]

    def test_split_at_level_2(self, sample_pdf, output_dir):
        result = split_pdf_by_chapters(sample_pdf, output_dir, "test_book", level=2)
        assert len(result) == 6

    def test_chapter_pdfs_have_toc(self, sample_pdf, output_dir):
        result = split_pdf_by_chapters(sample_pdf, output_dir, "test_book", level=1)
        doc = pymupdf.open(result[0])
        toc = doc.get_toc()
        assert len(toc) > 0
        doc.close()

    def test_raises_on_no_toc(self, sample_pdf_no_toc, output_dir):
        with pytest.raises(ValueError, match="has no bookmarks/TOC"):
            split_pdf_by_chapters(sample_pdf_no_toc, output_dir, "test_book")

    def test_raises_on_wrong_level(self, sample_pdf, output_dir):
        with pytest.raises(ValueError, match="No TOC entries at level 5"):
            split_pdf_by_chapters(sample_pdf, output_dir, "test_book", level=5)

    def test_creates_output_dir_if_missing(self, sample_pdf, tmp_path):
        new_dir = tmp_path / "nonexistent" / "nested"
        result = split_pdf_by_chapters(sample_pdf, new_dir, "test_book", level=1)
        assert new_dir.exists()
        assert len(result) == 3

    def test_book_name_in_filenames(self, sample_pdf, output_dir):
        result = split_pdf_by_chapters(sample_pdf, output_dir, "my_book", level=1)
        for path in result:
            assert path.name.startswith("my_book_")
