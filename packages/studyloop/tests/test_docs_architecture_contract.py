"""L6 remediation lane: architecture-overview doc-contract tests.

Council ruling A20's shape for this kind of test: compare SETS derived from
real code symbols against what a parser extracts from the doc, rather than
grepping for a hardcoded stale string or pinning line numbers. Six checks:

(a) W24 -- every ``packages/...`` path cited in a docs/architecture/*.md
    "Component -> file map" table must exist in ``git ls-files``. Catches
    ``web/routes/session.py`` and ``web/routes/content_gen.py``, both split
    into packages (commit 123b6d60) three months before current.md's own
    "last updated" banner.
(b) W25 -- no in-scope doc names "Stub" as a card-generator backend/adapter,
    derived by comparing the doc's Adapters-node class list against the real
    ``*Generator`` classes defined under ``content/generators/`` (``stub.py``
    was deleted in commit 80d24e48).
(c) Every relative Markdown link in docs/**/*.md (excluding receipts/
    handoffs/superpowers) resolves to a real file.
(d) SECURITY.md and CONTRIBUTING.md must not name a specific ``0.x.y`` release
    line as the only one receiving security fixes (W40).
(e) docs/tui-guide.md's timer note must describe the real, energy-adaptive
    poll interval and colour thresholds from studyloop.tui.sidebar /
    studyloop.logic.break_logic, not a stale fixed schedule (W43).
(f) obsidian.filename_template: since the code now reads it (wired into
    ``_make_filename``), docs/obsidian-export.md must document it (W37).
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
DOCS_DIR = REPO_ROOT / "docs"
ARCHITECTURE_DIR = DOCS_DIR / "architecture"

_EXCLUDED_LINK_DIR_MARKERS = ("receipts", "handoffs", "superpowers")


def _git_tracked_files() -> set[str]:
    output = subprocess.run(
        ["git", "ls-files"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    ).stdout
    return set(output.splitlines())


# ---------------------------------------------------------------------------
# (a) W24 -- file-map paths must resolve
# ---------------------------------------------------------------------------

_HEADING_RE = re.compile(r"^(#+)\s*(.+?)\s*$")
_BACKTICK_PACKAGES_PATH_RE = re.compile(r"`(packages/[^`]+)`")


def _file_map_sections(md_path: Path) -> list[str]:
    """Every table line inside a "... file map ..." heading's section."""
    lines = md_path.read_text(encoding="utf-8").splitlines()
    table_lines: list[str] = []
    in_section = False
    section_level = 0
    for line in lines:
        heading_match = _HEADING_RE.match(line)
        if heading_match:
            level = len(heading_match.group(1))
            title = heading_match.group(2)
            if "file map" in title.lower():
                in_section = True
                section_level = level
                continue
            if in_section and level <= section_level:
                in_section = False
            continue
        if in_section and line.strip().startswith("|"):
            table_lines.append(line)
    return table_lines


def _expand_braces(path: str) -> list[str]:
    """Expand a single ``{a,b}`` alternation group into concrete paths.

    ``content/{schemas,storage}.py`` -> both ``content/schemas.py`` and
    ``content/storage.py``. Paths without a brace group are returned as-is.
    """
    brace_match = re.search(r"\{([^{}]+)\}", path)
    if not brace_match:
        return [path]
    alternatives = brace_match.group(1).split(",")
    return [path[: brace_match.start()] + alt + path[brace_match.end() :] for alt in alternatives]


def _file_map_paths(md_path: Path) -> list[str]:
    paths: list[str] = []
    for line in _file_map_sections(md_path):
        for raw_path in _BACKTICK_PACKAGES_PATH_RE.findall(line):
            paths.extend(_expand_braces(raw_path))
    return paths


def _architecture_docs() -> list[Path]:
    return sorted(ARCHITECTURE_DIR.glob("*.md"))


def _file_map_path_cases() -> list[Any]:
    tracked = _git_tracked_files()
    cases = []
    for doc_path in _architecture_docs():
        for path in _file_map_paths(doc_path):
            location = f"{doc_path.relative_to(REPO_ROOT)}::{path}"
            cases.append(pytest.param(path, tracked, id=location))
    return cases


@pytest.mark.parametrize(("path", "tracked"), _file_map_path_cases())
def test_file_map_path_exists_in_repo(path: str, tracked: set[str]) -> None:
    assert path in tracked, f"{path!r} is cited in a file-map table but is not in git ls-files"


