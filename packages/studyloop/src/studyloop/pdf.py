"""Markdown → PDF conversion with mermaid diagram rendering."""

from __future__ import annotations

import re
import subprocess
import tempfile
from pathlib import Path

MERMAID_BLOCK = re.compile(r"```mermaid\s*\n(.*?)```", re.DOTALL)


def _render_mermaid(code: str, output_path: Path) -> bool:
    """Render a mermaid code block to PNG."""
    with tempfile.NamedTemporaryFile(suffix=".mmd", mode="w", delete=False) as f:
        f.write(code)
        mmd_path = f.name
    result = subprocess.run(
        [
            "npx",
            "-y",
            "@mermaid-js/mermaid-cli",
            "-i",
            mmd_path,
            "-o",
            str(output_path),
            "-b",
            "white",
            "-q",
        ],
        capture_output=True,
        text=True,
    )
    Path(mmd_path).unlink(missing_ok=True)
    return result.returncode == 0 and output_path.exists()


def _preprocess_mermaid(md_content: str, work_dir: Path) -> str:
    """Replace mermaid code blocks with rendered PNG image references."""
    counter = 0

    def replace_block(match: re.Match) -> str:
        nonlocal counter
        counter += 1
        code = match.group(1).strip()
        png_path = work_dir / f"mermaid_{counter}.png"
        if _render_mermaid(code, png_path):
            return f"![diagram]({png_path})"
        # Fallback: keep as code block if rendering fails
        return match.group(0)

    return MERMAID_BLOCK.sub(replace_block, md_content)


def md_to_pdf(md_path: Path, pdf_dir: Path, unique_name: str | None = None) -> Path | None:
    """Convert markdown to PDF, rendering mermaid diagrams as images."""
    stem = unique_name or md_path.stem
    pdf_path = pdf_dir / (stem + ".pdf")
    content = md_path.read_text()

    has_mermaid = "```mermaid" in content

    with tempfile.TemporaryDirectory(prefix="studyctl-mermaid-") as mermaid_dir:
        if has_mermaid:
            processed = _preprocess_mermaid(content, Path(mermaid_dir))
            # Write processed markdown to temp file
            tmp_md = Path(mermaid_dir) / md_path.name
            tmp_md.write_text(processed)
            source = tmp_md
        else:
            source = md_path

        result = subprocess.run(
            [
                "pandoc",
                str(source),
                "-o",
                str(pdf_path),
                "--pdf-engine=xelatex",
                "-V",
                "geometry:margin=1in",
            ],
            capture_output=True,
            text=True,
        )

    if result.returncode == 0 and pdf_path.exists():
        return pdf_path
    return None
