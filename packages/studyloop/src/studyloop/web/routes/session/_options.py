"""GET /session/options and picker data builders."""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any

from fastapi import Request  # noqa: TC002 - FastAPI needs Request at runtime for injection.

from studyloop.settings import MAX_ACTIVE_TOPICS
from studyloop.web.routes.session._models import SessionOption
from studyloop.web.routes.session._router import router
from studyloop.web.services.session_start import ACP_CAPABLE_AGENTS

_SESSION_OPTION_INDEX_VERSION = 3
_SESSION_OPTION_INDEX_LOCK = threading.Lock()
_OUTPUT_DIR_NAMES = {"flashcards", "quizzes"}
_AGENT_FALLBACK_BINARIES = {
    "claude": "claude",
    "codex": "codex",
    "gemini": "gemini",
    "grok": "grok",
    "kiro": "kiro-cli",
    "opencode": "opencode",
}


@router.get("/session/options")
def get_session_options(request: Request, refresh: bool = False) -> dict[str, Any]:
    """Return local study choices for the web session picker."""
    targets = _get_indexed_target_options(request.app.state, force=refresh)
    dev_mode = bool(getattr(request.app.state, "dev_mode", False))
    return {
        **targets,
        "agents": _agent_options(dev_mode=dev_mode),
        "terminal_engine": _terminal_engine_option(request.app.state),
    }


def _terminal_engine_option(state: Any) -> dict[str, Any]:
    """Describe the renderer actually mounted for this app instance.

    Delegates to ``studyloop.web.dev_engines.describe_terminal_engine`` — the
    single source of truth for the renderer axis (xterm.js vs the ``--dev``
    engine), as opposed to the session transport axis (pty/acp/ttyd).
    """
    from studyloop.web.dev_engines import describe_terminal_engine

    dev_mode = bool(getattr(state, "dev_mode", False))
    dev_engine = getattr(state, "dev_engine", None)
    return describe_terminal_engine(dev_mode, dev_engine)


def warm_session_options_index(app: object) -> None:
    """Pre-index the filesystem-backed picker options in the background."""

    def _warm() -> None:
        try:
            state = getattr(app, "state", app)
            _get_indexed_target_options(state)
        except Exception:
            return

    thread = threading.Thread(target=_warm, name="studyloop-session-options-index", daemon=True)
    thread.start()


def _get_indexed_target_options(
    state: Any | None = None, *, force: bool = False
) -> dict[str, list[dict[str, Any]]]:
    """Return topic/vendor/course/lesson options from memory, disk, or a fresh scan."""
    fingerprint = _target_fingerprint()

    if not force and state is not None:
        cached = getattr(state, "session_options_targets_cache", None)
        cached_fingerprint = getattr(state, "session_options_targets_fingerprint", None)
        if cached is not None and cached_fingerprint == fingerprint:
            return cached

    with _SESSION_OPTION_INDEX_LOCK:
        if not force and state is not None:
            cached = getattr(state, "session_options_targets_cache", None)
            cached_fingerprint = getattr(state, "session_options_targets_fingerprint", None)
            if cached is not None and cached_fingerprint == fingerprint:
                return cached

        if not force:
            disk_targets = _read_target_index(fingerprint)
            if disk_targets is not None:
                if state is not None:
                    state.session_options_targets_cache = disk_targets
                    state.session_options_targets_fingerprint = fingerprint
                return disk_targets

        targets = _target_options_snapshot()
        _write_target_index(fingerprint, targets)
        if state is not None:
            state.session_options_targets_cache = targets
            state.session_options_targets_fingerprint = fingerprint
        return targets


def _target_options_snapshot() -> dict[str, list[dict[str, Any]]]:
    """Build the filesystem-backed part of the session picker."""
    return {
        "session_types": [
            {"label": "Study Session", "value": "study", "kind": "session_type"},
            # Body Double is a first-class top-level view with its own agent
            # picker, not a Study Session "session type" (body-double-own-agent-
            # picker, tasks §5.3). The session_types key itself stays — MCP's
            # list_session_options publishes it and test_mcp_session_parity.py
            # asserts its presence.
        ],
        "topics": [option.model_dump() for option in _topic_options()],
        "vendors": [option.model_dump() for option in _vendor_options()],
        "courses": [option.model_dump() for option in _course_options()],
        "lessons": [option.model_dump() for option in _lesson_options()],
    }