def test_file_map_path_cases_are_not_empty() -> None:
    """Sanity check the extraction actually found rows, not zero (a silently

    passing empty parametrize would hide a regex or heading-matching bug).
    """
    assert len(_file_map_path_cases()) > 10


# ---------------------------------------------------------------------------
# (b) W25 -- no doc names "Stub" as a card-generator backend
# ---------------------------------------------------------------------------

_GENERATORS_DIR = (
    REPO_ROOT / "packages" / "studyloop" / "src" / "studyloop" / "content" / "generators"
)
_CLASS_DEF_RE = re.compile(r"^class (\w+Generator)\b", re.MULTILINE)
_ADAPTERS_NODE_RE = re.compile(r'Adapters\["((?:[^"])*)"\]')
_GENERATOR_PARTICIPANT_RE = re.compile(r"participant Gen as Generator \(([^)]*)\)")


def _real_generator_classes() -> set[str]:
    """Every ``*Generator`` class actually defined under content/generators/,

    excluding ``__init__.py`` (the Protocol + factory) and ``_retry.py`` /
    ``provider_profiles.py`` (helpers, not adapter classes).
    """
    classes: set[str] = set()
    for py_file in _GENERATORS_DIR.glob("*.py"):
        if py_file.name in {"__init__.py", "_retry.py", "provider_profiles.py"}:
            continue
        classes.update(_CLASS_DEF_RE.findall(py_file.read_text(encoding="utf-8")))
    return classes


def test_real_generator_classes_sanity() -> None:
    """The extraction must find the classes we know exist -- an empty or

    trivially-wrong set would make the comparison test below vacuous.
    """
    classes = _real_generator_classes()
    assert classes == {
        "OllamaGenerator",
        "BedrockGenerator",
        "OpenAICompatGenerator",
        "AnthropicCompatGenerator",
    }


def test_current_md_adapters_node_matches_real_generator_classes() -> None:
    current_md = ARCHITECTURE_DIR / "current.md"
    match = _ADAPTERS_NODE_RE.search(current_md.read_text(encoding="utf-8"))
    assert match, "could not find the Adapters[...] mermaid node in current.md"
    doc_classes = {token for token in match.group(1).split("<br/>") if token.endswith("Generator")}
    assert doc_classes == _real_generator_classes()


def test_current_md_generator_sequence_participant_names_no_stub() -> None:
    current_md = ARCHITECTURE_DIR / "current.md"
    match = _GENERATOR_PARTICIPANT_RE.search(current_md.read_text(encoding="utf-8"))
    assert match, "could not find the 'participant Gen as Generator (...)' line"
    tokens = {token.strip() for token in match.group(1).split("/")}
    assert "Stub" not in tokens


def test_system_overview_generator_nodes_name_no_stub() -> None:
    system_overview = DOCS_DIR / "system-overview.md"
    text = system_overview.read_text(encoding="utf-8")
    for node_name in ("Generator", "Backend"):
        node_match = re.search(rf'{node_name}\["((?:[^"])*)"\]', text)
        assert node_match, f"could not find the {node_name}[...] mermaid node"
        tokens = {
            token.strip()
            for segment in node_match.group(1).split("<br/>")
            for token in segment.split("/")
        }
        assert "Stub" not in tokens, f"{node_name}[...] still names Stub: {node_match.group(1)!r}"


# ---------------------------------------------------------------------------
# (c) relative Markdown links must resolve
# ---------------------------------------------------------------------------

_LINK_RE = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")

#: This lane (L6-architecture-release) owns exactly these doc pages -- see
#: lanes.json's "files" list. Scoped here rather than a full docs/**/*.md
#: rglob so this test doesn't fail on pre-existing breakage in pages no lane
#: in the 2026-09-14 congruence review claims (e.g. docs/topic-exercises.md's
#: dead link to a docs/ci.md that has never existed): fixing those is a
#: decision for whichever lane owns that page, not a side effect of this
#: one. Every page below is still checked against the full docs/ tree when
#: resolving link *targets* -- only the set of pages whose *outgoing* links
#: get asserted is restricted.
_LANE_OWNED_DOCS = (
    "docs/adr/README.md",
    "docs/architecture/current.md",
    "docs/obsidian-export.md",
    "docs/roadmap.md",
    "docs/setup-guide.md",
    "docs/system-overview.md",
    "docs/troubleshooting.md",
    "docs/tui-guide.md",
    "docs/voice-output.md",
    "docs/web-ui-guide.md",
)


