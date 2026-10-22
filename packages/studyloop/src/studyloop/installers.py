"""Install helpers for studyloop tools, agents, and config bootstrap."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from studyloop.harnesses import RELEASE_HARNESSES
from studyloop.settings import generate_default_config, get_config_path, load_settings

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence


class InstallError(RuntimeError):
    """Raised when an install action cannot be completed."""


@dataclass(frozen=True, slots=True)
class LinkSpec:
    """One symlink to create: ``target`` -> ``source``.

    ``source`` is normally a repository-relative path. It may instead be an
    absolute path or one starting with ``~``, which means "link to this location on
    disk, wherever it came from". That form exists for the skills hub: a skill is
    installed once into ``~/.agents/skills/`` and each harness's own skills
    directory then links to THAT, not back to the repository.

    Two links in a chain rather than several in parallel, because the alternative
    drifts. With parallel links, adding a harness means another repo-relative row,
    and harnesses that already read ``~/.agents/skills`` (Codex, OpenCode, pi)
    would get redundant paths. With a hub, those three are served directly and
    only Kiro/Claude need native-directory links.

    ``copy=True`` installs a COPY of ``source`` at ``target`` instead of a link.
    For a file the harness itself rewrites that is the only safe shape: kiro-cli
    migrates an agent file it loads (the legacy ``hooks`` object to the array
    form, ``toolsSettings`` denylist regexes to ``permissions.rules`` globs) and
    writes the result back to the path it read -- through a link, into the
    repository. On 2026-10-12 that left ``agents/kiro/studyloop.json`` and
    ``study-plan-architect.json`` rewritten in one second, seven manifest tests
    red, and a bare ``*`` (every shell command denied) in the migrated denylist
    where ``curl .* \\| bash`` had been. A copy keeps the rewrite where it
    belongs, on the learner's machine; re-running the installer refreshes it.
    """

    source: str
    target: str
    copy: bool = False


_HOME = Path.home()

_TOOL_LINKS: dict[str, tuple[LinkSpec, ...]] = {
    "kiro": (
        # The three agent FILES are copies (LinkSpec.copy): kiro-cli rewrites the
        # agent file it loads, and through a link that rewrite reached the
        # repository (2026-10-12). The directories beside them stay links --
        # kiro-cli reads those, it does not write them.
        LinkSpec(
            "agents/kiro/study-mentor.json",
            str(_HOME / ".kiro/agents/study-mentor.json"),
            copy=True,
        ),
        # StudyLoop's own persona-neutral agent, named on every Kiro ACP launch
        # (`kiro-cli acp --agent studyloop`) so the learner's default agent never
        # configures a StudyLoop session (owner steer, 2026-09-26).
        LinkSpec(
            "agents/kiro/studyloop.json", str(_HOME / ".kiro/agents/studyloop.json"), copy=True
        ),
        # study-plan-architect.json declares `file://shared/*.md` resources, which
        # Kiro resolves relative to the agent file's directory; this link is what
        # makes them exist there (council phase 2, L7 reviewer).
        LinkSpec("agents/shared", str(_HOME / ".kiro/agents/shared")),
        LinkSpec("agents/kiro/study-mentor", str(_HOME / ".kiro/agents/study-mentor")),
        LinkSpec(
            "agents/kiro/study-plan-architect.json",
            str(_HOME / ".kiro/agents/study-plan-architect.json"),
            copy=True,
        ),
        LinkSpec(
            "agents/kiro/study-plan-architect",
            str(_HOME / ".kiro/agents/study-plan-architect"),
        ),
        LinkSpec("agents/kiro/skills/study-mentor", str(_HOME / ".kiro/skills/study-mentor")),
        LinkSpec(
            "agents/kiro/skills/audhd-socratic-mentor",
            str(_HOME / ".kiro/skills/audhd-socratic-mentor"),
        ),
        LinkSpec(
            "agents/kiro/skills/tutor-progress-tracker",
            str(_HOME / ".kiro/skills/tutor-progress-tracker"),
        ),
        LinkSpec("agents/kiro/skills/study-speak", str(_HOME / ".kiro/skills/study-speak")),
        LinkSpec(
            "agents/mcp/study-speak-server.py",
            str(_HOME / ".kiro/agents/mcp/study-speak-server.py"),
        ),
    ),
    "claude": (
        LinkSpec(
            "agents/claude/socratic-mentor.md",
            str(_HOME / ".claude/agents/socratic-mentor.md"),
        ),
        LinkSpec(
            "agents/claude/study-plan-architect.md",
            str(_HOME / ".claude/agents/study-plan-architect.md"),
        ),
    ),
    "opencode": (
        LinkSpec(
            "agents/opencode/study-mentor.md",
            str(_HOME / ".config/opencode/agents/study-mentor.md"),
        ),
        LinkSpec(
            "agents/opencode/study-plan-architect.md",
            str(_HOME / ".config/opencode/agents/study-plan-architect.md"),
        ),
        LinkSpec(
            "agents/opencode/plugins/studyloop-session-export.js",
            str(_HOME / ".config/opencode/plugins/studyloop-session-export.js"),
        ),
    ),
    # Codex and Grok Build get no persona link. Both read AGENTS.md from the
    # session directory the launcher writes it into (adapters/codex.py,
    # adapters/grok.py); the repo-root AGENTS.md is the contributor file, and
    # an installer must never create or unlink a git-tracked path (council
    # pass 3, D1). install_agent_definitions still wires their hooks, mandates
    # and MCP servers.
    "codex": (),
    "grok": (),
    "pi": (
        LinkSpec("agents/pi/AGENTS.md", str(_HOME / ".pi/agent/AGENTS.md")),
        LinkSpec(
            "agents/pi/extensions/studyloop-session-export.ts",
            str(_HOME / ".pi/agent/extensions/studyloop-session-export.ts"),
        ),
    ),
}

#: The canonical location of the xTiles wind-down skill, and the name every
#: harness link points at. Not a StudyLoop invention: Codex reads
#: ``~/.agents/skills`` as its USER scope and OpenCode lists it as a global search
#: path, so the hub is a directory those two already look in.
XTILES_SKILL_NAME = "studyloop-xtiles-wind-down"
XTILES_SKILL_HUB = _HOME / ".agents/skills" / XTILES_SKILL_NAME
SESSION_MEMORY_SKILL_NAME = "studyloop-session-memory"
SESSION_MEMORY_SKILL_HUB = _HOME / ".agents/skills" / SESSION_MEMORY_SKILL_NAME

_SHARED_LINKS: tuple[LinkSpec, ...] = (
    LinkSpec("agents/shared", str(_HOME / ".agents/shared")),
    # Session memory is a release-harness invariant, not provider-specific.
    # Codex, OpenCode and pi discover ~/.agents/skills directly; Kiro and
    # Claude receive links from their documented native skill directories.
    LinkSpec(
        f"agents/skills/{SESSION_MEMORY_SKILL_NAME}",
        str(SESSION_MEMORY_SKILL_HUB),
    ),
    # The skill itself, installed once. Opt-in and self-gating: inert unless the
    # learner's provider is xtiles AND an `xtiles` MCP server is connected, so
    # installing it unconditionally costs a silent file rather than an unwanted
    # offer (T5 C5 / DECISIONS §F18). Codex needs no further link -- this IS its
    # user-scope skills directory.
    LinkSpec(f"agents/skills/{XTILES_SKILL_NAME}", str(XTILES_SKILL_HUB)),
)

#: Each harness's own skills directory, only where an extra link is needed.
#: Codex, OpenCode, pi and Grok Build are absent because all four officially
#: discover the shared ``~/.agents/skills`` hub directly; duplicate
#: native-directory links would create two discovery paths to the same skill.
#: Grok Build "also scans ``.agents/skills/`` (and ``commands/``) at each tier"
#: alongside its own ``.grok/`` roots (Grok CLI 1.0.13 user guide, 08-skills.md).
XTILES_SKILL_LINKS: dict[str, LinkSpec] = {
    "kiro": LinkSpec(str(XTILES_SKILL_HUB), str(_HOME / ".kiro/skills" / XTILES_SKILL_NAME)),
    "claude": LinkSpec(str(XTILES_SKILL_HUB), str(_HOME / ".claude/skills" / XTILES_SKILL_NAME)),
}

SESSION_MEMORY_SKILL_LINKS: dict[str, LinkSpec] = {
    "kiro": LinkSpec(
        str(SESSION_MEMORY_SKILL_HUB),
        str(_HOME / ".kiro/skills" / SESSION_MEMORY_SKILL_NAME),
    ),
    "claude": LinkSpec(
        str(SESSION_MEMORY_SKILL_HUB),
        str(_HOME / ".claude/skills" / SESSION_MEMORY_SKILL_NAME),
    ),
}

_AGENT_CHOICES = RELEASE_HARNESSES

# ---------------------------------------------------------------------------
# Cross-harness session-memory wiring
# ---------------------------------------------------------------------------
#
# The session DB is the single source of truth for cross-harness struggle
# tracking. Every release harness gets the canonical query skill plus a native
# automatic export hook. Steering mandates remain belt-and-braces reminders;
# Codex carries that reminder directly in its installed AGENTS.md.


def _grok_home() -> Path:
    """Grok Build's home: ``$GROK_HOME`` when set, else ``~/.grok``.

    The same rule the GrokExporter applies when it reads sessions, so the
    hook and rules StudyLoop writes land where the Grok that produced those
    sessions actually looks (Grok CLI user guide, 12-project-rules.md:
    "``$GROK_HOME/rules/`` (default ``~/.grok/rules/``) — always scanned").
    """
    override = os.environ.get("GROK_HOME")
    return Path(override) if override else _HOME / ".grok"


@dataclass(frozen=True, slots=True)
class _HarnessExport:
    """Where a harness's steering file lives + the session-export flag to use."""

    steering_path: Path
    export_flag: str  # the `session-export --<flag>` argument