def _target_fingerprint() -> dict[str, Any]:
    """Cheap fingerprint for picker inputs so runtime re-indexes are fast.

    Includes the resolved root list (whether or not each path exists) so that
    an empty scan under root set A never validates a cache built from root set B.
    """
    roots = [*_study_roots(), *_courses_roots()]
    # Include root list as absolute strings — even absent roots must be part
    # of the identity so different root sets always produce different fingerprints.
    root_strings = [str(Path(r).expanduser().resolve()) for r in roots]

    records: list[list[Any]] = []
    for root in roots:
        _record_dir(records, root, depth=0)
        for vendor_dir in _visible_child_dirs(root):
            _record_dir(records, vendor_dir, depth=1)
            for course_dir in _visible_child_dirs(vendor_dir):
                _record_dir(records, course_dir, depth=2)
                for lesson_dir in _visible_child_dirs(course_dir):
                    _record_dir(records, lesson_dir, depth=3)

    config_record: list[Any] = []
    try:
        from studyloop.settings import get_config_path

        config_path = get_config_path()
        config_stat = config_path.stat()
        config_record = [str(config_path), config_stat.st_mtime_ns, config_stat.st_size]
    except OSError:
        config_record = []

    records.sort()
    return {
        "version": _SESSION_OPTION_INDEX_VERSION,
        "config": config_record,
        "roots": root_strings,
        "record_count": len(records),
        "records": records,
    }


def _record_dir(records: list[list[Any]], path: Path, *, depth: int) -> None:
    try:
        stat = path.stat()
        resolved = path.resolve()
    except OSError:
        return
    records.append([depth, str(resolved), stat.st_mtime_ns, stat.st_ino, stat.st_dev])


def _visible_child_dirs(parent: Path) -> list[Path]:
    try:
        children = sorted(parent.iterdir(), key=lambda p: p.name.lower())
    except OSError:
        return []
    return [
        child
        for child in children
        if child.is_dir() and not child.name.startswith(".") and child.name not in _OUTPUT_DIR_NAMES
    ]


def _target_index_path() -> Path | None:
    try:
        from studyloop.settings import load_settings

        state_dir = load_settings().state_dir
        # Guard against a non-path state_dir (e.g. a MagicMock in tests): building
        # Path(str(mock)) and mkdir-ing it would create a stray "MagicMock/…" dir
        # on disk. Only proceed for real string/PathLike values.
        if not isinstance(state_dir, (str, Path)):
            return None
        path = Path(state_dir) / "session-options-index.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        return path
    except Exception:
        return None


def _read_target_index(fingerprint: dict[str, Any]) -> dict[str, list[dict[str, Any]]] | None:
    path = _target_index_path()
    if path is None or not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    if payload.get("version") != _SESSION_OPTION_INDEX_VERSION:
        return None
    if payload.get("fingerprint") != fingerprint:
        return None
    targets = payload.get("targets")
    if not isinstance(targets, dict):
        return None
    # Absolute-path invariant: reject any payload where an option has a
    # non-empty path that is not absolute. This catches poisoned caches
    # written by test runs with cwd-relative study roots.
    if _targets_contain_relative_paths(targets):
        return None
    return targets


def _write_target_index(
    fingerprint: dict[str, Any], targets: dict[str, list[dict[str, Any]]]
) -> None:
    path = _target_index_path()
    if path is None:
        return
    # Refuse to persist relative paths — a write-time guard so even if test
    # isolation regresses, a poisoned payload never reaches the user's state dir.
    if _targets_contain_relative_paths(targets):
        return
    payload = {
        "version": _SESSION_OPTION_INDEX_VERSION,
        "built_at": time.time(),
        "fingerprint": fingerprint,
        "targets": targets,
    }
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    try:
        tmp_path.write_text(json.dumps(payload, indent=2))
        tmp_path.replace(path)
    except OSError:
        return


