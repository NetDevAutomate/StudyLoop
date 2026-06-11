"""GET /session/options and picker data builders."""

from __future__ import annotations

from pathlib import Path

from studyloop.web.routes.session._models import SessionOption
from studyloop.web.routes.session._router import router


@router.get("/session/options")
def get_session_options() -> dict[str, list[dict]]:
    """Return local study choices for the web session picker."""
    return {
        "session_types": [
            {"label": "Study Session", "value": "study", "kind": "session_type"},
            {"label": "Body Double", "value": "body_double", "kind": "session_type"},
        ],
        "topics": [option.model_dump() for option in _topic_options()],
        "vendors": [option.model_dump() for option in _vendor_options()],
        "courses": [option.model_dump() for option in _course_options()],
        "lessons": [option.model_dump() for option in _lesson_options()],
        "agents": _agent_options(),
    }


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
    return options


def _vendor_options() -> list[SessionOption]:
    vendors: list[SessionOption] = []
    seen: set[Path] = set()
    for courses_root in _courses_roots():
        for vendor in sorted(courses_root.iterdir(), key=lambda p: p.name.lower()):
            resolved = vendor.resolve()
            if resolved in seen or not vendor.is_dir() or vendor.name.startswith("."):
                continue
            seen.add(resolved)
            vendors.append(
                SessionOption(
                    label=vendor.name.replace("_", " "),
                    value=vendor.name,
                    kind="vendor",
                    path=str(vendor),
                )
            )
    return vendors


def _course_options() -> list[SessionOption]:
    courses: list[SessionOption] = []
    for vendor in _vendor_options():
        vendor_path = Path(vendor.path or "")
        if not vendor_path.exists():
            continue
        for course in sorted(vendor_path.iterdir(), key=lambda p: p.name.lower()):
            if course.is_dir() and not course.name.startswith("."):
                courses.append(
                    SessionOption(
                        label=course.name.replace("_", " "),
                        value=f"{vendor.value}/{course.name}",
                        kind="course",
                        path=str(course),
                        parent=vendor.value,
                    )
                )
    return courses


def _lesson_options() -> list[SessionOption]:
    lessons: list[SessionOption] = []
    for course in _course_options():
        course_path = Path(course.path or "")
        if not course_path.exists():
            continue
        for lesson in sorted(course_path.iterdir(), key=lambda p: p.name.lower()):
            if lesson.is_dir() and not lesson.name.startswith("."):
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


def _agent_options() -> list[dict[str, object]]:
    try:
        from studyloop.agent_launcher import AGENTS, detect_agents

        detected = set(detect_agents())
        return [
            {
                "label": _agent_label(name),
                "value": name,
                "available": name in detected,
                "supports_acp": name in {"kiro", "gemini"},
                "acp_ready": False,
                "recommended_transport": "ttyd",
                "binary": adapter.binary,
            }
            for name, adapter in AGENTS.items()
            if name in {"codex", "claude", "gemini", "kiro", "opencode"}
        ]
    except Exception:
        return []


def _agent_label(name: str) -> str:
    return {
        "claude": "Claude Code",
        "codex": "Codex",
        "gemini": "Gemini",
        "kiro": "Kiro",
        "opencode": "OpenCode",
    }.get(name, name)