def _is_excluded(md_path: Path) -> bool:
    parts = md_path.relative_to(DOCS_DIR).parts
    return any(marker in parts for marker in _EXCLUDED_LINK_DIR_MARKERS)


def _in_scope_docs() -> list[Path]:
    docs = [REPO_ROOT / rel for rel in _LANE_OWNED_DOCS]
    return sorted(p for p in docs if not _is_excluded(p))


def _relative_link_targets(md_path: Path) -> list[str]:
    text = md_path.read_text(encoding="utf-8")
    # Fenced code blocks (```...```) commonly contain literal `[text](url)`
    # examples (dataview queries, JSON, shell) that are not real doc links.
    text_without_fences = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
    targets = []
    for target in _LINK_RE.findall(text_without_fences):
        if target.startswith(("http://", "https://", "mailto:", "#")):
            continue
        targets.append(target)
    return targets


def _resolve_link(md_path: Path, target: str) -> Path:
    path_part = target.split("#", 1)[0]
    return (md_path.parent / path_part).resolve()


def _relative_link_cases() -> list[Any]:
    cases = []
    for doc_path in _in_scope_docs():
        for target in _relative_link_targets(doc_path):
            location = f"{doc_path.relative_to(REPO_ROOT)} -> {target}"
            cases.append(pytest.param(doc_path, target, id=location))
    return cases


@pytest.mark.parametrize(("doc_path", "target"), _relative_link_cases())
def test_relative_markdown_link_resolves(doc_path: Path, target: str) -> None:
    resolved = _resolve_link(doc_path, target)
    assert resolved.exists(), f"{doc_path.relative_to(REPO_ROOT)} links to {target!r} -> {resolved}"


def test_relative_link_cases_are_not_empty() -> None:
    assert len(_relative_link_cases()) > 20


# ---------------------------------------------------------------------------
# (d) W40 -- no doc names one specific 0.x.y line as the only supported one
# ---------------------------------------------------------------------------

_VERSION_LINE_RE = re.compile(r"\b0\.\d+\.x\b")


@pytest.mark.parametrize("doc_name", ["SECURITY.md", "CONTRIBUTING.md"])
def test_no_hardcoded_version_line(doc_name: str) -> None:
    text = (REPO_ROOT / doc_name).read_text(encoding="utf-8")
    matches = _VERSION_LINE_RE.findall(text)
    assert not matches, f"{doc_name} still names a specific release line: {matches}"


# ---------------------------------------------------------------------------
# (e) W43 -- tui-guide.md's timer note matches sidebar.py / break_logic.py
# ---------------------------------------------------------------------------


def test_tui_guide_poll_interval_matches_sidebar_sleep_constant() -> None:
    import ast
    import inspect

    from studyloop.tui import sidebar as sidebar_mod

    source_file = inspect.getsourcefile(sidebar_mod)
    assert source_file is not None
    tree = ast.parse(Path(source_file).read_text(encoding="utf-8"))
    sleep_seconds: int | None = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_poll_ipc_files":
            for call in ast.walk(node):
                if (
                    isinstance(call, ast.Call)
                    and isinstance(call.func, ast.Attribute)
                    and call.func.attr == "sleep"
                    and call.args
                    and isinstance(call.args[0], ast.Constant)
                    and isinstance(call.args[0].value, int)
                ):
                    sleep_seconds = call.args[0].value
    assert sleep_seconds is not None, "could not find the sleep() call in _poll_ipc_files"

    tui_guide = DOCS_DIR / "tui-guide.md"
    poll_line = next(
        line
        for line in tui_guide.read_text(encoding="utf-8").splitlines()
        if "polls these files every" in line
    )
    number_words: dict[int, str] = {1: "one", 2: "two", 3: "three"}
    expected_word = number_words.get(sleep_seconds, str(sleep_seconds))
    assert expected_word in poll_line.lower(), (
        f"doc says {poll_line!r}, sidebar.py polls every {sleep_seconds} second(s)"
    )


def test_tui_guide_timer_note_matches_break_thresholds_at_medium_band() -> None:
    from studyloop.logic.break_logic import THRESHOLDS

    tui_guide = DOCS_DIR / "tui-guide.md"
    text = tui_guide.read_text(encoding="utf-8")
    timer_sentence = next(
        line for line in text.splitlines() if "timer" in line.lower() and "20 minutes" in line
    )
    medium = THRESHOLDS["medium"]
    assert f"{medium.micro} minutes" in timer_sentence
    assert f"{medium.short} minutes" in timer_sentence


