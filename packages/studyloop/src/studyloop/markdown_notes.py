"""Clean-Markdown normalisation for parking-lot notes.

Parking-lot notes are stored as Markdown, not HTML and not a bespoke format.
That is a deliberate durability choice: a note written today must still open
in Obsidian, a text editor, or a future viewport years from now.

"Clean" here is a concrete contract, not a vibe:

1. LF line endings only (CRLF/CR normalised) — no mixed-EOL diffs.
2. No trailing whitespace on any line — except Markdown's two-space hard
   break, which is kept as exactly two spaces *and only when a line of
   content follows it* (a hard break with nothing after it renders nothing).
3. Tabs used for indentation become spaces (2 per tab) so nesting renders
   consistently across renderers.
4. At most one blank line in a row outside fenced code blocks (inside a fence,
   content is byte-preserved — blank lines can be semantically meaningful).
5. Unterminated fenced code block gets its closing fence appended, so a
   half-typed note can never swallow the rest of the document.
6. Exactly one trailing newline, no leading blank lines.

Everything here is pure and deterministic — no DB, no I/O — so it is directly
unit-testable and safe to call on every save.
"""

from __future__ import annotations

import re

__all__ = [
    "MERMAID_TEMPLATE",
    "extract_diagrams",
    "has_diagram",
    "normalise_markdown",
    "summarise_markdown",
]

_FENCE_RE = re.compile(r"^(\s*)(`{3,}|~{3,})(.*)$")
_TAB_INDENT_RE = re.compile(r"^[\t ]+")

# A starter diagram the UI can insert with one click. Kept here (not in JS) so
# the server-side and client-side notion of "add a diagram" cannot drift.
MERMAID_TEMPLATE = """```mermaid
graph TD
    A[Parked thought] --> B[Why it mattered]
    B --> C[What to try next]
```"""


def _expand_indent_tabs(line: str, width: int = 2) -> str:
    """Replace tabs in the *leading* whitespace only (never inside content)."""
    match = _TAB_INDENT_RE.match(line)
    if not match or "\t" not in match.group(0):
        return line
    indent = match.group(0).replace("\t", " " * width)
    return indent + line[match.end() :]


def _strip_trailing(line: str) -> str:
    """Strip trailing whitespace, preserving a Markdown hard line break.

    Two-or-more trailing spaces are Markdown's hard break; collapse to exactly
    two so the intent survives without accumulating whitespace noise.
    """
    stripped = line.rstrip()
    if stripped and line != stripped and len(line) - len(stripped) >= 2:
        return stripped + "  "
    return stripped


def normalise_markdown(text: str | None) -> str:
    """Return ``text`` as clean Markdown (see module docstring for the contract).

    ``None`` and whitespace-only input normalise to ``""`` — an empty note is
    stored as empty, never as a stray newline.
    """
    if not text:
        return ""

    body = text.replace("\r\n", "\n").replace("\r", "\n")
    out: list[str] = []
    fenced: set[int] = set()  # indices of lines inside a fenced block
    fence: str | None = None  # active fence marker while inside a code block

    for raw in body.split("\n"):
        match = _FENCE_RE.match(raw)
        if fence is None:
            if match and match.group(2)[0] in "`~":
                fence = match.group(2)[0] * 3
                out.append(_strip_trailing(_expand_indent_tabs(raw)))
                continue
            line = _strip_trailing(_expand_indent_tabs(raw))
            # Collapse runs of blank lines (outside fences) to a single blank.
            if not line and out and not out[-1]:
                continue
            out.append(line)
        else:
            # Inside a fence: preserve content byte-for-byte apart from EOL.
            fenced.add(len(out))
            out.append(raw)
            if match and match.group(2).startswith(fence):
                fence = None

    if fence is not None:
        # Unterminated fence — close it so the note can't eat the document.
        # Drop the trailing blank lines first (usually just the final newline's
        # empty split element) so the closing fence sits against the content.
        while out and not out[-1].strip():
            fenced.discard(len(out) - 1)
            out.pop()
        out.append(fence)

    while out and not out[0]:
        out.pop(0)
        fenced = {i - 1 for i in fenced}
    while out and not out[-1]:
        out.pop()

    # A hard line break is only meaningful when a line of content follows it.
    # Preserving a trailing "  " at the end of a paragraph or document keeps
    # invisible whitespace alive for no rendering benefit — strip those.
    # Never applied inside a fence: code is byte-preserved by contract.
    for i, line in enumerate(out):
        if i in fenced:
            continue
        if line.endswith("  ") and (i + 1 >= len(out) or not out[i + 1].strip()):
            out[i] = line.rstrip()

    return "\n".join(out) + "\n" if out else ""


def extract_diagrams(text: str | None) -> list[str]:
    """Return the raw source of every ```mermaid fenced block in ``text``."""
    if not text:
        return []
    diagrams: list[str] = []
    buffer: list[str] | None = None
    for line in text.replace("\r\n", "\n").split("\n"):
        stripped = line.strip()
        if buffer is None:
            if stripped.startswith("```") and stripped[3:].strip().lower() == "mermaid":
                buffer = []
            continue
        if stripped.startswith("```"):
            diagrams.append("\n".join(buffer).strip())
            buffer = None
            continue
        buffer.append(line)
    if buffer:  # unterminated fence still counts as a diagram
        diagrams.append("\n".join(buffer).strip())
    return [d for d in diagrams if d]


def has_diagram(text: str | None) -> bool:
    """True when the note contains at least one mermaid diagram block."""
    return bool(extract_diagrams(text))


def summarise_markdown(text: str | None, limit: int = 140) -> str:
    """One-line plain-text preview of a note — for collapsed Kanban cards.

    Drops fenced blocks, heading markers, list bullets, emphasis and link
    syntax so a card shows readable prose rather than punctuation soup.
    """
    if not text:
        return ""
    t = re.sub(r"```[\s\S]*?```", " ", text)
    t = re.sub(r"~~~[\s\S]*?~~~", " ", t)
    t = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", t)
    t = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", t)
    t = re.sub(r"`([^`]*)`", r"\1", t)
    t = re.sub(r"^#{1,6}[ \t]+", "", t, flags=re.MULTILINE)
    t = re.sub(r"^[ \t]*>[ \t]?", "", t, flags=re.MULTILINE)
    t = re.sub(r"^[ \t]*([-*+]|\d+\.)[ \t]+", "", t, flags=re.MULTILINE)
    t = re.sub(r"(\*\*|__)(.*?)\1", r"\2", t)
    t = re.sub(r"(\*|_)(.*?)\1", r"\2", t)
    t = re.sub(r"~~(.*?)~~", r"\1", t)
    t = " ".join(t.split())
    if len(t) <= limit:
        return t
    return t[: limit - 1].rstrip() + "…"
