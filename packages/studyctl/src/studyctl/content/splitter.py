"""PDF splitting module using PyMuPDF.

Splits a PDF into per-chapter files based on its Table of Contents
bookmarks. Requires pymupdf (install via studyctl[content] extra).
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

import pymupdf

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)


def sanitize_filename(name: str) -> str:
    """Clean a chapter title for use as a filename.

    Removes special characters, replaces whitespace with underscores,
    truncates to 80 characters, and lowercases the result.
    """
    name = re.sub(r"[^\w\s-]", "", name)
    name = re.sub(r"[\s]+", "_", name.strip())
    return name[:80].strip("_").lower()


def split_pdf_by_chapters(
    input_path: Path,
    output_dir: Path,
    book_name: str,
    level: int = 1,
) -> list[Path]:
    """Split a PDF into per-chapter files based on its TOC bookmarks.

    Args:
        input_path: Path to the source PDF.
        output_dir: Directory to write chapter PDFs into.
        book_name: Base name used in output filenames.
        level: TOC depth level to split on (1 = top-level chapters).

    Returns:
        List of paths to the generated chapter PDF files.

    Raises:
        ValueError: If the PDF contains no TOC / bookmarks.
    """
    with pymupdf.open(input_path) as doc:
        toc = doc.get_toc()

        if not toc:
            raise ValueError(
                f"'{input_path.name}' has no bookmarks/TOC. Cannot split without chapter markers."
            )

        # Filter to requested level entries: each entry is [level, title, page]
        chapters = [(title, page) for lvl, title, page in toc if lvl == level]

        if not chapters:
            raise ValueError(
                f"No TOC entries at level {level}. Available levels: {sorted({e[0] for e in toc})}"
            )

        output_dir = output_dir.resolve()
        output_dir.mkdir(parents=True, exist_ok=True)
        total_pages = doc.page_count
        output_paths: list[Path] = []

        logger.info(
            "Splitting '%s' into %d chapters (level %d)",
            input_path.name,
            len(chapters),
            level,
        )

        for i, (title, start_page) in enumerate(chapters):
            start = start_page - 1  # TOC pages are 1-indexed
            end = chapters[i + 1][1] - 2 if i + 1 < len(chapters) else total_pages - 1

            safe_title = sanitize_filename(title)
            filename = f"{book_name}_chapter_{i + 1:02d}_{safe_title}.pdf"
            out_path = output_dir / filename

            with pymupdf.open() as chapter_doc:
                chapter_doc.insert_pdf(doc, from_page=start, to_page=end)

                # Rebuild TOC for this chunk
                chunk_toc = [
                    [lvl, t, p - start_page + 1] for lvl, t, p in toc if start_page <= p <= end + 1
                ]
                if chunk_toc:
                    min_lvl = min(entry[0] for entry in chunk_toc)
                    if min_lvl > 1:
                        chunk_toc = [[lvl - min_lvl + 1, t, p] for lvl, t, p in chunk_toc]
                    chapter_doc.set_toc(chunk_toc)

                chapter_doc.ez_save(str(out_path))
            output_paths.append(out_path)

            logger.info(
                "Chapter %02d: %s (pages %d-%d)",
                i + 1,
                title,
                start + 1,
                end + 1,
            )

    logger.info("%d files written to %s", len(output_paths), output_dir)
    return output_paths


def split_pdf_by_ranges(
    input_path: Path,
    output_dir: Path,
    book_name: str,
    ranges: str,
) -> list[Path]:
    """Split a PDF by explicit page ranges (for PDFs without TOC).

    Args:
        input_path: Path to the source PDF.
        output_dir: Directory to write chapter PDFs into.
        book_name: Base name used in output filenames.
        ranges: Comma-separated page ranges, e.g. "1-30,31-60,61-90".

    Returns:
        List of paths to the generated chapter PDF files.
    """
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    output_paths: list[Path] = []

    with pymupdf.open(input_path) as doc:
        for i, range_str in enumerate(ranges.split(",")):
            range_str = range_str.strip()
            if "-" in range_str:
                start_s, end_s = range_str.split("-", 1)
                start = int(start_s) - 1
                end = min(int(end_s) - 1, doc.page_count - 1)
            else:
                start = int(range_str) - 1
                end = start

            filename = f"{book_name}_part_{i + 1:02d}.pdf"
            out_path = output_dir / filename

            with pymupdf.open() as chapter_doc:
                chapter_doc.insert_pdf(doc, from_page=start, to_page=end)
                chapter_doc.ez_save(str(out_path))

            output_paths.append(out_path)
            logger.info("Part %02d: pages %d-%d", i + 1, start + 1, end + 1)

    logger.info("%d files written to %s", len(output_paths), output_dir)
    return output_paths