# ---------------------------------------------------------------------------
# (f) W37 -- obsidian.filename_template: code reads it, so docs must too
# ---------------------------------------------------------------------------


def test_filename_template_documented_iff_code_reads_it() -> None:
    """The dead-key policy (W07/W14/W37): a config key with no functional

    effect should not appear in docs (nothing to document); a key the code
    actually reads must be documented. ``_make_filename`` now threads
    ``obsidian.filename_template`` through every call site (see
    test_obsidian_writer.py), so it must appear in docs/obsidian-export.md.
    """
    import inspect

    from agent_session_tools import obsidian_writer

    source_file = inspect.getsourcefile(obsidian_writer)
    assert source_file is not None
    source = Path(source_file).read_text(encoding="utf-8")
    code_reads_it = "filename_template" in source

    obsidian_export_doc = DOCS_DIR / "obsidian-export.md"
    doc_mentions_it = "filename_template" in obsidian_export_doc.read_text(encoding="utf-8")

    assert code_reads_it, "obsidian_writer.py no longer reads filename_template at all"
    assert doc_mentions_it, (
        "obsidian.filename_template is read by _make_filename() but "
        "docs/obsidian-export.md never mentions it"
    )


# ---------------------------------------------------------------------------
# (g) W38 -- an ADR's own ``**Status:**`` header and its row in the
# docs/adr/README.md index must agree on the status word. ADR-0009 said
# "Accepted" in its file while the index said "Proposed" and nothing caught it;
# ``validate_adr_statuses()`` compares an ADR against release tags, not against
# the index. ADRs 0001-0007 predate the Status header and are skipped.
# ---------------------------------------------------------------------------

_ADR_STATUS_WORDS = ("Accepted", "Proposed", "Superseded", "Deprecated")
_ADR_INDEX_ROW = re.compile(r"^\|\s*\[(\d{4})\]\([^)]+\)\s*\|[^|]*\|\s*([^|]+?)\s*\|")
_ADR_STATUS_HEADER = re.compile(r"^\*\*Status:\*\*\s*([A-Za-z]+)")


def _adr_index_statuses(adr_dir: Path) -> dict[str, str]:
    rows: dict[str, str] = {}
    for line in (adr_dir / "README.md").read_text(encoding="utf-8").splitlines():
        match = _ADR_INDEX_ROW.match(line)
        if match:
            rows[match.group(1)] = match.group(2).split()[0]
    assert rows, "no ADR index rows parsed from docs/adr/README.md"
    return rows


def _adr_file_statuses(adr_dir: Path) -> dict[str, str]:
    statuses: dict[str, str] = {}
    for path in sorted(adr_dir.glob("[0-9][0-9][0-9][0-9]-*.md")):
        for line in path.read_text(encoding="utf-8").splitlines():
            match = _ADR_STATUS_HEADER.match(line.strip())
            if match:
                statuses[path.name[:4]] = match.group(1)
                break
    return statuses


def _adr_status_mismatches(adr_dir: Path) -> list[str]:
    index = _adr_index_statuses(adr_dir)
    files = _adr_file_statuses(adr_dir)
    problems: list[str] = []
    for number, file_status in files.items():
        assert file_status in _ADR_STATUS_WORDS, f"ADR-{number}: unexpected status {file_status!r}"
        index_status = index.get(number)
        if index_status is None:
            problems.append(f"ADR-{number} has no row in docs/adr/README.md")
        elif index_status != file_status:
            problems.append(f"ADR-{number}: file says {file_status}, index says {index_status}")
    return problems


def test_adr_status_headers_agree_with_the_readme_index() -> None:
    assert _adr_status_mismatches(DOCS_DIR / "adr") == []


def test_adr_status_checker_detects_a_drifted_index_row(tmp_path: Path) -> None:
    """Positive control: the checker must actually fire on the ADR-0009 class of
    drift, otherwise the green test above proves nothing."""
    adr_dir = tmp_path / "adr"
    adr_dir.mkdir()
    (adr_dir / "0042-example.md").write_text("# ADR-0042\n\n**Status:** Accepted, 2026-09-14.\n")
    (adr_dir / "README.md").write_text(
        "| ADR | Title | Status | Change |\n|---|---|---|---|\n"
        "| [0042](0042-example.md) | Example | Proposed | `x` |\n"
    )
    assert _adr_status_mismatches(adr_dir) == ["ADR-0042: file says Accepted, index says Proposed"]