_HARNESS_EXPORT: dict[str, _HarnessExport] = {
    "claude": _HarnessExport(_HOME / ".claude/rules/session-db.md", "claude-only"),
    "kiro": _HarnessExport(_HOME / ".kiro/steering/session-db.md", "kiro-only"),
    "opencode": _HarnessExport(_HOME / ".config/opencode/session-db.md", "opencode-only"),
    "pi": _HarnessExport(_HOME / ".pi/agent/session-db.md", "pi-only"),
    # Grok scans every *.md under $GROK_HOME/rules/ for all projects, which is
    # the global-steering slot the other four use. The per-session AGENTS.md the
    # launcher writes names the Codex flag, so this file is what carries grok's own.
    "grok": _HarnessExport(_grok_home() / "rules/session-db.md", "grok-only"),
}

# Sentinel marking a steering file as carrying the export mandate (idempotency
# + the doctor harness check both key on this).
_MANDATE_SENTINEL = "studyloop:session-export-mandate"
# Sentinel inside the Claude Stop hook command (idempotent merge + doctor check).
_HOOK_SENTINEL = "session-export --claude-only"

#: Where every export hook appends its output and a dated line on failure.
EXPORT_HOOK_LOG = "$HOME/.config/studyloop/export-hook.log"
#: The exporter every hook calls when uv's tool bin dir is the default
#: (``~/.local/bin``): the ``$HOME`` form survives a home directory that moves.
PINNED_EXPORTER = "$HOME/.local/bin/session-export"


def _uv_tool_bin_dir_from_uv() -> Path | None:
    """``uv tool dir --bin`` -- the directory uv installs tool executables into."""
    try:
        done = subprocess.run(
            ["uv", "tool", "dir", "--bin"],
            capture_output=True,
            text=True,
            check=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    out = done.stdout.strip()
    return Path(out) if out else None


def uv_tool_bin_dir() -> Path | None:
    """Where uv puts tool executables: ``UV_TOOL_BIN_DIR`` when set, else what uv reports."""
    override = os.environ.get("UV_TOOL_BIN_DIR")
    if override:
        return Path(override).expanduser()
    return _uv_tool_bin_dir_from_uv()


def pinned_exporter() -> str:
    """The exporter path every hook embeds.

    ``$HOME/.local/bin/session-export`` when uv's tool bin dir is the default,
    else the absolute directory uv actually installs into. Found on 2026-09-14
    by the first run of scripts/smoke-uv-tool-install.sh inside
    ``just release-check``: with ``UV_TOOL_BIN_DIR`` set, the hooks and doctor's
    ``exporter_schema`` still named a path that did not exist.
    """
    bin_dir = uv_tool_bin_dir()
    # Compare against the REAL home: the `$HOME` in PINNED_EXPORTER is expanded by
    # the shell at hook time, so uv's default (`~/.local/bin`) is the portable case
    # regardless of any test-time redirection of ``_HOME``.
    default = Path.home() / ".local/bin"
    if bin_dir is None or bin_dir.expanduser().resolve() == default.resolve():
        return PINNED_EXPORTER
    return str(bin_dir.expanduser() / "session-export")


def export_hook_command(flag: str) -> str:
    """The one shell line every SessionEnd/Stop hook runs.

    Pinned path, not ``session-export`` from ``PATH``: a shell whose PATH puts a
    development checkout first would otherwise run unpinned code against the
    learner's database (that is how the live database reached schema 48 on
    2026-09-11, see the Stage 4 record). Never silent: stdout and stderr go to
    :data:`EXPORT_HOOK_LOG` and a failure leaves a dated line with the exit
    status -- while the hook itself still exits 0, so a broken exporter can
    never block a session from closing.
    """
    return (
        f"{pinned_exporter()} {flag} >>{EXPORT_HOOK_LOG} 2>&1 || "
        f'{{ rc=$?; echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) session-export {flag} FAILED exit=$rc" '
        f">>{EXPORT_HOOK_LOG}; }}"
    )


def hook_command_is_canonical(command: str, flag: str) -> bool:
    """True when a hook already runs :func:`export_hook_command` for ``flag``."""
    return command.strip() == export_hook_command(flag)


_SESSION_HOOK_SENTINEL = "studyloop:session-export-hook"
_CODEX_HOOK_SENTINEL = "session-export --codex-only"
_GROK_HOOK_SENTINEL = "session-export --grok-only"

_MCP_SERVERS: dict[str, dict[str, object]] = {
    "session-db": {"command": "session-db-mcp", "args": []},
    "studyloop": {"command": "studyloop-mcp", "args": []},
}
#: Every harness the installer registers both StudyLoop MCP servers into
#: globally. pi is deliberately absent -- its README states "No MCP" by
#: design (build CLI tools with skills, or an extension), so pi stays
#: CLI-fallback-only (session-query / session-context / mastery graph).
_MCP_HARNESSES = ("claude", "kiro", "codex", "opencode", "grok")


def _mcp_config_path(tool: str) -> Path:
    """The config file a harness's MCP registration lives in.

    Grok Build is deliberately absent: it has no repo-owned config file to
    merge bytes into -- registration goes through its own CLI
    (:func:`register_grok_mcp_servers`) instead.
    """
    paths = {
        "claude": _HOME / ".claude.json",
        "kiro": _HOME / ".kiro/settings/mcp.json",
        "codex": _HOME / ".codex/config.toml",
        "opencode": _HOME / ".config/opencode/opencode.json",
    }
    try:
        return paths[tool]
    except KeyError as exc:
        raise InstallError(f"Unsupported MCP registration target: {tool}") from exc


def _json_root_object_span(raw: str) -> tuple[int, int] | None:
    """Return the root JSON object span without reserializing its bytes."""
    import json

    start = 0
    while start < len(raw) and raw[start].isspace():
        start += 1
    try:
        value, end = json.JSONDecoder().raw_decode(raw, start)
    except json.JSONDecodeError:
        return None
    return (start, end) if isinstance(value, dict) else None


def _json_member_spans(
    raw: str, object_span: tuple[int, int]
) -> list[tuple[str, int, int, int]] | None:
    """Every member of one JSON object as ``(name, key_start, value_start, value_end)``.

    Offsets index ``raw``. ``None`` when the object text cannot be walked, so a
    caller never edits bytes it did not understand.
    """
    import json

    start, end = object_span
    decoder = json.JSONDecoder()
    members: list[tuple[str, int, int, int]] = []
    cursor = start + 1
    while cursor < end - 1:
        while cursor < end - 1 and (raw[cursor].isspace() or raw[cursor] == ","):
            cursor += 1
        if cursor >= end - 1:
            break
        key_start = cursor
        try:
            member_name, key_end = decoder.raw_decode(raw, cursor)
        except json.JSONDecodeError:
            return None
        if not isinstance(member_name, str):
            return None
        cursor = key_end
        while cursor < end - 1 and raw[cursor].isspace():
            cursor += 1
        if cursor >= end - 1 or raw[cursor] != ":":
            return None
        cursor += 1
        while cursor < end - 1 and raw[cursor].isspace():
            cursor += 1
        value_start = cursor
        try:
            _, value_end = decoder.raw_decode(raw, value_start)
        except json.JSONDecodeError:
            return None
        members.append((member_name, key_start, value_start, value_end))
        cursor = value_end
    return members


def _json_value_span(
    raw: str, key: str, object_span: tuple[int, int] | None = None
) -> tuple[int, int] | None:
    """Return an arbitrary JSON member value span from one object."""
    span = object_span or _json_root_object_span(raw)
    if span is None:
        return None
    members = _json_member_spans(raw, span)
    if members is None:
        return None
    for name, _key_start, value_start, value_end in members:
        if name == key:
            return value_start, value_end
    return None


def _json_object_span(raw: str, key: str) -> tuple[int, int] | None:
    """Return an object-valued top-level member span for ``key``."""
    span = _json_value_span(raw, key)
    if span is None or raw[span[0]] != "{":
        return None
    return span


def _json_array_element_spans(raw: str, span: tuple[int, int]) -> list[tuple[int, int]] | None:
    """Every element of one JSON array as ``(start, end)`` offsets into ``raw``.

    The array analogue of :func:`_json_member_spans`; ``None`` when the text
    cannot be walked.
    """
    start, end = span
    if raw[start] != "[":
        return None
    decoder = json.JSONDecoder()
    elements: list[tuple[int, int]] = []
    cursor = start + 1
    while cursor < end - 1:
        while cursor < end - 1 and (raw[cursor].isspace() or raw[cursor] == ","):
            cursor += 1
        if cursor >= end - 1:
            break
        try:
            _, value_end = decoder.raw_decode(raw, cursor)
        except json.JSONDecodeError:
            return None
        elements.append((cursor, value_end))
        cursor = value_end
    return elements


def _json_children(raw: str, span: tuple[int, int]) -> list[tuple[int, int]] | None:
    """``(start, end)`` of each child of one container, in document order.

    A member runs from its key to the end of its value; an element is the
    element. This is the unit a byte-preserving cut removes.
    """
    if raw[span[0]] == "{":
        members = _json_member_spans(raw, span)
        return None if members is None else [(key_start, end) for _, key_start, _, end in members]
    if raw[span[0]] == "[":
        return _json_array_element_spans(raw, span)
    return None


def _json_path_span(raw: str, path: Sequence[str | int]) -> tuple[int, int] | None:
    """The value span at ``path`` from the root object.

    A ``str`` step names an object member, an ``int`` step indexes an array.
    ``None`` when any step is missing or the text cannot be walked -- the
    caller then refuses the edit rather than guessing.
    """
    span = _json_root_object_span(raw)
    for step in path:
        if span is None:
            return None
        if isinstance(step, str):
            span = _json_value_span(raw, step, span) if raw[span[0]] == "{" else None
        else:
            elements = _json_array_element_spans(raw, span) if raw[span[0]] == "[" else None
            span = elements[step] if elements is not None and 0 <= step < len(elements) else None
    return span


def _json_cut_child(raw: str, parent: Sequence[str | int], child: str | int) -> str | None:
    """Remove one member (``str``) or element (``int``) from the container at ``parent``.

    The child is cut together with the separator that joined it to its
    neighbour, so every other byte stays: the shape :func:`_remove_json_members`
    established, generalised to any depth and to arrays. ``None`` when the
    text cannot be walked or the child is not there.
    """
    container = _json_path_span(raw, parent)
    if container is None:
        return None
    children = _json_children(raw, container)
    if children is None:
        return None
    if isinstance(child, str):
        members = _json_member_spans(raw, container) or []
        index = next((i for i, member in enumerate(members) if member[0] == child), None)
    else:
        index = child if 0 <= child < len(children) else None
    if index is None:
        return None
    child_start, child_end = children[index]
    if len(children) == 1:
        return raw[: container[0] + 1] + raw[container[1] - 1 :]
    if index > 0:
        return raw[: children[index - 1][1]] + raw[child_end:]
    return raw[:child_start] + raw[children[1][0] :]


def _append_json_children(
    raw: str, span: tuple[int, int], items: Sequence[tuple[str | None, object]]
) -> str:
    """Append members (``(name, value)``) or elements (``(None, value)``) to one container.

    Every existing byte stays, including the whitespace before the closing
    bracket, so a later cut of what was appended returns the text exactly.
    New items follow the container's own layout: one-line containers get
    ``, `` separators; multi-line ones get a new line per item indented like
    the last existing child, with nested lines stepped by the file's own
    indentation; an empty container is opened like ``json.dumps`` would,
    relative to the line it starts on.
    """
    start, end = span
    close = end - 1
    newline = "\r\n" if "\r\n" in raw else "\n"
    children = _json_children(raw, span) or []

    def render(name: str | None, value: object, indent: str, unit: str) -> str:
        text = json.dumps(value, indent=unit).replace("\n", newline + indent)
        return text if name is None else f"{json.dumps(name)}: {text}"

    if children:
        last_start, last_end = children[-1]
        line_start = raw.rfind("\n", 0, last_start) + 1
        indent = raw[line_start:last_start]
        if indent and not indent.isspace():
            # The last child shares its line with the opening bracket or an
            # earlier child: a one-line container.
            rendered = ", ".join(
                f"{json.dumps(n)}: {json.dumps(v)}" if n is not None else json.dumps(v)
                for n, v in items
            )
            return raw[:last_end] + ", " + rendered + raw[last_end:]
        # The file's own indentation unit (spaces or tabs): what the last
        # child has beyond the closing bracket's own indentation.
        close_line_start = raw.rfind("\n", 0, close) + 1
        closing_indent = raw[close_line_start:close]
        if closing_indent and not closing_indent.isspace():
            closing_indent = ""
        unit = indent[len(closing_indent) :] if indent.startswith(closing_indent) else ""
        rendered = ("," + newline).join(
            indent + render(n, v, indent, unit or "  ") for n, v in items
        )
        return raw[:last_end] + "," + newline + rendered + raw[last_end:]

    line_start = raw.rfind("\n", 0, start) + 1
    base = raw[line_start:start]
    base_indent = base[: len(base) - len(base.lstrip())]
    indent = base_indent + "  "
    rendered = ("," + newline).join(indent + render(n, v, indent, "  ") for n, v in items)
    return raw[: start + 1] + newline + rendered + newline + base_indent + raw[close:]


def _append_json_members(
    raw: str,
    span: tuple[int, int],
    members: Mapping[str, object],
) -> str:
    """Append object members while retaining every existing member byte."""
    return _append_json_children(raw, span, list(members.items()))


def _append_json_elements(raw: str, span: tuple[int, int], values: Sequence[object]) -> str:
    """Append array elements while retaining every existing byte."""
    return _append_json_children(raw, span, [(None, value) for value in values])


def _merge_json_mcp_config(
    path: Path,
    *,
    container_key: str = "mcpServers",
    servers: Mapping[str, dict[str, object]] | None = None,
) -> int:
    """Byte-preserving merge of ``servers`` into ``path``'s ``container_key`` object.

    Generalised over the container key and server payload so OpenCode's
    ``mcp`` container (:func:`_merge_opencode_mcp_config`) reuses the same
    span-based merge as Claude/Kiro's ``mcpServers`` container -- one owned-key
    repair algorithm, not two copies that could drift (council grok F8).
    """
    import json

    owned = dict(servers) if servers is not None else _MCP_SERVERS

    try:
        raw = path.read_bytes().decode("utf-8")
    except FileNotFoundError:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({container_key: owned}, indent=2) + "\n",
            encoding="utf-8",
        )
        return 1
    except (OSError, UnicodeDecodeError) as exc:
        raise InstallError(f"Cannot read MCP config {path}: {exc}") from exc
    try:
        loaded = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise InstallError(f"Cannot merge MCP servers into malformed {path}: {exc}") from exc
    if not isinstance(loaded, dict):
        raise InstallError(f"Cannot merge MCP servers: {path} is not a JSON object")

    root_span = _json_root_object_span(raw)
    if root_span is None:
        raise InstallError(f"Cannot locate root object in MCP config {path}")
    current = loaded.get(container_key)
    if isinstance(current, dict) and all(
        current.get(name) == value for name, value in owned.items()
    ):
        return 0

    if container_key not in loaded:
        updated = _append_json_members(raw, root_span, {container_key: owned})
    elif not isinstance(current, dict):
        container_span = _json_value_span(raw, container_key, root_span)
        if container_span is None:
            raise InstallError(f"Cannot locate {container_key} value in {path}")
        rendered = json.dumps(owned, separators=(", ", ": "))
        updated = raw[: container_span[0]] + rendered + raw[container_span[1] :]
    else:
        mcp_span = _json_object_span(raw, container_key)
        if mcp_span is None:
            raise InstallError(f"Cannot locate {container_key} object in {path}")
        incorrect = {name: value for name, value in owned.items() if current.get(name) != value}
        updated = raw
        for name in sorted(set(incorrect) & set(current)):
            mcp_span = _json_object_span(updated, container_key)
            if mcp_span is None:
                raise InstallError(f"Cannot locate {container_key} object in {path}")
            nested = updated[mcp_span[0] : mcp_span[1]]
            value_span = _json_value_span(nested, name)
            if value_span is None:
                raise InstallError(f"Cannot locate owned MCP server {name} in {path}")
            value_start = mcp_span[0] + value_span[0]
            value_end = mcp_span[0] + value_span[1]
            rendered = json.dumps(owned[name], separators=(", ", ": "))
            updated = updated[:value_start] + rendered + updated[value_end:]
        absent = {name: value for name, value in incorrect.items() if name not in current}
        if absent:
            mcp_span = _json_object_span(updated, container_key)
            if mcp_span is None:
                raise InstallError(f"Cannot locate {container_key} object in {path}")
            updated = _append_json_members(updated, mcp_span, absent)
    path.write_bytes(updated.encode("utf-8"))
    return 1


