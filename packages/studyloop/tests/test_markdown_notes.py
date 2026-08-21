"""Tests for markdown_notes.py — the clean-Markdown contract for parked notes.

Each test names the specific clause of the contract it pins, so a future change
that loosens one of them fails loudly rather than silently degrading notes.
"""

from __future__ import annotations

from studyloop.markdown_notes import (
    MERMAID_TEMPLATE,
    extract_diagrams,
    has_diagram,
    normalise_markdown,
    summarise_markdown,
)

# ---------------------------------------------------------------------------
# normalise_markdown — clause by clause
# ---------------------------------------------------------------------------


def test_empty_input_normalises_to_empty_string() -> None:
    """An empty note is stored as "", never as a stray newline."""
    assert normalise_markdown(None) == ""
    assert normalise_markdown("") == ""
    assert normalise_markdown("   \n\n  \n") == ""


def test_crlf_and_cr_become_lf() -> None:
    """Clause 1: LF line endings only."""
    assert normalise_markdown("a\r\nb\rc") == "a\nb\nc\n"


def test_trailing_whitespace_stripped() -> None:
    """Clause 2: no trailing whitespace."""
    assert normalise_markdown("hello   \nworld\t\n") == "hello  \nworld\n"


def test_single_trailing_space_is_dropped_not_promoted() -> None:
    """One trailing space is noise (not a hard break) — drop it."""
    assert normalise_markdown("hello \n") == "hello\n"


def test_two_space_hard_break_preserved_as_exactly_two() -> None:
    """Clause 2 exception: Markdown's two-space hard break survives."""
    assert normalise_markdown("line one     \nline two\n") == "line one  \nline two\n"


def test_leading_tabs_become_spaces() -> None:
    """Clause 3: indentation tabs → 2 spaces each."""
    assert normalise_markdown("- a\n\t- b\n\t\t- c\n") == "- a\n  - b\n    - c\n"


def test_tab_inside_content_is_untouched() -> None:
    """Only *leading* whitespace is expanded — inline tabs are content."""
    out = normalise_markdown("a\tb\n")
    assert out == "a\tb\n"


def test_blank_line_runs_collapse_outside_fences() -> None:
    """Clause 4: at most one blank line in a row."""
    assert normalise_markdown("a\n\n\n\n\nb\n") == "a\n\nb\n"


def test_blank_lines_preserved_inside_fence() -> None:
    """Clause 4 exception: inside a fence, blank lines can be meaningful."""
    src = "```python\ndef a():\n\n\n    pass\n```\n"
    assert normalise_markdown(src) == src


def test_fence_content_is_byte_preserved() -> None:
    """Code must not be reformatted — trailing spaces inside a fence stay."""
    src = "```\nx = 1   \n\ty = 2\n```\n"
    assert normalise_markdown(src) == src


def test_unterminated_fence_is_closed() -> None:
    """Clause 5: a half-typed fence can't swallow the document."""
    out = normalise_markdown("intro\n```python\nx = 1\n")
    assert out == "intro\n```python\nx = 1\n```\n"
    assert out.count("```") == 2


def test_unterminated_tilde_fence_is_closed_with_tildes() -> None:
    out = normalise_markdown("~~~\nraw\n")
    assert out.endswith("~~~\n")
    assert out == "~~~\nraw\n~~~\n"


def test_leading_and_trailing_blank_lines_removed() -> None:
    """Clause 6: exactly one trailing newline, no leading blanks."""
    assert normalise_markdown("\n\n# Title\n\ntext\n\n\n") == "# Title\n\ntext\n"


def test_normalisation_is_idempotent() -> None:
    """Re-saving an already-clean note must not change it."""
    messy = "\r\n# T\r\n\r\n\r\n- a\t\n\t- b   \n```js\nlet x=1  \n```\n\n\n"
    once = normalise_markdown(messy)
    assert normalise_markdown(once) == once


def test_mermaid_fence_survives_normalisation_intact() -> None:
    """Diagram sources must round-trip exactly — a mangled diagram won't render."""
    out = normalise_markdown(MERMAID_TEMPLATE)
    assert "```mermaid" in out
    assert "graph TD" in out
    assert extract_diagrams(out) == extract_diagrams(MERMAID_TEMPLATE)


def test_long_fence_marker_closes_correctly() -> None:
    """A 4-backtick fence is closed by 4+ backticks, not by an inner 3."""
    src = "````\n```\ninner\n```\n````\n"
    assert normalise_markdown(src) == src


# ---------------------------------------------------------------------------
# extract_diagrams / has_diagram
# ---------------------------------------------------------------------------


def test_extract_diagrams_finds_multiple() -> None:
    md = (
        "# N\n\n```mermaid\ngraph TD\n A-->B\n```\n\n"
        "prose\n\n```mermaid\nsequenceDiagram\n A->>B: hi\n```\n"
    )
    diagrams = extract_diagrams(md)
    assert len(diagrams) == 2
    assert diagrams[0] == "graph TD\n A-->B"
    assert diagrams[1].startswith("sequenceDiagram")


def test_extract_diagrams_ignores_other_languages() -> None:
    assert extract_diagrams("```python\ngraph TD\n```") == []


def test_extract_diagrams_case_insensitive_label() -> None:
    assert extract_diagrams("```Mermaid\ngraph TD\n A-->B\n```") == ["graph TD\n A-->B"]


def test_has_diagram_flags() -> None:
    assert has_diagram("```mermaid\ngraph TD\n A-->B\n```")
    assert not has_diagram("just prose")
    assert not has_diagram(None)


def test_extract_diagrams_handles_unterminated_fence() -> None:
    assert extract_diagrams("```mermaid\ngraph TD\n A-->B") == ["graph TD\n A-->B"]


# ---------------------------------------------------------------------------
# summarise_markdown — collapsed-card preview
# ---------------------------------------------------------------------------


def test_summarise_strips_markdown_syntax() -> None:
    out = summarise_markdown("# Heading\n\n- **bold** and `code` and [link](http://x)")
    assert out == "Heading bold and code and link"


def test_summarise_drops_code_and_diagram_blocks() -> None:
    out = summarise_markdown("Intro\n\n```mermaid\ngraph TD\n A-->B\n```\n\nOutro")
    assert "graph" not in out
    assert out == "Intro Outro"


def test_summarise_truncates_with_ellipsis() -> None:
    out = summarise_markdown("word " * 100, limit=20)
    assert len(out) <= 20
    assert out.endswith("…")


def test_summarise_empty_input() -> None:
    assert summarise_markdown(None) == ""
    assert summarise_markdown("") == ""
