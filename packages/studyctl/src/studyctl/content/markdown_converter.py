"""Markdown to PDF conversion with mermaid diagram rendering."""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

_WIKILINK_RE = re.compile(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]")
_FRONTMATTER_RE = re.compile(r"^---\s*\n.*?\n---\s*\n", re.DOTALL)
_MERMAID_BLOCK_RE = re.compile(r"```mermaid\s*\n(.*?)```", re.DOTALL)


class ConversionError(Exception):
    """Raised when markdown to PDF conversion fails."""


def check_prerequisites() -> list[str]:
    """Check that pandoc and mmdc are installed.

    Returns:
        List of missing tool names. Empty if all present.
    """
    missing = []
    if not shutil.which("pandoc"):
        missing.append("pandoc")
    if not shutil.which("mmdc"):
        missing.append("mmdc (@mermaid-js/mermaid-cli)")
    if not shutil.which("typst"):
        missing.append("typst (brew install typst)")
    return missing


def preprocess_markdown(content: str) -> str:
    """Clean markdown for pandoc conversion.

    Strips YAML frontmatter and converts Obsidian wikilinks to plain text.

    Args:
        content: Raw markdown file content.

    Returns:
        Cleaned markdown ready for pandoc.
    """
    content = _FRONTMATTER_RE.sub("", content)
    content = _WIKILINK_RE.sub(lambda m: m.group(2) or m.group(1), content)
    return content


# Matches unquoted node labels containing / (file paths), e.g. C[/home/user]
# but NOT already-quoted labels like C["some text"]
_UNQUOTED_PATH_NODE_RE = re.compile(r'\[(/[^\]"]+)\]')

# Matches <br/> or <br> in text (not valid in all mermaid contexts)
_HTML_BR_RE = re.compile(r"<br\s*/?>")


def _sanitize_mermaid(code: str) -> str:
    """Fix common mermaid syntax issues that cause parser failures.

    Fixes:
    - Unquoted node labels containing / (file paths) -> wraps in quotes
    - <br/> tags in state diagram notes -> replaced with newline character
    """
    # Wrap unquoted path-like node labels in quotes: [/home/user] -> ["/home/user"]
    code = _UNQUOTED_PATH_NODE_RE.sub(lambda m: f'["{m.group(1)}"]', code)

    # Replace <br/> with space -- special separators (|, /, \n) break state diagram notes
    code = _HTML_BR_RE.sub(" ", code)

    # In state diagram notes, colons after the initial "note ... :" break the parser.
    # Strip extra colons from note body text.
    def _fix_note_colons(m: re.Match) -> str:
        prefix = m.group(1)  # "note right of X: "
        body = m.group(2)
        return prefix + body.replace(":", " -")

    code = re.sub(
        r"(note\s+(?:right|left)\s+of\s+\w+\s*:\s*)(.*)",
        _fix_note_colons,
        code,
    )

    return code