def _targets_contain_relative_paths(targets: dict[str, list[dict[str, Any]]]) -> bool:
    """Return True if any option in *targets* has a non-empty relative path.

    This is a permanent tripwire: absolute paths are the only valid shape for
    persisted options. A relative path indicates the index was built from a
    working-directory-relative root (typically a test leak).
    """
    for options in targets.values():
        if not isinstance(options, list):
            continue
        for option in options:
            if not isinstance(option, dict):
                continue
            path_val = option.get("path", "")
            if path_val and not Path(path_val).is_absolute():
                return True
    return False


def _study_roots() -> list[Path]:
    candidates: list[Path] = []
    try:
        from studyloop.settings import load_settings

        settings = load_settings()
        candidates.extend(Path(path).expanduser() for path in settings.content.study_paths)
        candidates.extend(
            [
                settings.obsidian_base / "Personal" / "Study",
                settings.obsidian_base / "Personal" / "2-Areas" / "Study",
            ]
        )
        candidates.extend(topic.obsidian_path for topic in settings.topics)
    except Exception:
        candidates.extend(
            [
                Path("~/Obsidian/Personal/Study").expanduser(),
                Path("~/Obsidian/Personal/2-Areas/Study").expanduser(),
            ]
        )
    return _existing_unique_dirs(candidates)


def _topic_options() -> list[SessionOption]:
    options: list[SessionOption] = []
    try:
        from studyloop.settings import load_settings

        configured_topics = getattr(load_settings(), "topics", [])
        for topic in configured_topics[:MAX_ACTIVE_TOPICS]:
            options.append(
                SessionOption(
                    label=topic.name,
                    value=topic.slug,
                    kind="topic",
                    path=str(topic.obsidian_path),
                )
            )
        if options:
            return options
    except Exception:
        pass
    for root in _study_roots():
        if not root.exists():
            continue
        for child in sorted(root.iterdir(), key=lambda p: p.name.lower()):
            if child.is_dir() and not child.name.startswith("."):
                options.append(
                    SessionOption(
                        label=child.name.replace("_", " "),
                        value=child.name,
                        kind="topic",
                        path=str(child),
                    )
                )
                if len(options) >= MAX_ACTIVE_TOPICS:
                    return options
    return options


def _topic_dir_paths() -> set[Path]:
    """Resolved configured-topic note dirs — study targets, never course vendors."""
    try:
        from studyloop.settings import load_settings

        return {
            Path(topic.obsidian_path).expanduser().resolve()
            for topic in getattr(load_settings(), "topics", [])
        }
    except Exception:
        return set()


def _vendor_dirs() -> list[tuple[str, Path]]:
    """Every vendor directory across all course roots.

    Names may repeat when the same vendor exists under multiple roots
    (e.g. ``Study/Udemy`` and ``2-Areas/Study/Courses/Udemy``) — callers
    that render a picker dedupe by name, while course discovery walks all
    directories so no courses are lost. Configured topic dirs (Python,
    DevOps, …) live at the same level as vendors under a study root and
    are excluded: they are session *targets*, not content sources.
    """
    dirs: list[tuple[str, Path]] = []
    seen: set[Path] = set()
    topic_paths = _topic_dir_paths()
    for courses_root in _courses_roots():
        for vendor in _visible_child_dirs(courses_root):
            resolved = vendor.resolve()
            if resolved in seen or resolved in topic_paths:
                continue
            seen.add(resolved)
            dirs.append((vendor.name, vendor))
    return dirs


def _vendor_options() -> list[SessionOption]:
    vendors: list[SessionOption] = []
    seen_names: set[str] = set()
    for name, path in _vendor_dirs():
        if name in seen_names:
            continue
        seen_names.add(name)
        vendors.append(
            SessionOption(
                label=name.replace("_", " "),
                value=name,
                kind="vendor",
                path=str(path),
            )
        )
    return vendors


