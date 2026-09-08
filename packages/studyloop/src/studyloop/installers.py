"""Install helpers for studyloop tools, agents, and config bootstrap."""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from studyloop.harnesses import RELEASE_HARNESSES
from studyloop.settings import generate_default_config, get_config_path, load_settings

if TYPE_CHECKING:
    from collections.abc import Mapping


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
    """

    source: str
    target: str


_HOME = Path.home()

_TOOL_LINKS: dict[str, tuple[LinkSpec, ...]] = {
    "kiro": (
        LinkSpec("agents/kiro/study-mentor.json", str(_HOME / ".kiro/agents/study-mentor.json")),
        LinkSpec("agents/kiro/study-mentor", str(_HOME / ".kiro/agents/study-mentor")),
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
    ),
    "opencode": (
        LinkSpec(
            "agents/opencode/study-mentor.md",
            str(_HOME / ".config/opencode/agents/study-mentor.md"),
        ),
        LinkSpec(
            "agents/opencode/plugins/studyloop-session-export.js",
            str(_HOME / ".config/opencode/plugins/studyloop-session-export.js"),
        ),
    ),
    "codex": (LinkSpec("agents/codex/AGENTS.md", "{repo_root}/AGENTS.md"),),
    # Deliberately the SAME source and target as codex. Grok Build reads the
    # AGENTS.md instruction-file family from the repository root down to the
    # working directory, exactly as Codex does, so both harnesses are served by
    # one repo-root file. A grok-specific copy under agents/grok/ would be a
    # second body of the same persona and would drift; none has ever existed.
    "grok": (LinkSpec("agents/codex/AGENTS.md", "{repo_root}/AGENTS.md"),),
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
}

# Sentinel marking a steering file as carrying the export mandate (idempotency
# + the doctor harness check both key on this).
_MANDATE_SENTINEL = "studyloop:session-export-mandate"
# Sentinel inside the Claude Stop hook command (idempotent merge + doctor check).
_HOOK_SENTINEL = "session-export --claude-only"
_SESSION_HOOK_SENTINEL = "studyloop:session-export-hook"
_CODEX_HOOK_SENTINEL = "session-export --codex-only"

_MCP_SERVERS: dict[str, dict[str, object]] = {
    "session-db": {"command": "session-db-mcp", "args": []},
    "studyloop": {"command": "studyloop-mcp", "args": []},
}
_MCP_HARNESSES = ("claude", "kiro", "codex")


def _mcp_config_path(tool: str) -> Path:
    paths = {
        "claude": _HOME / ".claude.json",
        "kiro": _HOME / ".kiro/settings/mcp.json",
        "codex": _HOME / ".codex/config.toml",
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


def _json_value_span(
    raw: str, key: str, object_span: tuple[int, int] | None = None
) -> tuple[int, int] | None:
    """Return an arbitrary JSON member value span from one object."""
    import json

    span = object_span or _json_root_object_span(raw)
    if span is None:
        return None
    start, end = span
    decoder = json.JSONDecoder()
    cursor = start + 1
    while cursor < end - 1:
        while cursor < end - 1 and (raw[cursor].isspace() or raw[cursor] == ","):
            cursor += 1
        if cursor >= end - 1:
            break
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
        if member_name == key:
            return value_start, value_end
        cursor = value_end
    return None


def _json_object_span(raw: str, key: str) -> tuple[int, int] | None:
    """Return an object-valued top-level member span for ``key``."""
    span = _json_value_span(raw, key)
    if span is None or raw[span[0]] != "{":
        return None
    return span


def _append_json_members(
    raw: str,
    span: tuple[int, int],
    members: Mapping[str, object],
) -> str:
    """Append object members while retaining every existing member byte."""
    import json

    start, end = span
    close = end - 1
    content_end = close
    while content_end > start + 1 and raw[content_end - 1].isspace():
        content_end -= 1
    existing = raw[start + 1 : content_end].strip()
    line_start = raw.rfind("\n", 0, close) + 1
    closing_indent = raw[line_start:close]
    if not closing_indent.isspace():
        closing_indent = "  "
    entry_indent = closing_indent + "  "
    newline = "\r\n" if "\r\n" in raw else "\n"
    rendered: list[str] = []
    for name, value in members.items():
        value_text = json.dumps(value, indent=2)
        value_text = value_text.replace("\n", newline + entry_indent)
        rendered.append(f"{entry_indent}{json.dumps(name)}: {value_text}")
    separator = "," if existing else ""
    insertion = separator + newline + ("," + newline).join(rendered) + newline + closing_indent
    return raw[:content_end] + insertion + raw[close:]


def _merge_json_mcp_config(path: Path) -> int:
    import json

    try:
        raw = path.read_bytes().decode("utf-8")
    except FileNotFoundError:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"mcpServers": _MCP_SERVERS}, indent=2) + "\n",
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
    current = loaded.get("mcpServers")
    if isinstance(current, dict) and all(
        current.get(name) == value for name, value in _MCP_SERVERS.items()
    ):
        return 0

    if "mcpServers" not in loaded:
        updated = _append_json_members(raw, root_span, {"mcpServers": _MCP_SERVERS})
    elif not isinstance(current, dict):
        container_span = _json_value_span(raw, "mcpServers", root_span)
        if container_span is None:
            raise InstallError(f"Cannot locate mcpServers value in {path}")
        rendered = json.dumps(_MCP_SERVERS, separators=(", ", ": "))
        updated = raw[: container_span[0]] + rendered + raw[container_span[1] :]
    else:
        mcp_span = _json_object_span(raw, "mcpServers")
        if mcp_span is None:
            raise InstallError(f"Cannot locate mcpServers object in {path}")
        incorrect = {
            name: value for name, value in _MCP_SERVERS.items() if current.get(name) != value
        }
        updated = raw
        for name in sorted(set(incorrect) & set(current)):
            mcp_span = _json_object_span(updated, "mcpServers")
            if mcp_span is None:
                raise InstallError(f"Cannot locate mcpServers object in {path}")
            nested = updated[mcp_span[0] : mcp_span[1]]
            value_span = _json_value_span(nested, name)
            if value_span is None:
                raise InstallError(f"Cannot locate owned MCP server {name} in {path}")
            value_start = mcp_span[0] + value_span[0]
            value_end = mcp_span[0] + value_span[1]
            rendered = json.dumps(_MCP_SERVERS[name], separators=(", ", ": "))
            updated = updated[:value_start] + rendered + updated[value_end:]
        absent = {name: value for name, value in incorrect.items() if name not in current}
        if absent:
            mcp_span = _json_object_span(updated, "mcpServers")
            if mcp_span is None:
                raise InstallError(f"Cannot locate mcpServers object in {path}")
            updated = _append_json_members(updated, mcp_span, absent)
    path.write_bytes(updated.encode("utf-8"))
    return 1


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


def register_mcp_servers(tools: list[str] | None = None) -> dict[str, int]:
    """Register both StudyLoop MCP servers in supported harness configs."""
    selected = [
        tool for tool in (tools or detect_available_agent_tools()) if tool in _MCP_HARNESSES
    ]
    changed: dict[str, int] = {}
    for tool in selected:
        path = _mcp_config_path(tool)
        changed[tool] = (
            _merge_codex_mcp_config(path) if tool == "codex" else _merge_json_mcp_config(path)
        )
    return changed


def mcp_registration_status(tools: list[str] | None = None) -> dict[str, bool]:
    """Report registration state without modifying any harness configuration."""
    import json
    import tomllib

    selected = list(tools or _MCP_HARNESSES)
    status: dict[str, bool] = {}
    for tool in selected:
        path = _mcp_config_path(tool)
        try:
            if tool == "codex":
                data = tomllib.loads(path.read_text(encoding="utf-8"))
                current = data.get("mcp_servers", {})
            else:
                data = json.loads(path.read_text(encoding="utf-8"))
                current = data.get("mcpServers", {})
            status[tool] = isinstance(current, dict) and all(
                current.get(name) == value for name, value in _MCP_SERVERS.items()
            )
        except (OSError, ValueError, TypeError):
            status[tool] = False
    return status


def _codex_hooks_path() -> Path:
    return _HOME / ".codex/hooks.json"


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


def install_session_db_mandate(repo_root: Path, tools: list[str] | None = None) -> dict[str, int]:
    """Write the session-export steering mandate into each harness's file.

    Idempotent: a file already containing the sentinel is left untouched.
    A file without it is overwritten with the rendered mandate (these
    session-db.md files are StudyLoop-managed, single-purpose). Returns a
    per-tool count of files written.
    """
    selected = tools or detect_available_agent_tools()
    written: dict[str, int] = {}
    for tool in selected:
        spec = _HARNESS_EXPORT.get(tool)
        if spec is None:
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


def install_claude_stop_hook() -> int:
    """Merge the session-export Stop hook into ~/.claude/settings.json.

    Read-modify-write that preserves existing hooks; idempotent (a hook
    already containing the sentinel is not duplicated). Returns 1 if a hook
    was added, else 0.
    """
    import json

    settings_path = _HOME / ".claude/settings.json"
    data: dict = {}
    try:
        raw = settings_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        settings_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise InstallError(f"Cannot read Claude settings {settings_path}: {exc}") from exc
    else:
        try:
            loaded = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise InstallError(
                f"Cannot merge Claude hook into malformed {settings_path}: {exc}"
            ) from exc
        if not isinstance(loaded, dict):
            raise InstallError(f"Cannot merge Claude hook: {settings_path} is not a JSON object")
        data = loaded

    hooks = data.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise InstallError(f"Cannot merge Claude hook: {settings_path} hooks is not an object")
    stop = hooks.setdefault("Stop", [])
    if not isinstance(stop, list):
        raise InstallError(f"Cannot merge Claude hook: {settings_path} hooks.Stop is not a list")

    # Idempotency: bail if any existing Stop hook already runs session-export.
    for group in stop:
        for h in (group or {}).get("hooks", []) if isinstance(group, dict) else []:
            if _HOOK_SENTINEL in str(h.get("command", "")):
                return 0

    stop.append(
        {
            "matcher": "",
            "hooks": [
                {
                    "type": "command",
                    "command": f"{_HOOK_SENTINEL} >/dev/null 2>&1 || true",
                    "timeout": 30,
                    "async": True,
                }
            ],
        }
    )
    settings_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return 1


def install_codex_session_end_hook() -> int:
    """Merge StudyLoop's SessionEnd hook into ``~/.codex/hooks.json``.

    Codex loads global hooks from this file for CLI and app sessions. Existing
    hook groups are preserved; StudyLoop owns only the command carrying its
    sentinel. Codex asks the user to trust new command-hook hashes before the
    first execution — the installer cannot and must not bypass that review.
    """
    import json

    path = _codex_hooks_path()
    data: dict = {}
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise InstallError(f"Cannot read Codex hooks {path}: {exc}") from exc
    else:
        try:
            loaded = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise InstallError(f"Cannot merge Codex hook into malformed {path}: {exc}") from exc
        if not isinstance(loaded, dict):
            raise InstallError(f"Cannot merge Codex hook: {path} is not a JSON object")
        data = loaded

    hooks = data.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise InstallError(f"Cannot merge Codex hook: {path} hooks is not an object")
    groups = hooks.setdefault("SessionEnd", [])
    if not isinstance(groups, list):
        raise InstallError(f"Cannot merge Codex hook: {path} hooks.SessionEnd is not a list")

    for group in groups:
        for hook in (group or {}).get("hooks", []) if isinstance(group, dict) else []:
            if _CODEX_HOOK_SENTINEL in str(hook.get("command", "")):
                return 0

    groups.append(
        {
            "hooks": [
                {
                    "type": "command",
                    "command": f"{_CODEX_HOOK_SENTINEL} >/dev/null 2>&1 || true",
                    "timeout": 3,
                }
            ]
        }
    )
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return 1


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
        _run(["uv", "sync", "--all-packages"], cwd=repo_root)

    packages_dir = repo_root / "packages"
    for pkg_dir in sorted(p for p in packages_dir.iterdir() if p.is_dir()):
        package_name = pkg_dir.name
        cmd = ["uv", "tool", "install"]
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
            cmd.extend(["--with-editable", str(repo_root / "packages" / "agent-session-tools")])
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


def _link_paths(repo_root: Path, specs: tuple[LinkSpec, ...], *, uninstall: bool) -> int:
    changed = 0
    for spec in specs:
        source = _render_source(spec.source, repo_root)
        target = _render_target(spec.target, repo_root)
        # In-repo targets use relative links so they survive repo moves and
        # syncing between machines with different absolute paths.
        in_repo = "{repo_root}" in spec.target
        link_value = Path(os.path.relpath(source, target.parent)) if in_repo else source
        target.parent.mkdir(parents=True, exist_ok=True)
        if uninstall:
            if target.is_symlink() and _points_to(target, source):
                target.unlink()
                changed += 1
            continue

        if not source.exists():
            raise InstallError(f"Missing install asset: {source}")

        if target.is_symlink():
            if os.readlink(target) == str(link_value):
                continue
            # Legacy absolute (or otherwise stale) link — replace below.
            target.unlink()
        elif target.exists():
            backup = target.with_name(f"{target.name}.bak")
            shutil.move(str(target), str(backup))

        target.symlink_to(link_value)
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
    if shutil.which("grok") or (_HOME / ".grok").is_dir():
        available.append("grok")
    return available


def _configure_claude(repo_root: Path, *, uninstall: bool) -> int:
    claude_home = _HOME / ".claude"
    statusline = claude_home / "study-statusline.sh"
    settings = claude_home / "settings.json"
    changed = 0

    if uninstall:
        if statusline.exists():
            statusline.unlink()
            changed += 1
        return changed

    claude_home.mkdir(parents=True, exist_ok=True)
    shutil.copy2(repo_root / "agents/claude/study-statusline.sh", statusline)
    statusline.chmod(0o755)
    changed += 1
    if not settings.exists():
        shutil.copy2(repo_root / "agents/claude/settings.json", settings)
        changed += 1
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
    # Skipped on uninstall so user-owned JSON is never destructively rewritten.
    if not uninstall:
        for tool, count in install_session_db_mandate(repo_root, tools=selected).items():
            summary[tool] = summary.get(tool, 0) + count
        if "claude" in selected:
            summary["claude"] = summary.get("claude", 0) + install_claude_stop_hook()
        if "codex" in selected:
            summary["codex"] = summary.get("codex", 0) + install_codex_session_end_hook()
        for tool, count in register_mcp_servers(selected).items():
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
    "register_mcp_servers",
    "require_repo_root",
]