def _render_mermaid_to_png(mermaid_code: str, output_dir: Path, index: int) -> Path | None:
    """Render a mermaid diagram to PNG using mmdc.

    Uses PNG (not SVG) because SVG foreignObject elements lose text
    when converted to PDF by pandoc/typst.
    """
    mermaid_code = _sanitize_mermaid(mermaid_code)
    png_path = output_dir / f"mermaid_{index:03d}.png"

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".mmd", dir=str(output_dir), delete=False
    ) as f:
        f.write(mermaid_code)
        mmd_path = f.name

    try:
        result = subprocess.run(
            ["mmdc", "-i", mmd_path, "-o", str(png_path), "-b", "white", "-s", "2"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0 or not png_path.exists():
            logger.warning("mmdc failed for diagram %d: %s", index, result.stderr[:200])
            return None
        return png_path
    except subprocess.TimeoutExpired:
        logger.warning("mmdc timed out for diagram %d", index)
        return None
    finally:
        Path(mmd_path).unlink(missing_ok=True)


def prerender_mermaid_diagrams(content: str, work_dir: Path) -> str:
    """Replace mermaid code blocks with rendered SVG image references.

    Args:
        content: Markdown content with mermaid blocks.
        work_dir: Directory for temporary SVG files.

    Returns:
        Markdown with mermaid blocks replaced by image references.
    """
    work_dir.mkdir(parents=True, exist_ok=True)
    counter = 0

    def _replace(match: re.Match) -> str:
        nonlocal counter
        counter += 1
        mermaid_code = match.group(1)
        png_path = _render_mermaid_to_png(mermaid_code, work_dir, counter)
        if png_path:
            return f"![Diagram {counter}]({png_path})"
        return f"```\n{mermaid_code}```"

    result = _MERMAID_BLOCK_RE.sub(_replace, content)
    logger.debug("Rendered %d mermaid diagrams", counter)
    return result


def convert_markdown_to_pdf(
    md_path: Path,
    output_path: Path,
) -> Path:
    """Convert a markdown file to PDF with pre-rendered mermaid diagrams.

    Args:
        md_path: Path to the source markdown file.
        output_path: Path for the output PDF file.

    Returns:
        Path to the generated PDF.

    Raises:
        ConversionError: If pandoc fails or prerequisites are missing.
    """
    missing = check_prerequisites()
    if missing:
        raise ConversionError(
            f"Missing prerequisites: {', '.join(missing)}. "
            "Install with: brew install pandoc && npm install -g @mermaid-js/mermaid-cli"
        )

    raw_content = md_path.read_text(encoding="utf-8")
    cleaned = preprocess_markdown(raw_content)

    work_dir = output_path.parent / f".mermaid_{md_path.stem}"
    cleaned = prerender_mermaid_diagrams(cleaned, work_dir)

    temp_md = work_dir / f"{md_path.stem}_preprocessed.md"
    try:
        temp_md.write_text(cleaned, encoding="utf-8")
        output_path.parent.mkdir(parents=True, exist_ok=True)

        cmd = [
            "pandoc",
            str(temp_md),
            "-o",
            str(output_path),
            "--pdf-engine=typst",
        ]

        logger.debug("Running: %s", " ".join(cmd))
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)

        if result.returncode != 0:
            # Fallback to default engine (pdflatex) if typst fails
            cmd_fallback = [
                "pandoc",
                str(temp_md),
                "-o",
                str(output_path),
                "-V",
                "geometry:margin=1in",
            ]
            result = subprocess.run(cmd_fallback, capture_output=True, text=True, timeout=180)
            if result.returncode != 0:
                raise ConversionError(f"pandoc failed for {md_path.name}: {result.stderr[:500]}")

        if not output_path.exists():
            raise ConversionError(f"pandoc produced no output for {md_path.name}")

        logger.info("Converted %s -> %s", md_path.name, output_path.name)
        return output_path

    finally:
        if work_dir.exists():
            shutil.rmtree(work_dir, ignore_errors=True)


def convert_directory(
    source_dir: Path,
    output_dir: Path,
) -> list[Path]:
    """Convert all markdown files in a directory to PDFs.

    Files are sorted alphabetically and numbered sequentially.

    Args:
        source_dir: Directory containing .md files.
        output_dir: Directory to write PDFs into.

    Returns:
        List of paths to generated PDF files, in order.

    Raises:
        ConversionError: If prerequisites are missing.
        ValueError: If source_dir doesn't exist or has no .md files.
    """
    if not source_dir.is_dir():
        raise ValueError(f"Source directory does not exist: {source_dir}")

    md_files = sorted(source_dir.glob("*.md"))
    if not md_files:
        raise ValueError(f"No .md files found in {source_dir}")

    missing = check_prerequisites()
    if missing:
        raise ConversionError(
            f"Missing prerequisites: {', '.join(missing)}. "
            "Install with: brew install pandoc && npm install -g @mermaid-js/mermaid-cli"
        )

    pdf_dir = output_dir / "pdfs"
    pdf_dir.mkdir(parents=True, exist_ok=True)

    pdfs: list[Path] = []
    for i, md_path in enumerate(md_files, 1):
        stem = re.sub(r"-{2,}", "-", md_path.stem.lower().replace(" ", "_"))
        pdf_name = f"{i:02d}-{stem}.pdf"
        pdf_path = pdf_dir / pdf_name

        try:
            convert_markdown_to_pdf(md_path, pdf_path)
            pdfs.append(pdf_path)
        except ConversionError as exc:
            logger.error("Failed to convert %s: %s", md_path.name, exc)

    logger.info("Converted %d/%d files to %s", len(pdfs), len(md_files), pdf_dir)
    return pdfs