def _mcp_server_args(config: dict[str, object]) -> list[object]:
    """The ``args`` list of one ``_MCP_SERVERS`` entry, typed for iteration.

    ``_MCP_SERVERS`` is typed ``dict[str, dict[str, object]]`` so both the
    ``command`` string and the ``args`` list share one value type; this
    narrows ``args`` back to a list pyright (and callers that splat it) can
    iterate.
    """
    args = config["args"]
    return list(args) if isinstance(args, list) else []


def _opencode_mcp_servers() -> dict[str, dict[str, object]]:
    """The two StudyLoop servers rendered in OpenCode's own MCP schema.

    Same ``_MCP_SERVERS`` names (``session-db``, ``studyloop``) as every other
    globally-registered harness -- only the value shape differs: a flat
    ``command`` array plus ``enabled``/``type: local`` (council grok F9:
    ``studyloop-mcp``/``session-db-mcp`` are console-script COMMANDS, never
    server names).
    """
    return {
        name: {
            "command": [config["command"], *_mcp_server_args(config)],
            "enabled": True,
            "type": "local",
        }
        for name, config in _MCP_SERVERS.items()
    }


def _merge_opencode_mcp_config(path: Path) -> int:
    """Merge both StudyLoop servers into OpenCode's global ``mcp`` container."""
    return _merge_json_mcp_config(path, container_key="mcp", servers=_opencode_mcp_servers())


def _remove_json_members(raw: str, container_key: str, names: set[str]) -> str:
    """Delete ``names`` from the top-level ``container_key`` object, byte-preserving.

    The inverse of :func:`_append_json_members`: a member is cut together with
    the separator that joined it to its neighbour, so every other member keeps
    its exact bytes and an install-then-uninstall round trip returns the text
    install started from. One member per pass, re-walking the text each time.
    """
    while True:
        container = _json_object_span(raw, container_key)
        if container is None:
            return raw
        members = _json_member_spans(raw, container)
        if members is None:
            return raw
        index = next((i for i, member in enumerate(members) if member[0] in names), None)
        if index is None:
            return raw
        _, key_start, _, value_end = members[index]
        if len(members) == 1:
            raw = raw[: container[0] + 1] + raw[container[1] - 1 :]
        elif index > 0:
            raw = raw[: members[index - 1][3]] + raw[value_end:]
        else:
            raw = raw[:key_start] + raw[members[1][1] :]


def _remove_json_mcp_entries(path: Path, container_key: str, names: set[str]) -> int:
    """Remove ``names`` from ``path``'s ``container_key`` object, if present.

    Byte-preserving, like the merge: these files belong to the harness and the
    learner (``~/.claude.json`` carries Claude Code's whole state), so every
    member StudyLoop does not own keeps its exact bytes -- a reserialising
    writer would reflow them and escape every non-ASCII character. The edited
    text is parsed back and must equal the original minus ``names`` before it
    is written; when it does not, nothing is written and :class:`InstallError`
    names the file. Returns the number of names removed; 0 for a missing,
    malformed, or already-clean file.
    """
    import copy
    import json

    try:
        raw = path.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return 0
    try:
        loaded = json.loads(raw)
    except json.JSONDecodeError:
        return 0
    if not isinstance(loaded, dict):
        return 0
    container = loaded.get(container_key)
    if not isinstance(container, dict):
        return 0
    present = names & set(container)
    if not present:
        return 0
    expected = copy.deepcopy(loaded)
    for name in present:
        del expected[container_key][name]
    updated = _remove_json_members(raw, container_key, present)
    try:
        edited_ok = json.loads(updated) == expected
    except json.JSONDecodeError:
        edited_ok = False
    if not edited_ok:
        raise InstallError(f"Cannot remove StudyLoop MCP servers from {path} without rewriting it")
    path.write_bytes(updated.encode("utf-8"))
    return len(present)


