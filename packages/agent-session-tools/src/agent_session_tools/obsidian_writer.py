"""Obsidian vault writer for agent session-memory notes.

Writes structured Markdown notes for AI coding sessions into an Obsidian vault.
Notes carry Dataview-ready frontmatter and [[wikilink]] backlinks to existing
vault topic notes. Per-project MOC index notes list session notes in
reverse-chronological order.

Import boundary: this module must NOT import from studyloop.
"""

from __future__ import annotations

import hashlib
import re
import sqlite3
from pathlib import Path
from typing import Any

import yaml

from agent_session_tools.config_loader import load_config
from agent_session_tools.formatters import format_summary

# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------

_OBSIDIAN_DEFAULTS: dict[str, Any] = {
    "export_enabled": False,
    "vault_path": "~/Obsidian/Personal",
    "memory_dir": "AgentMemory",
    "moc_dir": "AgentMemory/MOC",
    "backlinks": True,
    "granularity": "both",
    "filename_template": "$date-$source-$slug",
}

# Dotfolders to skip when building the topic index
_SKIP_DOTFOLDERS = {".obsidian", ".smart-env", ".trash", ".git"}


def get_obsidian_config(config: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return the merged obsidian sub-config with defaults applied.

    Mirrors ``get_semantic_config`` in config_loader. Accepts an explicit
    *config* dict so the function is unit-testable without touching disk.

    Returns:
        Dict with keys: export_enabled, vault_path (str), memory_dir,
        moc_dir, backlinks, granularity, filename_template.
    """
    if config is None:
        config = load_config()

    raw: dict[str, Any] = dict(_OBSIDIAN_DEFAULTS)

    # Pull the flat scalar as a default vault_path fallback
    if obs_base := config.get("obsidian_base"):
        raw["vault_path"] = str(obs_base)

    # Overlay the structured obsidian: section if present
    obsidian_section = config.get("obsidian")
    if isinstance(obsidian_section, dict):
        raw.update(obsidian_section)

    return raw


# ---------------------------------------------------------------------------
# Slug / filename helpers
# ---------------------------------------------------------------------------

_SAFE_CHARS_RE = re.compile(r"[^a-z0-9-]")
_SAFE_DATE_RE = re.compile(r"[^0-9-]")


def _safe_date(raw_date: object) -> str:
    """Return a filesystem-safe date string (digits and hyphens only).

    Session ``created_at`` values are untrusted (they originate from session
    files on disk), so this strips anything that could escape the target
    directory (``/``, ``.``, ``..``) before the value is used in a path.
    """
    date_str = str(raw_date)[:10] if raw_date else "1970-01-01"
    cleaned = _SAFE_DATE_RE.sub("", date_str)
    return cleaned or "1970-01-01"


def _slugify(text: str) -> str:
    """Convert *text* to a lowercase-kebab safe slug."""
    lowered = text.lower()
    # Replace common separators with hyphens first
    lowered = re.sub(r"[\s/_]+", "-", lowered)
    # Strip anything else
    lowered = _SAFE_CHARS_RE.sub("", lowered)
    # Collapse multiple hyphens and strip edge hyphens
    lowered = re.sub(r"-{2,}", "-", lowered).strip("-")
    return lowered or "session"


def _make_slug(project_path: str | None, session_id: str) -> str:
    """Build a unique slug: <project-name>-<last-8-chars-of-id>."""
    project_name = Path(project_path).name if project_path else "unknown"
    suffix = (session_id or "")[-8:]
    return _slugify(f"{project_name}-{suffix}")


def _make_filename(date_str: str, source: str, slug: str) -> str:
    """Return the bare filename (no extension): <date>-<source>-<slug>."""
    return f"{date_str}-{_slugify(source)}-{slug}"


# ---------------------------------------------------------------------------
# Frontmatter / body builders
# ---------------------------------------------------------------------------


def _content_hash(content: str) -> str:
    """Return an 8-char hex SHA-256 digest of *content*."""
    return hashlib.sha256(content.encode()).hexdigest()[:8]


def _parse_existing_hash(file_path: Path) -> str | None:
    """Read the ``content_hash`` field from an existing note's frontmatter.

    Returns None if the file has no parseable frontmatter or no hash field.
    """
    try:
        text = file_path.read_text(encoding="utf-8")
    except OSError:
        return None
    if not text.startswith("---"):
        return None
    parts = text.split("---", 2)
    if len(parts) < 3:
        return None
    try:
        fm = yaml.safe_load(parts[1])
        if isinstance(fm, dict):
            return fm.get("content_hash")
    except yaml.YAMLError:
        pass
    return None


def _build_frontmatter(
    note_id: str,
    date_str: str,
    session: dict[str, Any],
    content_hash_val: str,
) -> str:
    """Render YAML frontmatter block for a session-memory note.

    Args:
        note_id: The full note identifier (filename stem).
        date_str: ISO date string (YYYY-MM-DD).
        session: Session row dict from the database.
        content_hash_val: Pre-computed hash of the note body.

    Returns:
        Frontmatter block including the leading and trailing ``---`` delimiters.
    """
    source = session.get("source") or "unknown"
    project_path = session.get("project_path") or ""
    source_project = Path(project_path).name if project_path else "unknown"
    git_branch = session.get("git_branch") or None

    fm: dict[str, Any] = {
        "type": "agent-memory",
        "id": note_id,
        "created": date_str,
        "updated": date_str,
        "status": "active",
        "source_tool": source,
        "source_project": source_project,
        "session_id": session.get("id") or "",
        "git_branch": git_branch,
        "tags": ["agent-memory", source],
        "date": date_str,
        "about": [],
        "content_hash": content_hash_val,
    }

    return (
        "---\n" + yaml.dump(fm, default_flow_style=False, allow_unicode=True) + "---\n"
    )


def _extract_files_touched(messages: list[dict[str, Any]]) -> list[str]:
    """Heuristically derive file paths mentioned in tool-use / metadata.

    Scans ``tool_use`` and ``tool_result`` messages for file path strings.
    Returns a deduplicated, ordered list; may return an empty list if none
    are found (callers should omit the section when empty).
    """
    seen: dict[str, None] = {}  # ordered set

    path_re = re.compile(r"(?:^|[\s\"'`(])(/[^\s\"'`,)]+\.[a-zA-Z]{1,10})\b")

    for msg in messages:
        role = msg.get("role", "")
        if role not in ("tool_use", "tool_result"):
            continue
        content = msg.get("content") or ""
        if not isinstance(content, str):
            # Some exporters store structured dicts; skip
            continue
        for match in path_re.finditer(content):
            candidate = match.group(1)
            if candidate not in seen:
                seen[candidate] = None

    return list(seen.keys())


def _build_body(
    session: dict[str, Any],
    messages: list[dict[str, Any]],
    date_str: str,
    related_links: list[str],
) -> str:
    """Build the Markdown body of a session-memory note.

    Args:
        session: Session dict.
        messages: Message dicts for this session.
        date_str: ISO date of the session.
        related_links: Pre-resolved ``[[wikilink]]`` strings for the ## Related section.

    Returns:
        Markdown body string (does NOT include frontmatter).
    """
    project_path = session.get("project_path") or ""
    source_project = Path(project_path).name if project_path else "Unknown"

    lines: list[str] = [
        f"# Session Memory — {source_project} ({date_str})",
        "",
    ]

    # Summary + Key Points from formatter
    summary_block = format_summary(session, messages)
    # Strip the H1 title line that format_summary emits (we have our own)
    summary_lines = summary_block.splitlines()
    if summary_lines and summary_lines[0].startswith("# "):
        summary_lines = summary_lines[1:]
    lines.extend(summary_lines)
    lines.append("")

    # Files Touched — only if derivable
    files = _extract_files_touched(messages)
    if files:
        lines.append("## Files Touched")
        for f in files:
            lines.append(f"- `{f}`")
        lines.append("")

    # Related — only if we have matches
    if related_links:
        lines.append("## Related")
        for link in related_links:
            lines.append(f"- {link}")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Topic index
# ---------------------------------------------------------------------------


def build_topic_index(vault_path: Path) -> dict[str, str]:
    """Scan vault Markdown files and build a lowercased-term → NoteTitle map.

    Skips dotfolders (e.g., ``.obsidian``, ``.trash``, ``.smart-env``, ``.git``).
    Collects note titles from filename stems and any ``aliases:`` frontmatter
    entries. Uses only stdlib + PyYAML (already a dependency); no new packages.

    Args:
        vault_path: Absolute path to the Obsidian vault root.

    Returns:
        Mapping from lowercased term to the canonical NoteTitle (filename stem).
        Terms include the note's own title and any configured aliases.
    """
    index: dict[str, str] = {}

    if not vault_path.is_dir():
        return index

    for md_file in vault_path.rglob("*.md"):
        # Skip anything inside a dotfolder
        parts = set(md_file.relative_to(vault_path).parts[:-1])  # parent folders
        if parts & _SKIP_DOTFOLDERS:
            continue
        # Also skip if any path component starts with '.' (e.g., .obsidian/...)
        if any(p.startswith(".") for p in md_file.relative_to(vault_path).parts[:-1]):
            continue

        note_title = md_file.stem
        # Register the note's own title
        index[note_title.lower()] = note_title

        # Try to parse frontmatter aliases
        try:
            text = md_file.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue

        if not text.startswith("---"):
            continue

        parts_split = text.split("---", 2)
        if len(parts_split) < 3:
            continue

        try:
            fm = yaml.safe_load(parts_split[1])
        except yaml.YAMLError:
            continue

        if not isinstance(fm, dict):
            continue

        aliases = fm.get("aliases", [])
        if isinstance(aliases, str):
            aliases = [aliases]
        if isinstance(aliases, list):
            for alias in aliases:
                if isinstance(alias, str) and alias.strip():
                    index[alias.lower()] = note_title

    return index


# ---------------------------------------------------------------------------
# Backlink injection
# ---------------------------------------------------------------------------


def inject_backlinks(body_topics: list[str], topic_index: dict[str, str]) -> list[str]:
    """Return ``[[NoteTitle]]`` wikilinks for topics that match the vault index.

    Matching is case-insensitive. The returned list contains unique wikilinks
    ordered by input appearance.

    Args:
        body_topics: List of topic/keyword strings to try to match.
        topic_index: Map produced by :func:`build_topic_index`.

    Returns:
        List of ``[[NoteTitle]]`` strings for matched topics.
    """
    seen: dict[str, None] = {}  # ordered dedup
    for topic in body_topics:
        normalized = topic.lower().strip()
        if normalized in topic_index:
            title = topic_index[normalized]
            wikilink = f"[[{title}]]"
            if wikilink not in seen:
                seen[wikilink] = None
    return list(seen.keys())


# ---------------------------------------------------------------------------
# Write single session note
# ---------------------------------------------------------------------------


def write_session_to_vault(
    session: dict[str, Any],
    messages: list[dict[str, Any]],
    vault_path: Path,
    obsidian_cfg: dict[str, Any] | None = None,
    topic_index: dict[str, str] | None = None,
) -> Path | None:
    """Write one Markdown note for *session* into the vault's memory directory.

    The note is placed at ``<vault_path>/<memory_dir>/<filename>.md``. Filename
    format: ``<YYYY-MM-DD>-<source>-<slug>.md``.

    Idempotent: if the target file already exists and its ``content_hash``
    frontmatter field matches the computed hash, the file is NOT overwritten and
    ``None`` is returned. Otherwise the file is written (or overwritten) and the
    path is returned.

    Args:
        session: Session dict (keys: id, source, project_path, git_branch,
            created_at, updated_at, metadata, import_fingerprint).
        messages: List of message dicts for this session.
        vault_path: Absolute path to the Obsidian vault root.
        obsidian_cfg: Obsidian sub-config (merged defaults). When ``None``,
            the config is loaded from disk — pass an explicit dict in tests.
        topic_index: Pre-built topic index from :func:`build_topic_index`.
            When provided, ``[[wikilink]]`` backlinks are injected into the
            ``## Related`` section. When ``None``, the section is omitted.

    Returns:
        The :class:`~pathlib.Path` of the written file, or ``None`` if skipped
        (unchanged content).
    """
    if obsidian_cfg is None:
        obsidian_cfg = get_obsidian_config()

    memory_dir_rel = obsidian_cfg.get("memory_dir", "AgentMemory")
    memory_dir = (vault_path / memory_dir_rel).resolve()
    memory_dir.mkdir(parents=True, exist_ok=True)

    # Date string — prefer created_at, fall back to updated_at or today.
    # _safe_date strips path separators: created_at is untrusted session data.
    raw_date = session.get("created_at") or session.get("updated_at") or ""
    date_str = _safe_date(raw_date)

    source = session.get("source") or "unknown"
    session_id = session.get("id") or ""
    project_path = session.get("project_path") or ""

    slug = _make_slug(project_path, session_id)
    note_id = _make_filename(date_str, source, slug)
    filename = f"{note_id}.md"
    target_path = (memory_dir / filename).resolve()

    # Containment guard: every path component is sanitized, but assert the
    # resolved target stays inside memory_dir so no future field can escape.
    if memory_dir not in target_path.parents:
        raise ValueError(
            f"Refusing to write outside the vault memory dir: {target_path}"
        )

    # Build body first (needed for hashing)
    related_links: list[str] = []
    if topic_index and obsidian_cfg.get("backlinks", True):
        # Derive topics from the project name and source as minimal heuristic
        project_name = Path(project_path).name if project_path else ""
        candidates = [t for t in [project_name, source] if t]
        related_links = inject_backlinks(candidates, topic_index)

    body = _build_body(session, messages, date_str, related_links)
    hash_val = _content_hash(body)

    # Idempotency check
    if target_path.exists():
        existing_hash = _parse_existing_hash(target_path)
        if existing_hash == hash_val:
            return None  # unchanged — skip

    frontmatter = _build_frontmatter(note_id, date_str, session, hash_val)
    full_content = frontmatter + "\n" + body

    target_path.write_text(full_content, encoding="utf-8")
    return target_path


# ---------------------------------------------------------------------------
# MOC writer
# ---------------------------------------------------------------------------


def write_moc(
    vault_path: Path,
    obsidian_cfg: dict[str, Any],
    project: str,
    note_ids: list[str],
) -> Path:
    """Regenerate the MOC (Map of Content) index note for *project*.

    Creates ``<vault_path>/<moc_dir>/<project>.md`` listing *note_ids* as
    ``[[id]]`` links in reverse-chronological order (input list assumed sorted
    ascending; function reverses it). The file is always overwritten so it
    stays accurate.

    Args:
        vault_path: Absolute path to the Obsidian vault root.
        obsidian_cfg: Obsidian sub-config dict.
        project: Project name (used as filename stem; will be slugified).
        note_ids: Ordered (ascending) list of note ID strings (filename stems).

    Returns:
        The :class:`~pathlib.Path` of the written MOC file.
    """
    moc_dir_rel = obsidian_cfg.get("moc_dir", "AgentMemory/MOC")
    moc_dir = vault_path / moc_dir_rel
    moc_dir.mkdir(parents=True, exist_ok=True)

    safe_project = _slugify(project)
    moc_path = moc_dir / f"{safe_project}.md"

    fm: dict[str, Any] = {
        "type": "agent-memory-moc",
        "project": project,
        "note_count": len(note_ids),
    }
    frontmatter = (
        "---\n" + yaml.dump(fm, default_flow_style=False, allow_unicode=True) + "---\n"
    )

    lines: list[str] = [
        f"# Agent Memory — {project}",
        "",
        f"*{len(note_ids)} session note(s) — reverse-chronological*",
        "",
    ]
    for nid in reversed(note_ids):
        lines.append(f"- [[{nid}]]")
    lines.append("")

    moc_path.write_text(frontmatter + "\n" + "\n".join(lines), encoding="utf-8")
    return moc_path


def _write_vault_index(
    vault_path: Path,
    obsidian_cfg: dict[str, Any],
    projects: list[str],
) -> Path:
    """Write the top-level ``_index.md`` MOC listing all projects.

    Args:
        vault_path: Absolute path to the Obsidian vault root.
        obsidian_cfg: Obsidian sub-config dict.
        projects: Sorted list of project names that have MOC notes.

    Returns:
        The :class:`~pathlib.Path` of the written index file.
    """
    moc_dir_rel = obsidian_cfg.get("moc_dir", "AgentMemory/MOC")
    moc_dir = vault_path / moc_dir_rel
    moc_dir.mkdir(parents=True, exist_ok=True)

    index_path = moc_dir / "_index.md"

    fm: dict[str, Any] = {
        "type": "agent-memory-moc",
        "title": "Agent Memory Index",
        "project_count": len(projects),
    }
    frontmatter = (
        "---\n" + yaml.dump(fm, default_flow_style=False, allow_unicode=True) + "---\n"
    )

    lines: list[str] = [
        "# Agent Memory — Project Index",
        "",
        f"*{len(projects)} project(s)*",
        "",
    ]
    for proj in sorted(projects):
        safe = _slugify(proj)
        lines.append(f"- [[{safe}]]")
    lines.append("")

    index_path.write_text(frontmatter + "\n" + "\n".join(lines), encoding="utf-8")
    return index_path


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


def write_vault_notes(
    conn: sqlite3.Connection,
    obsidian_cfg: dict[str, Any],
    vault_path: Path,
    session_ids: list[str] | None = None,
    dry_run: bool = False,
) -> dict[str, int]:
    """Write session-memory notes and MOC index notes to the Obsidian vault.

    This is the top-level orchestrator called from the export pipeline. It reads
    sessions (and their messages) from *conn*, builds the topic index once, and
    writes per-session notes plus per-project MOCs according to the *granularity*
    setting in *obsidian_cfg*.

    Granularity semantics:
    - ``"both"`` — write per-session notes **and** MOC index notes.
    - ``"session"`` — write per-session notes only (no MOCs).
    - Any other value defaults to ``"both"``.

    Guards: if *vault_path* is missing or not a directory, a clear warning is
    printed and zero-counts are returned without raising.

    Args:
        conn: Open ``sqlite3.Connection`` with ``row_factory = sqlite3.Row``.
        obsidian_cfg: Obsidian sub-config dict (from :func:`get_obsidian_config`).
        vault_path: Absolute path to the Obsidian vault root.
        session_ids: Optional list of session IDs to export. When ``None``, all
            sessions in the database are exported.
        dry_run: When ``True``, count what would be written/skipped but do not
            write any files.

    Returns:
        Dict with keys ``written``, ``skipped``, ``mocs``.
    """
    result: dict[str, int] = {"written": 0, "skipped": 0, "mocs": 0}

    if not vault_path.exists() or not vault_path.is_dir():
        print(
            f"Warning: Obsidian vault path not found or not a directory: {vault_path} "
            "— skipping Obsidian export."
        )
        return result

    granularity = obsidian_cfg.get("granularity", "both")
    write_mocs = granularity != "session"
    do_backlinks = obsidian_cfg.get("backlinks", True)

    # Build topic index once (expensive scan; cached in caller if needed)
    topic_index: dict[str, str] | None = None
    if do_backlinks:
        topic_index = build_topic_index(vault_path)

    # Fetch sessions
    if session_ids is not None:
        placeholders = ",".join("?" * len(session_ids))
        rows = conn.execute(
            f"SELECT * FROM sessions WHERE id IN ({placeholders})",
            session_ids,
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM sessions").fetchall()

    # Group note_ids per project for MOC generation
    project_note_ids: dict[str, list[str]] = {}

    for row in rows:
        session = dict(row)
        session_id = session.get("id") or ""

        # Fetch messages for this session
        messages_rows = conn.execute(
            "SELECT * FROM messages WHERE session_id = ? ORDER BY id ASC",
            (session_id,),
        ).fetchall()
        messages = [dict(m) for m in messages_rows]

        if dry_run:
            # In dry_run mode, check idempotency without writing
            memory_dir_rel = obsidian_cfg.get("memory_dir", "AgentMemory")
            memory_dir = vault_path / memory_dir_rel
            raw_date = session.get("created_at") or session.get("updated_at") or ""
            date_str = str(raw_date)[:10] if raw_date else "1970-01-01"
            source = session.get("source") or "unknown"
            project_path = session.get("project_path") or ""
            slug = _make_slug(project_path, session_id)
            note_id = _make_filename(date_str, source, slug)
            target_path = memory_dir / f"{note_id}.md"

            related_links: list[str] = []
            if topic_index and do_backlinks:
                project_name = Path(project_path).name if project_path else ""
                candidates = [t for t in [project_name, source] if t]
                related_links = inject_backlinks(candidates, topic_index)

            body = _build_body(session, messages, date_str, related_links)
            hash_val = _content_hash(body)

            if target_path.exists():
                existing_hash = _parse_existing_hash(target_path)
                if existing_hash == hash_val:
                    result["skipped"] += 1
                    continue
            result["written"] += 1

            # Track for MOC
            project_name_for_moc = (
                Path(session.get("project_path") or "").name or "unknown"
            )
            project_note_ids.setdefault(project_name_for_moc, []).append(note_id)
        else:
            written_path = write_session_to_vault(
                session,
                messages,
                vault_path,
                obsidian_cfg=obsidian_cfg,
                topic_index=topic_index,
            )
            if written_path is None:
                result["skipped"] += 1
                # Still need the note_id for MOC tracking
                raw_date = session.get("created_at") or session.get("updated_at") or ""
                date_str = str(raw_date)[:10] if raw_date else "1970-01-01"
                source = session.get("source") or "unknown"
                note_id = _make_filename(
                    date_str,
                    source,
                    _make_slug(session.get("project_path") or "", session_id),
                )
            else:
                result["written"] += 1
                note_id = written_path.stem

            project_name_for_moc = (
                Path(session.get("project_path") or "").name or "unknown"
            )
            project_note_ids.setdefault(project_name_for_moc, []).append(note_id)

    # Write MOC notes per project
    if write_mocs and not dry_run:
        for project_name, ids in project_note_ids.items():
            write_moc(vault_path, obsidian_cfg, project_name, ids)
            result["mocs"] += 1

        if project_note_ids:
            _write_vault_index(vault_path, obsidian_cfg, list(project_note_ids.keys()))
    elif write_mocs and dry_run:
        result["mocs"] = len(project_note_ids)

    return result