def _course_options() -> list[SessionOption]:
    courses: list[SessionOption] = []
    seen_values: set[str] = set()
    for vendor_name, vendor_path in _vendor_dirs():
        for course in _visible_child_dirs(vendor_path):
            value = f"{vendor_name}/{course.name}"
            if value in seen_values:
                continue
            seen_values.add(value)
            courses.append(
                SessionOption(
                    label=course.name.replace("_", " "),
                    value=value,
                    kind="course",
                    path=str(course),
                    parent=vendor_name,
                )
            )
    return courses


def _lesson_options() -> list[SessionOption]:
    lessons: list[SessionOption] = []
    for course in _course_options():
        for lesson in _visible_child_dirs(Path(course.path or "")):
            lessons.append(
                SessionOption(
                    label=lesson.name.replace("_", " "),
                    value=f"{course.value}/{lesson.name}",
                    kind="lesson",
                    path=str(lesson),
                    parent=course.value,
                )
            )
    return lessons


def _courses_roots() -> list[Path]:
    # Course vendors (ArjanCodes, CodeWithMosh, …) live directly under each
    # study root — the same level "Topic" targets scan. Requiring an
    # intermediate ``Courses/`` directory left the vendor picker empty
    # because the real vault has no such level.
    #
    # A ``Courses/`` subdirectory is still honoured when one exists, so a
    # vault that nests courses under it keeps working. To avoid surfacing
    # ``Courses`` itself as a bogus vendor in that case, a study root is
    # only used directly when it has no ``Courses/`` child.
    candidates: list[Path] = []
    for root in _study_roots():
        nested = root / "Courses"
        if nested.is_dir():
            candidates.append(nested)
        else:
            candidates.append(root)
    candidates.extend(
        [
            Path("~/Obsidian/Personal/Study/Courses").expanduser(),
            Path("~/Obsidian/Personal/2-Areas/Study/Courses").expanduser(),
        ]
    )
    return _existing_unique_dirs(candidates)


def _existing_unique_dirs(paths: list[Path]) -> list[Path]:
    roots: list[Path] = []
    seen: set[Path] = set()
    for path in paths:
        expanded = path.expanduser()
        if not expanded.exists() or not expanded.is_dir():
            continue
        resolved = expanded.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        roots.append(expanded)
    return roots


def _agent_options(*, dev_mode: bool = False) -> list[dict[str, object]]:
    """Describe installed agents, exposing experimental ACP only in dev mode."""
    names = ["claude", "codex", "gemini", "kiro", "opencode"]
    if dev_mode:
        # Grok Build remains implemented for future integration work, but it
        # is not a supported v1 study-session harness.
        names.append("grok")
    if os.environ.get("STUDYLOOP_TEST_AGENT") == "1":
        # Harness-only: surface the deterministic fake agent in the picker so
        # browser e2e can drive the real UI spawn path (adapters/fake.py).
        names.append("fake")
    try:
        from studyloop.agent_launcher import AGENTS, detect_agents

        detected = set(detect_agents(include_experimental=dev_mode))
        return [
            {
                "label": _agent_label(name),
                "value": name,
                "available": name in detected,
                "supports_acp": dev_mode and name in ACP_CAPABLE_AGENTS,
                "acp_ready": False,
                "binary": adapter.binary,
            }
            for name, adapter in AGENTS.items()
            if name in names
        ]
    except Exception:
        return [
            {
                "label": _agent_label(name),
                "value": name,
                "available": False,
                "supports_acp": dev_mode and name in ACP_CAPABLE_AGENTS,
                "acp_ready": False,
                "binary": _AGENT_FALLBACK_BINARIES.get(name, name),
            }
            for name in names
        ]


def _agent_label(name: str) -> str:
    return {
        "claude": "Claude Code",
        "codex": "Codex",
        "gemini": "Gemini",
        "grok": "Grok",
        "kiro": "Kiro",
        "opencode": "OpenCode",
    }.get(name, name)
