"""Socratic note-companion prompt builder."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from studyloop.settings import load_settings

if TYPE_CHECKING:
    from pathlib import Path

CompanionMode = Literal["recall", "diagram", "trace", "teachback", "repair"]

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)
_CODE_FENCE_RE = re.compile(r"```.*?```", re.DOTALL)


@dataclass(frozen=True)
class NoteChunk:
    heading: str
    kind: str
    preview: str

    def to_json_dict(self) -> dict[str, str]:
        return {"heading": self.heading, "kind": self.kind, "preview": self.preview}


@dataclass(frozen=True)
class NoteCompanionPack:
    path: str
    title: str
    mode: CompanionMode
    prompt: str
    chunks: list[NoteChunk]
    suggested_command: str

    def to_json_dict(self) -> dict:
        return {
            "path": self.path,
            "title": self.title,
            "mode": self.mode,
            "prompt": self.prompt,
            "chunks": [chunk.to_json_dict() for chunk in self.chunks],
            "suggested_command": self.suggested_command,
        }


def allowed_note_roots() -> list[Path]:
    """Return configured roots a note companion may read from."""
    settings = load_settings()
    roots = [
        settings.obsidian.vault_path,
        *settings.content.study_paths,
        settings.content.base_path,
    ]
    unique: list[Path] = []
    seen: set[Path] = set()
    for root in roots:
        resolved = root.expanduser().resolve()
        if resolved not in seen:
            seen.add(resolved)
            unique.append(resolved)
    return unique


def resolve_note_path(path: Path, roots: list[Path] | None = None) -> Path:
    """Resolve and validate a note path against allowed study roots."""
    candidate = path.expanduser().resolve()
    if not candidate.exists():
        msg = f"Note not found: {path}"
        raise ValueError(msg)
    if not candidate.is_file():
        msg = f"Note path is not a file: {path}"
        raise ValueError(msg)
    if candidate.suffix.lower() not in {".md", ".markdown", ".txt"}:
        msg = "Note companion only reads markdown/text notes."
        raise ValueError(msg)

    allowed = roots or allowed_note_roots()
    if not any(candidate.is_relative_to(root) for root in allowed):
        msg = "Note is outside the configured StudyLoop study/vault roots."
        raise ValueError(msg)
    return candidate


def _strip_frontmatter(text: str) -> str:
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            return text[end + 4 :].lstrip()
    return text


def _chunk_note(text: str, *, limit: int = 8) -> list[NoteChunk]:
    stripped = _strip_frontmatter(text)
    headings = list(_HEADING_RE.finditer(stripped))
    chunks: list[NoteChunk] = []

    if headings:
        for index, match in enumerate(headings[:limit]):
            start = match.end()
            end = headings[index + 1].start() if index + 1 < len(headings) else len(stripped)
            body = stripped[start:end].strip()
            chunks.append(
                NoteChunk(
                    heading=match.group(2).strip(),
                    kind="heading",
                    preview=" ".join(body.split())[:360],
                )
            )

    for fence in _CODE_FENCE_RE.finditer(stripped):
        code = fence.group(0).strip()
        chunks.append(NoteChunk(heading="Code block", kind="code", preview=code[:360]))
        if len(chunks) >= limit:
            break

    if not chunks:
        chunks.append(
            NoteChunk(
                heading="Whole note",
                kind="note",
                preview=" ".join(stripped.split())[:420],
            )
        )
    return chunks[:limit]


def _mode_instruction(mode: CompanionMode) -> str:
    if mode == "diagram":
        return (
            "Use the note to ask Socratic questions that turn the learner's answer "
            "into a Mermaid diagram. When a structure or flow appears, request a "
            "small `mermaid` block and ask what each edge means."
        )
    if mode == "trace":
        return (
            "Guide a concrete trace. Pick one code block or process path, ask for "
            "the input, intermediate state, and output, then compare with the note."
        )
    if mode == "teachback":
        return (
            "Run a teach-back. Ask the learner to explain the core concept in their "
            "own words, score accuracy, own words, structure, depth, and transfer."
        )
    if mode == "repair":
        return (
            "Find the smallest shaky prerequisite. Use demand-light repair: one "
            "tiny example, one question, one evidence command."
        )
    return (
        "Run active recall. Hide the note content initially, ask one small recall "
        "question, then use the note only to repair gaps."
    )


def build_note_companion_pack(path: Path, *, mode: CompanionMode = "recall") -> NoteCompanionPack:
    """Build a Socratic context pack from a note path."""
    resolved = resolve_note_path(path)
    text = resolved.read_text(encoding="utf-8", errors="replace")
    chunks = _chunk_note(text)
    title = resolved.stem.replace("-", " ").replace("_", " ").title()
    concept = title.lower()
    topic = resolved.parent.name.lower().replace(" ", "-") or "study"
    suggested = (
        f'studyloop teachback "{concept}" -t "{topic}" --score "3,3,3,3,3" '
        "--type structured"
        if mode == "teachback"
        else f'studyloop progress "{concept}" -t "{topic}" -c learning'
    )

    chunk_lines = "\n".join(
        f"- {chunk.kind}: {chunk.heading} -- {chunk.preview}" for chunk in chunks
    )
    prompt = f"""You are StudyLoop's AuDHD-aware Socratic mentor.

Note: {resolved}
Mode: {mode}

Instruction:
{_mode_instruction(mode)}

Context pack:
{chunk_lines}

Rules:
- Start concrete and hands-on.
- Keep each exchange small.
- Prefer visual, audible, or runnable evidence when it helps.
- Do not lecture from the note; make the learner retrieve, trace, draw, or teach.
- End the flow by recording evidence with:
  {suggested}
"""
    return NoteCompanionPack(
        path=str(resolved),
        title=title,
        mode=mode,
        prompt=prompt,
        chunks=chunks,
        suggested_command=suggested,
    )


def pack_to_json(pack: NoteCompanionPack) -> str:
    return json.dumps(pack.to_json_dict(), indent=2)