def _remove_codex_mcp_config(path: Path) -> int:
    """Remove both StudyLoop servers from Codex's ``config.toml``, byte-preserving.

    Uses the same owned-table remover the merge repairs entries with, then
    drops the blank-line separators the merge appended before each block, so a
    config install appended to ends exactly as it began. The edit is checked
    the same way as :func:`_remove_json_mcp_entries`. Returns the number of
    servers removed; 0 for a missing, malformed or already-clean file.
    """
    import tomllib

    try:
        raw = path.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return 0
    try:
        loaded = tomllib.loads(raw)
    except tomllib.TOMLDecodeError:
        return 0
    current = loaded.get("mcp_servers")
    if not isinstance(current, dict):
        return 0
    present = set(_MCP_SERVERS) & set(current)
    if not present:
        return 0
    updated = _remove_owned_toml(raw, present)
    newline = "\r\n" if "\r\n" in raw else "\n"
    updated = updated.rstrip("\r\n") + newline if updated.strip() else ""

    def without_owned(data: dict[str, object]) -> dict[str, object]:
        servers = data.get("mcp_servers")
        rest = {key: value for key, value in data.items() if key != "mcp_servers"}
        if isinstance(servers, dict):
            kept = {name: value for name, value in servers.items() if name not in present}
            if kept:
                rest["mcp_servers"] = kept
        return rest

    try:
        edited_ok = without_owned(tomllib.loads(updated)) == without_owned(loaded)
    except tomllib.TOMLDecodeError:
        edited_ok = False
    if not edited_ok:
        raise InstallError(f"Cannot remove StudyLoop MCP servers from {path} without rewriting it")
    path.write_bytes(updated.encode("utf-8"))
    return len(present)


def _toml_marker_path(value: object, path: tuple[str, ...] = ()) -> tuple[str, ...] | None:
    """Return the parsed TOML key path containing the private marker."""
    if not isinstance(value, dict):
        return None
    marker = "__studyloop_owned_marker__"
    if marker in value:
        return path
    for key, nested in value.items():
        found = _toml_marker_path(nested, (*path, key))
        if found is not None:
            return found
    return None


def _toml_table_path(line: str) -> tuple[str, ...] | None:
    """Parse one TOML table header into semantic key components."""
    import tomllib

    candidate = line.rstrip("\r\n")
    if not candidate.lstrip().startswith("[") or candidate.lstrip().startswith("[["):
        return None
    try:
        parsed = tomllib.loads(candidate + "\n__studyloop_owned_marker__ = true\n")
    except tomllib.TOMLDecodeError:
        return None
    return _toml_marker_path(parsed)


def _toml_assignment_path(line: str) -> tuple[str, ...] | None:
    """Parse the dotted key path at the start of one TOML assignment."""
    import tomllib

    stripped = line.lstrip()
    if not stripped or stripped.startswith("#"):
        return None
    quote: str | None = None
    escaped = False
    for index, char in enumerate(stripped):
        if quote is not None:
            if quote == '"' and char == "\\" and not escaped:
                escaped = True
                continue
            if char == quote and not escaped:
                quote = None
            escaped = False
            continue
        if char in {'"', "'"}:
            quote = char
        elif char == "=":
            key = stripped[:index].strip()
            if not key:
                return None
            try:
                parsed = tomllib.loads(f"{key} = {{ __studyloop_owned_marker__ = true }}")
            except tomllib.TOMLDecodeError:
                return None
            return _toml_marker_path(parsed)
    return None


def _toml_statement_end(lines: list[str], start: int, stop: int) -> int:
    """Return the first line after a complete TOML assignment."""
    import tomllib

    statement = ""
    for index in range(start, stop):
        statement += lines[index]
        try:
            tomllib.loads(statement)
        except tomllib.TOMLDecodeError:
            continue
        return index + 1
    return start + 1


def _toml_normal_line_indexes(lines: list[str]) -> set[int]:
    """Return physical lines that begin outside TOML strings and comments."""
    normal_lines: set[int] = set()
    state = "normal"

    for line_index, line in enumerate(lines):
        if state == "normal":
            normal_lines.add(line_index)

        index = 0
        while index < len(line):
            char = line[index]

            if state == "comment":
                if char in "\r\n":
                    state = "normal"
                index += 1
                continue

            if state == "basic":
                if char == "\\":
                    index += 2
                elif char == '"' or char in "\r\n":
                    state = "normal"
                    index += 1
                else:
                    index += 1
                continue

            if state == "literal":
                if char == "'" or char in "\r\n":
                    state = "normal"
                index += 1
                continue

            if state in {"multiline-basic", "multiline-literal"}:
                delimiter = '"' if state == "multiline-basic" else "'"
                if state == "multiline-basic" and char == "\\":
                    index += 2
                    continue
                if char == delimiter:
                    run_end = index
                    while run_end < len(line) and line[run_end] == delimiter:
                        run_end += 1
                    if run_end - index >= 3:
                        state = "normal"
                    index = run_end
                    continue
                index += 1
                continue

            if char == "#":
                state = "comment"
                index += 1
            elif line.startswith('"""', index):
                state = "multiline-basic"
                index += 3
            elif char == '"':
                state = "basic"
                index += 1
            elif line.startswith("'''", index):
                state = "multiline-literal"
                index += 3
            elif char == "'":
                state = "literal"
                index += 1
            else:
                index += 1

    return normal_lines


def _remove_owned_toml(raw: str, names: set[str]) -> str:
    """Remove owned MCP table headers and assignments while retaining other bytes."""
    lines = raw.splitlines(keepends=True)
    starts: list[int] = []
    offset = 0
    for line in lines:
        starts.append(offset)
        offset += len(line)

    normal_lines = _toml_normal_line_indexes(lines)
    headers = [
        (index, path)
        for index, line in enumerate(lines)
        if index in normal_lines and (path := _toml_table_path(line)) is not None
    ]
    removals: list[tuple[int, int]] = []

    def owned(path: tuple[str, ...]) -> bool:
        return len(path) >= 2 and path[0] == "mcp_servers" and path[1] in names

    def remove_assignments(table_path: tuple[str, ...], start_line: int, stop_line: int) -> None:
        index = start_line
        remove_every_assignment = owned(table_path)
        while index < stop_line:
            key_path = _toml_assignment_path(lines[index])
            if key_path is None:
                index += 1
                continue
            end_line = _toml_statement_end(lines, index, stop_line)
            semantic_path = (*table_path, *key_path)
            if remove_every_assignment or owned(semantic_path):
                end_offset = starts[end_line] if end_line < len(lines) else len(raw)
                removals.append((starts[index], end_offset))
            index = end_line

    first_header = headers[0][0] if headers else len(lines)
    remove_assignments((), 0, first_header)
    for position, (line_index, table_path) in enumerate(headers):
        next_header = headers[position + 1][0] if position + 1 < len(headers) else len(lines)
        header_end = starts[line_index + 1] if line_index + 1 < len(lines) else len(raw)
        if owned(table_path):
            removals.append((starts[line_index], header_end))
        remove_assignments(table_path, line_index + 1, next_header)

    updated = raw
    for start, end in sorted(removals, reverse=True):
        updated = updated[:start] + updated[end:]
    return updated


def _codex_mcp_block(name: str, newline: str = "\n") -> str:
    config = _MCP_SERVERS[name]
    return (
        f'[mcp_servers.{name}]{newline}command = "{config["command"]}"{newline}args = []{newline}'
    )


def _merge_codex_mcp_config(path: Path) -> int:
    import tomllib

    try:
        raw = path.read_bytes().decode("utf-8")
    except FileNotFoundError:
        raw = ""
    except (OSError, UnicodeDecodeError) as exc:
        raise InstallError(f"Cannot read Codex MCP config {path}: {exc}") from exc
    try:
        loaded = tomllib.loads(raw)
    except tomllib.TOMLDecodeError as exc:
        raise InstallError(f"Cannot merge MCP servers into malformed {path}: {exc}") from exc
    current = loaded.get("mcp_servers", {})
    if not isinstance(current, dict):
        raise InstallError(f"Cannot merge MCP servers: {path} mcp_servers is not a table")
    if all(current.get(name) == value for name, value in _MCP_SERVERS.items()):
        return 0

    incorrect = {name for name, value in _MCP_SERVERS.items() if current.get(name) != value}
    updated = _remove_owned_toml(raw, incorrect)
    newline = "\r\n" if "\r\n" in raw else "\n"
    for name in _MCP_SERVERS:
        if name not in incorrect:
            continue
        if updated and not updated.endswith(("\n", "\r")):
            updated += newline
        if updated and not updated.endswith(newline * 2):
            updated += newline
        updated += _codex_mcp_block(name, newline)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(updated.encode("utf-8"))
    return 1


def _grok_user_settings_path() -> Path:
    """The legacy MCP config some Grok Build installs still carry.

    An older shape (``$GROK_HOME/user-settings.json`` with an ``mcpServers``
    map) that predates the ``grok mcp add`` CLI (council kimi F13).
    StudyLoop never writes this file -- it is read-only detection, so
    registration does not create a duplicate entry under a second name when
    a server is already present here.
    """
    return _grok_home() / "user-settings.json"


def _grok_legacy_registered_names() -> set[str]:
    """StudyLoop server names already present in the legacy user-settings.json."""
    import json

    try:
        data = json.loads(_grok_user_settings_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    servers = data.get("mcpServers") if isinstance(data, dict) else None
    if not isinstance(servers, dict):
        return set()
    return {name for name in _MCP_SERVERS if name in servers}


def _grok_mcp_list(binary: str) -> list[dict[str, object]] | None:
    """Parse ``grok mcp list --json``; ``None`` on any failure, never raises.

    Verified live on grok 1.0.13 (council grok F7): a JSON array of objects
    shaped ``{command, args, enabled, name, scope}``.
    """
    import json

    try:
        result = subprocess.run(
            [binary, "mcp", "list", "--json"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    try:
        parsed = json.loads(result.stdout)
    except (json.JSONDecodeError, TypeError):
        return None
    return parsed if isinstance(parsed, list) else None


def register_grok_mcp_servers() -> int:
    """Register both StudyLoop MCP servers with Grok Build's own CLI.

    Runs ``grok mcp add --scope user --transport stdio <name> <command>`` for
    each server not already present. Returns 0 (never raises) when ``grok``
    is not on PATH -- Grok Build is a preview harness the installer must not
    fail hard for merely being absent -- and skips a name already registered
    under the legacy ``user-settings.json`` map (council kimi F13) so the
    CLI does not create a duplicate entry.
    """
    binary = shutil.which("grok")
    if binary is None:
        return 0
    legacy = _grok_legacy_registered_names()
    changed = 0
    for name, config in _MCP_SERVERS.items():
        if name in legacy:
            continue
        cmd = [
            binary,
            "mcp",
            "add",
            "--scope",
            "user",
            "--transport",
            "stdio",
            name,
            str(config["command"]),
            *(str(arg) for arg in _mcp_server_args(config)),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if result.returncode == 0:
            changed += 1
    return changed


def unregister_grok_mcp_servers() -> int:
    """Remove both StudyLoop MCP servers via ``grok mcp remove <name>``.

    Returns 0 (never raises) when ``grok`` is not on PATH.
    """
    binary = shutil.which("grok")
    if binary is None:
        return 0
    changed = 0
    for name in _MCP_SERVERS:
        result = subprocess.run(
            [binary, "mcp", "remove", name], capture_output=True, text=True, check=False
        )
        if result.returncode == 0:
            changed += 1
    return changed


def _grok_registration_detail() -> tuple[bool, str | None]:
    """Registration state plus which file satisfied it, for doctor messaging.

    A server present in the legacy ``user-settings.json`` map counts as
    registered without running the CLI at all (council kimi F13); the second
    element then names that file. Otherwise falls back to ``grok mcp list
    --json``; when that covers both names the second element names
    ``config.toml`` (the file ``grok mcp add`` writes) instead. Both `grok`
    being absent and the CLI call failing report ``(False, None)`` rather
    than raising.
    """
    legacy = _grok_legacy_registered_names()
    if set(_MCP_SERVERS) <= legacy:
        return True, str(_grok_user_settings_path())
    binary = shutil.which("grok")
    if binary is None:
        return False, None
    entries = _grok_mcp_list(binary)
    if entries is None:
        return False, None
    live = {
        entry.get("name")
        for entry in entries
        if isinstance(entry, dict)
        and entry.get("command") == _MCP_SERVERS.get(str(entry.get("name")), {}).get("command")
    }
    if set(_MCP_SERVERS) <= (legacy | live):
        return True, str(_grok_home() / "config.toml")
    return False, None


def _grok_registration_status() -> bool:
    """True when both StudyLoop MCP servers are registered with Grok Build.

    Thin wrapper over :func:`_grok_registration_detail` for callers that only
    need the bool (e.g. :func:`mcp_registration_status`'s uniform per-tool map).
    """
    return _grok_registration_detail()[0]


def register_mcp_servers(
    tools: list[str] | None = None, *, uninstall: bool = False
) -> dict[str, int]:
    """Register both StudyLoop MCP servers in supported harness configs.

    ``uninstall=True`` removes them instead, through
    :func:`unregister_mcp_servers`: one entry point per installed surface,
    both directions, as :func:`_link_paths` and :func:`_configure_claude` do.
    """
    selected = [
        tool for tool in (tools or detect_available_agent_tools()) if tool in _MCP_HARNESSES
    ]
    if uninstall:
        return unregister_mcp_servers(selected)
    changed: dict[str, int] = {}
    for tool in selected:
        if tool == "codex":
            changed[tool] = _merge_codex_mcp_config(_mcp_config_path(tool))
        elif tool == "opencode":
            changed[tool] = _merge_opencode_mcp_config(_mcp_config_path(tool))
        elif tool == "grok":
            changed[tool] = register_grok_mcp_servers()
        else:
            changed[tool] = _merge_json_mcp_config(_mcp_config_path(tool))
    return changed


def unregister_mcp_servers(tools: list[str]) -> dict[str, int]:
    """Remove StudyLoop's owned MCP entries for the given tools.

    Covers every harness :func:`register_mcp_servers` writes. StudyLoop owns
    the two server NAMES it registers (``session-db``, ``studyloop``) -- the
    merge already claims them by overwriting a same-named entry -- and removes
    only those; every other server and every other byte of the file stays
    (Claude/Kiro/OpenCode JSON and Codex TOML are edited byte-preserving).
    Grok Build goes through its own CLI. Returns per-tool removal counts.
    """
    changed: dict[str, int] = {}
    for tool in tools:
        if tool == "opencode":
            changed[tool] = _remove_json_mcp_entries(
                _mcp_config_path("opencode"), "mcp", set(_MCP_SERVERS)
            )
        elif tool in {"claude", "kiro"}:
            changed[tool] = _remove_json_mcp_entries(
                _mcp_config_path(tool), "mcpServers", set(_MCP_SERVERS)
            )
        elif tool == "codex":
            changed[tool] = _remove_codex_mcp_config(_mcp_config_path("codex"))
        elif tool == "grok":
            changed[tool] = unregister_grok_mcp_servers()
        else:
            raise InstallError(f"MCP unregistration is not supported for tool: {tool}")
    return changed


def xtiles_mcp_harnesses() -> list[str]:
    """Harnesses whose MCP config registers a server named ``xtiles``, sorted.

    Read-only, for the doctor's xTiles row. The wind-down skill offers only in a
    session where an ``xtiles`` MCP server is connected, so where one is
    registered decides where the offer can ever appear. Reads the same files
    :func:`_mcp_config_path` names; Grok Build is not read (its registration goes
    through its own CLI). A missing or unreadable config counts as "not
    registered there", never as an error.
    """
    import json
    import tomllib

    sections = {"claude": "mcpServers", "codex": "mcp_servers", "kiro": "mcpServers"}
    sections["opencode"] = "mcp"
    found: list[str] = []
    for tool, section in sections.items():
        try:
            text = _mcp_config_path(tool).read_text(encoding="utf-8")
            data = tomllib.loads(text) if tool == "codex" else json.loads(text)
        except (OSError, ValueError):
            continue
        servers = data.get(section) if isinstance(data, dict) else None
        if isinstance(servers, dict) and "xtiles" in servers:
            found.append(tool)
    return sorted(found)


def mcp_registration_status(tools: list[str] | None = None) -> dict[str, bool]:
    """Report registration state without modifying any harness configuration."""
    import json
    import tomllib

    selected = list(tools or _MCP_HARNESSES)
    status: dict[str, bool] = {}
    for tool in selected:
        if tool == "grok":
            status[tool] = _grok_registration_status()
            continue
        path = _mcp_config_path(tool)
        try:
            if tool == "codex":
                data = tomllib.loads(path.read_text(encoding="utf-8"))
                current = data.get("mcp_servers", {})
                servers = _MCP_SERVERS
            elif tool == "opencode":
                data = json.loads(path.read_text(encoding="utf-8"))
                current = data.get("mcp", {})
                servers = _opencode_mcp_servers()
            else:
                data = json.loads(path.read_text(encoding="utf-8"))
                current = data.get("mcpServers", {})
                servers = _MCP_SERVERS
            status[tool] = isinstance(current, dict) and all(
                current.get(name) == value for name, value in servers.items()
            )
        except (OSError, ValueError, TypeError):
            status[tool] = False
    return status


def _codex_hooks_path() -> Path:
    return _HOME / ".codex/hooks.json"


def _grok_hooks_path() -> Path:
    # Grok loads every *.json under $GROK_HOME/hooks/ as global hooks, so
    # StudyLoop gets a file of its own rather than a slot in someone else's.
    return _grok_home() / "hooks/studyloop.json"


def _kiro_agent_path() -> Path:
    return _HOME / ".kiro/agents/study-mentor.json"


def _opencode_hook_path() -> Path:
    return _HOME / ".config/opencode/plugins/studyloop-session-export.js"


def _pi_hook_path() -> Path:
    return _HOME / ".pi/agent/extensions/studyloop-session-export.ts"


def _render_mandate(repo_root: Path, export_flag: str) -> str:
    """Load the shared mandate template and substitute the harness flag."""
    template = (repo_root / "agents/shared/session-db-mandate.md").read_text(encoding="utf-8")
    return template.replace("SESSION_EXPORT_FLAG", export_flag)


def _backup_path(path: Path) -> Path:
    """``<name>.bak``, or ``<name>.bak.N`` when that is taken: never clobber a backup."""
    candidate = path.with_name(f"{path.name}.bak")
    counter = 1
    while candidate.exists() or candidate.is_symlink():
        candidate = path.with_name(f"{path.name}.bak.{counter}")
        counter += 1
    return candidate


def install_session_db_mandate(
    repo_root: Path, tools: list[str] | None = None, *, uninstall: bool = False
) -> dict[str, int]:
    """Write the session-export steering mandate into each harness's file.

    Idempotent: a file already containing the sentinel is left untouched.
    A file without it is overwritten with the rendered mandate (these
    session-db.md files are StudyLoop-managed, single-purpose). Returns a
    per-tool count of files written.

    ``uninstall=True`` takes each mandate away: a file that is exactly the
    rendered mandate is deleted; one that carries the sentinel but no longer
    matches (the learner edited it, or an older release wrote it) is moved to
    a ``.bak`` beside it -- harnesses load ``*.md``, so it stops steering while
    its bytes survive. A file without the sentinel is not StudyLoop's and is
    left alone. Returns a per-tool count of files removed.
    """
    selected = tools or detect_available_agent_tools()
    written: dict[str, int] = {}
    for tool in selected:
        spec = _HARNESS_EXPORT.get(tool)
        if spec is None:
            continue
        if uninstall:
            try:
                current = spec.steering_path.read_text(encoding="utf-8")
            except FileNotFoundError:
                written[tool] = 0
                continue
            if _MANDATE_SENTINEL not in current:
                written[tool] = 0
                continue
            if current == _render_mandate(repo_root, spec.export_flag):
                spec.steering_path.unlink()
            else:
                spec.steering_path.rename(_backup_path(spec.steering_path))
            written[tool] = 1
            continue
        if spec.steering_path.exists() and _MANDATE_SENTINEL in spec.steering_path.read_text(
            encoding="utf-8"
        ):
            written[tool] = 0
            continue
        spec.steering_path.parent.mkdir(parents=True, exist_ok=True)
        spec.steering_path.write_text(
            _render_mandate(repo_root, spec.export_flag), encoding="utf-8"
        )
        written[tool] = 1
    return written


def _remove_owned_hooks(
    path: Path, *, event: str, sentinel: str, label: str, owned_file: bool = False
) -> int:
    """Remove every ``event`` command hook carrying ``sentinel`` from ``path``.

    The inverse of the merges: StudyLoop owns exactly the hooks whose command
    carries its sentinel (the merges treat such a hook as theirs too). Every
    other hook and group is kept as it was; a group, the event list and the
    ``hooks`` object are dropped only when that removal is what emptied them,
    so a file install appended to is written back as it began. With
    ``owned_file`` (Grok's ``hooks/studyloop.json``, StudyLoop's by name) a file
    left with nothing in it is deleted. Returns the number of hooks removed.

    Byte-preserving like :func:`_remove_json_mcp_entries` and
    :func:`_remove_claude_statusline`: each owned hook is cut with the
    separator that joined it, every other byte stays, and the edit is parsed
    back and must equal the original minus the owned hooks before it is
    written -- otherwise nothing is written and :class:`InstallError` names
    the file.
    """
    import copy

    try:
        raw = path.read_bytes().decode("utf-8")
    except FileNotFoundError:
        return 0
    except (OSError, UnicodeDecodeError) as exc:
        raise InstallError(f"Cannot read {label} hooks {path}: {exc}") from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise InstallError(f"Cannot remove {label} hook from malformed {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise InstallError(f"Cannot remove {label} hook: {path} is not a JSON object")
    hooks = data.get("hooks")
    groups = hooks.get(event) if isinstance(hooks, dict) else None
    if not isinstance(hooks, dict) or not isinstance(groups, list):
        return 0

    # The plan, on the parsed tree: which entries are ours, and which groups
    # go with them because ours were all they held.
    owned: list[tuple[int, int]] = []
    dropped_groups: list[int] = []
    for i, group in enumerate(groups):
        entries = group.get("hooks") if isinstance(group, dict) else None
        if not isinstance(group, dict) or not isinstance(entries, list):
            continue
        mine = [
            j
            for j, entry in enumerate(entries)
            if isinstance(entry, dict) and sentinel in str(entry.get("command", ""))
        ]
        owned += [(i, j) for j in mine]
        if mine and len(mine) == len(entries):
            dropped_groups.append(i)
    if not owned:
        return 0

    expected = copy.deepcopy(data)
    kept_groups = [
        group if i not in dropped_groups else None
        for i, group in enumerate(expected["hooks"][event])
    ]
    for i, j in sorted(owned, reverse=True):
        if i not in dropped_groups:
            del expected["hooks"][event][i]["hooks"][j]
    kept_groups = [group for group in kept_groups if group is not None]
    if kept_groups:
        expected["hooks"][event] = kept_groups
    else:
        del expected["hooks"][event]
        if not expected["hooks"]:
            del expected["hooks"]

    # The edits, deepest and last first so every earlier offset stays valid;
    # the path is re-walked on the edited text each time.
    updated: str | None = raw
    if "hooks" not in expected:
        updated = _json_cut_child(updated, (), "hooks")
    elif event not in expected["hooks"]:
        updated = _json_cut_child(updated, ("hooks",), event)
    else:
        for i, j in sorted(owned, reverse=True):
            if updated is not None and i not in dropped_groups:
                updated = _json_cut_child(updated, ("hooks", event, i, "hooks"), j)
        for i in sorted(dropped_groups, reverse=True):
            if updated is not None:
                updated = _json_cut_child(updated, ("hooks", event), i)
    try:
        edited_ok = updated is not None and json.loads(updated) == expected
    except json.JSONDecodeError:
        edited_ok = False
    if updated is None or not edited_ok:
        raise InstallError(f"Cannot remove {label} hook from {path} without rewriting it")
    if owned_file and not expected:
        path.unlink()
    else:
        path.write_bytes(updated.encode("utf-8"))
    return len(owned)


def _merge_hook_group(
    path: Path,
    *,
    label: str,
    event: str,
    sentinel: str,
    group: dict[str, object],
    refresh: Callable[[str], str | None] | None = None,
) -> int:
    """Merge one ``event`` hook group into a ``{"hooks": {...}}`` JSON file.

    Idempotent: a command already carrying ``sentinel`` is not duplicated.
    With ``refresh``, an existing owned command is handed to it and, when it
    returns a replacement, rewritten in place (a legacy form brought up to
    the canonical one). Returns 1 when the file changed, else 0; ``label``
    names the harness in error messages.

    Byte-preserving, the mirror image of :func:`_remove_owned_hooks`: the file
    is the learner's (``~/.claude/settings.json`` carries every Claude Code
    setting), so the group is INSERTED as bytes -- into the event list, or
    with a new ``hooks``/event member when the file has none -- and every
    other byte stays. The edit is parsed back and must equal the original
    plus the group before it is written. A file that does not exist is
    created; one that cannot be read as a JSON object is never edited.
    """
    import copy

    try:
        raw = path.read_bytes().decode("utf-8")
    except FileNotFoundError:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"hooks": {event: [group]}}, indent=2) + "\n", encoding="utf-8")
        return 1
    except (OSError, UnicodeDecodeError) as exc:
        raise InstallError(f"Cannot read {label} hooks {path}: {exc}") from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise InstallError(f"Cannot merge {label} hook into malformed {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise InstallError(f"Cannot merge {label} hook: {path} is not a JSON object")
    hooks = data.get("hooks", {})
    if not isinstance(hooks, dict):
        raise InstallError(f"Cannot merge {label} hook: {path} hooks is not an object")
    groups = hooks.get(event, [])
    if not isinstance(groups, list):
        raise InstallError(f"Cannot merge {label} hook: {path} hooks.{event} is not a list")

    expected = copy.deepcopy(data)
    updated: str | None = None
    found = False
    for i, existing in enumerate(groups):
        entries = existing.get("hooks") if isinstance(existing, dict) else None
        if not isinstance(entries, list):
            continue
        for j, entry in enumerate(entries):
            if not isinstance(entry, dict) or sentinel not in str(entry.get("command", "")):
                continue
            replacement = refresh(str(entry.get("command", ""))) if refresh else None
            if replacement is None:
                return 0
            found = True
            expected["hooks"][event][i]["hooks"][j]["command"] = replacement
            span = _json_path_span(raw, ("hooks", event, i, "hooks", j, "command"))
            if span is not None:
                updated = raw[: span[0]] + json.dumps(replacement) + raw[span[1] :]
            break
        if found:
            break
    if not found:
        expected.setdefault("hooks", {}).setdefault(event, []).append(copy.deepcopy(group))
        root = _json_root_object_span(raw)
        if root is None:
            updated = None
        elif "hooks" not in data:
            updated = _append_json_members(raw, root, {"hooks": {event: [group]}})
        elif event not in hooks:
            span = _json_path_span(raw, ("hooks",))
            updated = None if span is None else _append_json_members(raw, span, {event: [group]})
        else:
            span = _json_path_span(raw, ("hooks", event))
            updated = None if span is None else _append_json_elements(raw, span, [group])
    try:
        edited_ok = updated is not None and json.loads(updated) == expected
    except json.JSONDecodeError:
        edited_ok = False
    if updated is None or not edited_ok:
        raise InstallError(f"Cannot merge {label} hook into {path} without rewriting it")
    path.write_bytes(updated.encode("utf-8"))
    return 1


def install_claude_stop_hook(*, uninstall: bool = False) -> int:
    """Merge the session-export Stop hook into ~/.claude/settings.json.

    Byte-preserving read-modify-write (:func:`_merge_hook_group`) that keeps
    every existing hook and every other byte of the learner's file;
    idempotent (a hook already containing the sentinel is not duplicated).
    An existing session-export hook in a legacy form (a PATH lookup, or output
    discarded with ``|| true``) is rewritten in place to the canonical
    command. Returns 1 if the file changed, else 0. ``uninstall=True``
    removes the hook again (:func:`_remove_owned_hooks`) and returns the
    number removed.
    """
    settings_path = _HOME / ".claude/settings.json"
    if uninstall:
        return _remove_owned_hooks(
            settings_path, event="Stop", sentinel=_HOOK_SENTINEL, label="Claude"
        )
    canonical = export_hook_command("--claude-only")

    def refresh(command: str) -> str | None:
        return None if hook_command_is_canonical(command, "--claude-only") else canonical

    return _merge_hook_group(
        settings_path,
        label="Claude",
        event="Stop",
        sentinel=_HOOK_SENTINEL,
        group={
            "matcher": "",
            "hooks": [
                {
                    "type": "command",
                    "command": canonical,
                    "timeout": 30,
                    "async": True,
                }
            ],
        },
        refresh=refresh,
    )


def _merge_session_end_hook(path: Path, *, label: str, sentinel: str, hook: dict) -> int:
    """Merge one ``SessionEnd`` command hook into a ``{"hooks": {...}}`` JSON file.

    :func:`_merge_hook_group` for the Codex and Grok registries: byte-preserving,
    idempotent on ``sentinel``. Returns 1 if the hook was added, else 0.
    """
    return _merge_hook_group(
        path, label=label, event="SessionEnd", sentinel=sentinel, group={"hooks": [hook]}
    )


def install_codex_session_end_hook(*, uninstall: bool = False) -> int:
    """Merge StudyLoop's SessionEnd hook into ``~/.codex/hooks.json``.

    Codex loads global hooks from this file for CLI and app sessions. Existing
    hook groups are preserved; StudyLoop owns only the command carrying its
    sentinel. Codex asks the user to trust new command-hook hashes before the
    first execution — the installer cannot and must not bypass that review.
    ``uninstall=True`` removes that command again.
    """
    if uninstall:
        return _remove_owned_hooks(
            _codex_hooks_path(), event="SessionEnd", sentinel=_CODEX_HOOK_SENTINEL, label="Codex"
        )
    return _merge_session_end_hook(
        _codex_hooks_path(),
        label="Codex",
        sentinel=_CODEX_HOOK_SENTINEL,
        hook={
            "type": "command",
            "command": f"{_CODEX_HOOK_SENTINEL} >/dev/null 2>&1 || true",
            "timeout": 3,
        },
    )


#: The shell line Grok runs at ``SessionEnd``. Grok hands the event to the
#: command as JSON on stdin and, per its hooks guide, includes ``subagentType``
#: only for a child session's teardown -- so a payload carrying that key is a
#: subagent ending, not the session, and the export is skipped (the parent's
#: own ``SessionEnd`` follows). The pattern is the quoted KEY followed by a
#: colon, so a field whose string *value* happens to be ``subagentType``
#: cannot cause a false skip (a JSON string value can never contain an
#: unescaped ``"subagentType":``). ``grep`` is POSIX, so the line needs
#: nothing StudyLoop does not already install. Always exits 0: hooks are
#: fail-open anyway, and an export failure must never surface as a Grok error.
_GROK_HOOK_COMMAND = (
    f"grep -q '\"subagentType\" *:' || {_GROK_HOOK_SENTINEL} >/dev/null 2>&1 || true"
)


def install_grok_session_end_hook(*, uninstall: bool = False) -> int:
    """Write StudyLoop's SessionEnd hook to ``$GROK_HOME/hooks/studyloop.json``.

    Grok Build loads every ``*.json`` under its ``hooks/`` directory as global
    hooks, so StudyLoop owns this file by name; it is still merged rather than
    overwritten so anything a user added to it survives. The timeout sits
    above Grok's 5 s default because a cold ``session-export`` start on a slow
    machine can exceed it, and below the 10 s exit budget Grok gives
    ``SessionEnd`` hooks (a measured warm run here took 0.17 s).
    ``uninstall=True`` removes the hook, and the file once nothing else is in it.
    """
    if uninstall:
        return _remove_owned_hooks(
            _grok_hooks_path(),
            event="SessionEnd",
            sentinel=_GROK_HOOK_SENTINEL,
            label="Grok",
            owned_file=True,
        )
    return _merge_session_end_hook(
        _grok_hooks_path(),
        label="Grok",
        sentinel=_GROK_HOOK_SENTINEL,
        hook={"type": "command", "command": _GROK_HOOK_COMMAND, "timeout": 8},
    )


def find_repo_root(start: Path | None = None) -> Path | None:
    """Locate the repository root when running from a source checkout."""
    candidates = []
    if start is not None:
        candidates.append(start.resolve())
    candidates.extend([Path.cwd().resolve(), Path(__file__).resolve()])

    seen: set[Path] = set()
    for candidate in candidates:
        current = candidate if candidate.is_dir() else candidate.parent
        for path in (current, *current.parents):
            if path in seen:
                continue
            seen.add(path)
            if (
                (path / "pyproject.toml").exists()
                and (path / "packages" / "studyloop").exists()
                and (path / "scripts" / "install.sh").exists()
            ):
                return path
    return None


def require_repo_root(start: Path | None = None) -> Path:
    """Return the repo root or raise an install error."""
    repo_root = find_repo_root(start)
    if repo_root is None:
        msg = "This command requires a source checkout of studyloop."
        raise InstallError(msg)
    return repo_root


def _run(cmd: list[str], *, cwd: Path | None = None) -> None:
    subprocess.run(cmd, cwd=str(cwd) if cwd else None, check=True)


def install_workspace_tools(
    repo_root: Path,
    *,
    sync_workspace: bool = True,
    force: bool = True,
) -> list[str]:
    """Install editable workspace packages as global uv tools."""
    installed: list[str] = []

    if sync_workspace:
        # --inexact: refresh the workspace venv without REMOVING what the
        # developer synced into it. A plain `uv sync --all-packages` strips
        # every extra (semantic, web, content), which is how a developer's
        # .venv/bin/session-maint lost sqlite-vec straight after an install
        # and printed "Semantic layer not installed" for a tool venv that was
        # already correct.
        _run(["uv", "sync", "--all-packages", "--inexact"], cwd=repo_root)

    packages_dir = repo_root / "packages"
    # Pins every `uv tool install` below to the INVOKING interpreter's minor
    # version -- the synced venv running under `uv run` right now -- so the
    # new global tool venvs share the workspace's minor instead of whatever
    # `uv tool install` would otherwise resolve on its own (A3). This is
    # deliberately sys.version_info, not sys.executable: a venv interpreter
    # is the wrong base for a new tool venv, so identity is not passed, only
    # the minor version.
    py_version = f"{sys.version_info.major}.{sys.version_info.minor}"
    for pkg_dir in sorted(p for p in packages_dir.iterdir() if p.is_dir()):
        package_name = pkg_dir.name
        cmd = ["uv", "tool", "install", "--python", py_version]
        # Both packages install with their [all] aggregate extra so a single
        # `./scripts/install.sh` yields a fully working tool — web UI, content
        # generation, Bedrock (boto3), MCP server, NotebookLM, TUI, and
        # semantic session search. Partial extras here are how "No module
        # named 'boto3'/'mcp'" surfaced in otherwise-green installs.
        #
        # studyloop's own [all] does NOT include agent-session-tools (R-29):
        # it is not published, so it cannot resolve as a wheel extra outside
        # this workspace. `--with-editable` below is the real, unconditional
        # mechanism that makes it a hard dependency of THIS install path
        # regardless of any extra (DECISIONS.md B1).
        if package_name == "agent-session-tools":
            cmd.append(f"{pkg_dir}[all]")
        elif package_name == "studyloop":
            cmd.append(f"{pkg_dir}[all]")
            # [all] on the co-installed package too. `studyloop web` imports
            # agent_session_tools IN THIS venv: the server's boot-time encoder
            # warm and every hybrid search run tokenizers, onnxruntime,
            # huggingface_hub, numpy and sqlite_vec here, not in
            # agent-session-tools' own tool venv. Co-installed bare, the warm
            # failed at import and the header chip read "semantic: failed".
            ast_pkg = repo_root / "packages" / "agent-session-tools"
            cmd.extend(["--with-editable", f"{ast_pkg}[all]"])
        else:
            cmd.append(str(pkg_dir))
        cmd.append("--editable")
        if force:
            cmd.append("--force")
        _run(cmd, cwd=repo_root)
        installed.append(package_name)

    return installed


def _render_target(template: str, repo_root: Path) -> Path:
    return Path(template.format(repo_root=repo_root)).expanduser()


def _render_source(source: str, repo_root: Path) -> Path:
    """Resolve a :class:`LinkSpec` source to a real path.

    Absolute or ``~``-prefixed sources link to an existing location on disk (the
    skills hub); everything else is repository-relative, as it always was.
    """
    if source.startswith("~") or Path(source).is_absolute():
        return Path(source).expanduser()
    return repo_root / source


def _points_to(target: Path, source: Path) -> bool:
    """True if symlink ``target`` points at ``source`` (relative or absolute form)."""
    current = Path(os.readlink(target))
    if not current.is_absolute():
        current = target.parent / current
    return current.resolve() == source.resolve()


def _agent_name(path: Path) -> str | None:
    """The ``name`` of the agent definition at *path*, or None if it is not one."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    name = data.get("name") if isinstance(data, dict) else None
    return name if isinstance(name, str) else None


def _copy_path(source: Path, target: Path, *, uninstall: bool) -> int:
    """Install ``source`` at ``target`` as a copy (``LinkSpec.copy``); 1 if anything changed.

    The file is StudyLoop's by NAME: a target whose agent ``name`` matches the
    source's is ours whatever its content now says -- a copy kiro-cli has since
    migrated is refreshed in place with no backup, since the migration is the
    reason the file is a copy at all (see :class:`LinkSpec`). A legacy link from
    an earlier install is replaced. Anything else at the path belongs to the
    learner: on install it is moved to ``<name>.bak`` first, on uninstall it is
    left alone.
    """
    ours = target.is_symlink() and _points_to(target, source)
    if not target.is_symlink() and target.is_file():
        ours = _agent_name(target) == _agent_name(source)
    if uninstall:
        if ours:
            target.unlink()
            return 1
        return 0
    if target.is_symlink():
        target.unlink()  # legacy layout, or a stale link: the copy replaces it either way
    elif target.is_file():
        if target.read_bytes() == source.read_bytes():
            return 0
        if not ours:
            shutil.move(str(target), str(target.with_name(f"{target.name}.bak")))
    elif target.exists():
        shutil.move(str(target), str(target.with_name(f"{target.name}.bak")))
    shutil.copyfile(source, target)
    return 1


def _link_paths(repo_root: Path, specs: tuple[LinkSpec, ...], *, uninstall: bool) -> int:
    changed = 0
    for spec in specs:
        source = _render_source(spec.source, repo_root)
        target = _render_target(spec.target, repo_root)
        if spec.copy:
            if not uninstall and not source.exists():
                raise InstallError(f"Missing install asset: {source}")
            target.parent.mkdir(parents=True, exist_ok=True)
            changed += _copy_path(source, target, uninstall=uninstall)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        if uninstall:
            if target.is_symlink() and _points_to(target, source):
                target.unlink()
                changed += 1
            continue

        if not source.exists():
            raise InstallError(f"Missing install asset: {source}")

        if target.is_symlink():
            if os.readlink(target) == str(source):
                continue
            # Legacy absolute (or otherwise stale) link — replace below.
            target.unlink()
        elif target.exists():
            backup = target.with_name(f"{target.name}.bak")
            shutil.move(str(target), str(backup))

        target.symlink_to(source)
        changed += 1
    return changed


def detect_available_agent_tools() -> list[str]:
    """Detect agent environments available on this machine."""
    available: list[str] = []
    if (_HOME / ".kiro").is_dir():
        available.append("kiro")
    if (_HOME / ".claude").is_dir():
        available.append("claude")
    if shutil.which("opencode"):
        available.append("opencode")
    if shutil.which("codex"):
        available.append("codex")
    if shutil.which("pi") or (_HOME / ".pi").is_dir():
        available.append("pi")
    if shutil.which("grok") or _grok_home().is_dir():
        available.append("grok")
    return available


def _claude_statusline_is_ours(command: object, statusline: Path) -> bool:
    """Whether a ``statusLine`` command runs the script install copies to ~/.claude/.

    The shipped template's ``~`` spelling, and the two spellings it expands to
    (``$HOME`` and the absolute path). Anything else is the learner's own.
    """
    if not isinstance(command, str):
        return False
    ours = {"~/.claude/study-statusline.sh", "$HOME/.claude/study-statusline.sh", str(statusline)}
    return command.strip() in ours


def _remove_claude_statusline(settings: Path, statusline: Path) -> int:
    """Remove Claude Code's ``statusLine`` entry when it runs StudyLoop's script.

    Uninstall deletes the script, so an entry left pointing at it runs a
    missing command on every render. Ownership is judged the way the other
    removers judge theirs: the entry is StudyLoop's only when its command is
    the script install points it at; a learner's own status line is kept.
    Byte-preserving like :func:`_remove_json_mcp_entries`: the member is cut
    with the separator that joined it, every other byte stays, and the edit
    is parsed back and must equal the original minus ``statusLine`` before it
    is written. Returns 1 when removed; 0 for a missing, malformed or
    learner-owned entry.
    """
    import json

    try:
        raw = settings.read_bytes().decode("utf-8")
        loaded = json.loads(raw)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return 0
    if not isinstance(loaded, dict):
        return 0
    entry = loaded.get("statusLine")
    if not isinstance(entry, dict) or not _claude_statusline_is_ours(
        entry.get("command"), statusline
    ):
        return 0
    root = _json_root_object_span(raw)
    members = _json_member_spans(raw, root) if root is not None else None
    index = next((i for i, m in enumerate(members or []) if m[0] == "statusLine"), None)
    updated = None
    if root is not None and members is not None and index is not None:
        _, key_start, _, value_end = members[index]
        if len(members) == 1:
            updated = raw[: root[0] + 1] + raw[root[1] - 1 :]
        elif index > 0:
            updated = raw[: members[index - 1][3]] + raw[value_end:]
        else:
            updated = raw[:key_start] + raw[members[1][1] :]
    expected = {key: value for key, value in loaded.items() if key != "statusLine"}
    try:
        edited_ok = updated is not None and json.loads(updated) == expected
    except json.JSONDecodeError:
        edited_ok = False
    if updated is None or not edited_ok:
        raise InstallError(
            f"Cannot remove StudyLoop's statusLine from {settings} without rewriting it"
        )
    settings.write_bytes(updated.encode("utf-8"))
    return 1


def _add_claude_statusline(settings: Path, template: Path) -> int:
    """Add StudyLoop's ``statusLine`` to an existing ``settings.json`` that has none.

    Install used to copy the shipped template only when the file did not exist,
    so a learner with any Claude Code setting of their own never received the
    status line, and only a stale entry left by an earlier uninstall made a
    reinstall look as if it had worked. The mirror image of
    :func:`_remove_claude_statusline`: a learner's own ``statusLine`` is kept
    untouched; otherwise the member is INSERTED as bytes before the closing
    brace, every other byte stays, and the edit is parsed back and must equal
    the original plus the entry before it is written. Returns 1 when added,
    0 when the file already has a ``statusLine`` or cannot be read as a JSON
    object (a file that cannot be understood is never edited).
    """
    import json

    try:
        raw = settings.read_bytes().decode("utf-8")
        loaded = json.loads(raw)
        entry = json.loads(template.read_text(encoding="utf-8"))["statusLine"]
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError):
        return 0
    if not isinstance(loaded, dict) or "statusLine" in loaded:
        return 0
    root = _json_root_object_span(raw)
    if root is None:
        raise InstallError(f"Cannot add StudyLoop's statusLine to {settings} without rewriting it")
    members = _json_member_spans(raw, root) or []
    close = root[1] - 1  # index of the closing brace
    member = f'"statusLine": {json.dumps(entry)}'
    if members:
        # Join with the separator the file already uses between its last
        # member and the closing brace (", " on one line, ",\n    " indented).
        last_value_end = members[-1][3]
        gap = raw[last_value_end:close]
        # Indent the new member like the last one: the whitespace that opens
        # the last member's own line (the gap before the brace holds the
        # brace's indentation, which is one level shallower).
        last_key_start = members[-1][1]
        line_start = raw.rfind("\n", 0, last_key_start) + 1
        indent = raw[line_start:last_key_start]
        between = (",\n" + indent) if "\n" in gap else ", "
        # ``gap`` is re-added after the member so the brace keeps its own line
        # and indentation.
        updated = raw[:last_value_end] + between + member + gap + raw[close:]
    else:
        updated = raw[: root[0] + 1] + member + raw[close:]
    expected = {**loaded, "statusLine": entry}
    try:
        edited_ok = json.loads(updated) == expected
    except json.JSONDecodeError:
        edited_ok = False
    if not edited_ok:
        raise InstallError(f"Cannot add StudyLoop's statusLine to {settings} without rewriting it")
    settings.write_bytes(updated.encode("utf-8"))
    return 1


def _configure_claude(repo_root: Path, *, uninstall: bool) -> int:
    claude_home = _HOME / ".claude"
    statusline = claude_home / "study-statusline.sh"
    settings = claude_home / "settings.json"
    shipped = repo_root / "agents/claude/study-statusline.sh"
    changed = 0

    if uninstall:
        # The entry first: if it cannot be removed cleanly, the script it
        # points at is still there.
        changed += _remove_claude_statusline(settings, statusline)
        if statusline.exists():
            # The mandate remover's rule: a copy of what install wrote is
            # deleted; anything else may carry the learner's edits (or an
            # older release's script) and is kept as a .bak beside it. The
            # statusLine entry is already gone, so the .bak is never run.
            if statusline.read_bytes() == shipped.read_bytes():
                statusline.unlink()
            else:
                statusline.rename(_backup_path(statusline))
            changed += 1
        return changed

    claude_home.mkdir(parents=True, exist_ok=True)
    shutil.copy2(shipped, statusline)
    statusline.chmod(0o755)
    changed += 1
    template = repo_root / "agents/claude/settings.json"
    if not settings.exists():
        shutil.copy2(template, settings)
        changed += 1
    else:
        changed += _add_claude_statusline(settings, template)
    return changed


def install_agent_definitions(
    repo_root: Path,
    *,
    tools: list[str] | None = None,
    uninstall: bool = False,
) -> dict[str, int]:
    """Install or remove agent definition links for the requested tools."""
    selected = tools or detect_available_agent_tools()
    if not selected:
        raise InstallError(
            "No supported AI tools detected. "
            "Install Kiro CLI, Codex, Claude Code, OpenCode, pi, or Grok Build first."
        )

    invalid = [tool for tool in selected if tool not in _AGENT_CHOICES]
    if invalid:
        raise InstallError(f"Unsupported agent tool(s): {', '.join(sorted(invalid))}")

    summary: dict[str, int] = {"shared": _link_paths(repo_root, _SHARED_LINKS, uninstall=uninstall)}

    for tool in selected:
        summary[tool] = _link_paths(repo_root, _TOOL_LINKS[tool], uninstall=uninstall)
        # The xTiles skill, linked from the hub the shared pass installed above.
        # Ordering matters and is not incidental: _SHARED_LINKS runs first, so the
        # hub exists before anything points at it.
        if skill_link := XTILES_SKILL_LINKS.get(tool):
            summary[tool] += _link_paths(repo_root, (skill_link,), uninstall=uninstall)
        if memory_link := SESSION_MEMORY_SKILL_LINKS.get(tool):
            summary[tool] += _link_paths(repo_root, (memory_link,), uninstall=uninstall)
        if tool == "claude":
            summary[tool] += _configure_claude(repo_root, uninstall=uninstall)

    # Cross-harness session-memory wiring: query skill links/static native
    # hooks were installed above; add steering mandates and merge the two
    # user-owned JSON hook registries without replacing existing groups.
    if not uninstall:
        for tool, count in install_session_db_mandate(repo_root, tools=selected).items():
            summary[tool] = summary.get(tool, 0) + count
        if "claude" in selected:
            summary["claude"] = summary.get("claude", 0) + install_claude_stop_hook()
        if "codex" in selected:
            summary["codex"] = summary.get("codex", 0) + install_codex_session_end_hook()
        if "grok" in selected:
            summary["grok"] = summary.get("grok", 0) + install_grok_session_end_hook()
        for tool, count in register_mcp_servers(selected).items():
            summary[tool] = summary.get(tool, 0) + count
    else:
        # The same surfaces in reverse. Each remover takes away only what
        # carries StudyLoop's sentinel or server name and keeps every other
        # byte of the learner's files (review F-OPS-02: uninstall used to skip
        # this block, leaving export hooks and MCP servers live).
        removed = install_session_db_mandate(repo_root, tools=selected, uninstall=True)
        for tool, count in removed.items():
            summary[tool] = summary.get(tool, 0) + count
        if "claude" in selected:
            summary["claude"] = summary.get("claude", 0) + install_claude_stop_hook(uninstall=True)
        if "codex" in selected:
            summary["codex"] = summary.get("codex", 0) + install_codex_session_end_hook(
                uninstall=True
            )
        if "grok" in selected:
            summary["grok"] = summary.get("grok", 0) + install_grok_session_end_hook(uninstall=True)
        for tool, count in register_mcp_servers(selected, uninstall=True).items():
            summary[tool] = summary.get(tool, 0) + count

    return summary


def ensure_default_config() -> Path:
    """Create a default config file if it does not already exist."""
    config_path = get_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    if not config_path.exists():
        config_path.write_text(generate_default_config())
    return config_path


def ensure_review_directories() -> list[Path]:
    """Create any configured topic review directories that do not yet exist."""
    created: list[Path] = []
    for topic in load_settings().topics:
        path = topic.obsidian_path.expanduser()
        if not path.exists():
            path.mkdir(parents=True, exist_ok=True)
            created.append(path)
    return created


def ensure_review_database() -> Path:
    """Bootstrap or migrate the review database."""
    from studyloop.review_db import ensure_tables, get_db_path

    db_path = get_db_path()
    ensure_tables(db_path)
    return db_path


__all__ = [
    "InstallError",
    "detect_available_agent_tools",
    "ensure_default_config",
    "ensure_review_database",
    "ensure_review_directories",
    "find_repo_root",
    "install_agent_definitions",
    "install_workspace_tools",
    "mcp_registration_status",
    "register_grok_mcp_servers",
    "register_mcp_servers",
    "require_repo_root",
    "unregister_grok_mcp_servers",
    "unregister_mcp_servers",
]
