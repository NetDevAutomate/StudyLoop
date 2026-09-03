"""Guard tests for M0 item 0.8: docs must not run ahead of the code.

This is the second of the two recurring failure modes the M0 remediation
lanes exist to turn into a red gate (the other is lane collisions,
test_lane_ownership.py): a doc page or a `--help` string describes a command
or a config key that the real code doesn't actually accept, nobody notices
because docs aren't executed, and a learner following the docs hits a
traceback. Two independent checks, both fast, no network, no subprocess:

(a) ``test_studyloop_example_resolves`` + ``test_session_query_since_examples``
    -- every ``studyloop ...`` example in a fenced code block of
    docs/cli-reference.md, and every ``studyloop ...`` line inside a Click
    command's ``Examples:`` docstring section, is resolved against the real
    Click command tree rooted at the ``studyloop`` entry point (read from
    packages/studyloop/pyproject.toml's ``[project.scripts]``, not
    hardcoded). Every ``--option``/``-o`` token encountered must be a
    declared parameter of whatever command the walk has resolved to at that
    point (this *is* the "group options precede the subcommand" rule: once
    a token has resolved into a subcommand, ``current`` becomes that
    subcommand and no earlier ancestor's options are consulted again).
    Positional arguments are not otherwise validated.

    ``docs/cli-reference.md`` also documents ``agent-session-tools``'
    own CLI (``session-query`` et al) on the same page, under a `##
    agent-session-tools` heading -- a genuinely different command tree
    (argparse-based, a separate `[project.scripts]` entry in
    packages/agent-session-tools/pyproject.toml) that a Click-tree walk
    can't resolve. ``test_session_query_since_examples`` instead calls the
    real date-parsing function the CLI uses for `--since` directly. This is
    where R-61 lived (docs said ``--since 7d``, which
    ``agent_session_tools.query_utils.parse_date`` rejects) until both pages
    were corrected to ``--since last-7-days``.

(b) ``test_yaml_block_keys_are_known`` -- every fenced ```yaml block in
    docs/setup-guide.md and docs/cli-reference.md (docs/configuration.md
    does not exist, so it isn't scanned) is parsed and every top-level key
    checked against every config key some real loader in the codebase
    reads. See ``_known_top_level_keys`` for exactly which functions that
    is derived from and why it's more than just studyloop.settings.

One known-drift case the review found (R-31) is still pinned as
``pytest.mark.xfail(strict=True, ...)`` on the exact failing case, so this
suite is green today, and the moment it's fixed the xfail flips to an
unexpected pass -- which `strict=True` turns into a hard failure, forcing
whoever fixed it to also delete the marker. R-61's equivalent markers were
removed once the docs were corrected (the fix, not a marker deletion alone,
made ``test_session_query_since_examples`` pass honestly). Nothing else is
xfailed: any other drift this suite finds is a real, unmarked failure.
"""

from __future__ import annotations

import ast
import inspect
import re
import shlex
import sys
import tomllib
from importlib import import_module
from pathlib import Path
from typing import TYPE_CHECKING

import click
import pytest
import yaml

if TYPE_CHECKING:
    from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parents[3]
DOCS_DIR = REPO_ROOT / "docs"
STUDYLOOP_PYPROJECT = REPO_ROOT / "packages" / "studyloop" / "pyproject.toml"

_tests_dir = str(Path(__file__).parent)
if _tests_dir not in sys.path:
    sys.path.insert(0, _tests_dir)


# ---------------------------------------------------------------------------
# (a) shared extraction/validation helpers
# ---------------------------------------------------------------------------

_STUDYLOOP_LINE_RE = re.compile(r"^\s*\$?\s*studyloop\b")
_SESSION_QUERY_LINE_RE = re.compile(r"^\s*\$?\s*session-query\b")


_SHELL_OPERATORS = frozenset({"|", "||", ">", ">>", "&&", ";", "&", "<"})


def _cut_at_shell_metachar(line: str) -> str:
    """Cut a doc example at the first UNQUOTED shell pipe/redirect/chain operator.

    Tokenises with ``shlex`` in punctuation mode so ``studyloop x --msg "a | b"``
    keeps its quoted argument intact while ``studyloop x | head`` is cut before
    the pipe. The earlier regex cut at the first metacharacter anywhere in the
    line, which false-flagged valid quoted arguments (M0 council finding A4,
    openai.gpt-5.6-sol). Trailing ``# comments`` are dropped here too, so a
    parenthesised ``(-r)`` inside a comment is never mistaken for an option.

    Returns a string (re-joined with ``shlex.join``) so the caller's tokenizer
    is unchanged; on a tokenisation error the original line is returned and
    the caller reports the error.
    """
    # shlex's default commenters ("#") drop a trailing `# comment (-r)` here,
    # exactly as the caller's ``comments=True`` would; a quoted "#" survives.
    lexer = shlex.shlex(line, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    try:
        tokens = list(lexer)
    except ValueError:
        return line
    kept: list[str] = []
    for token in tokens:
        if token in _SHELL_OPERATORS or (token and set(token) <= set("|>&;<")):
            break
        kept.append(token)
    return shlex.join(kept)


def _iter_fenced_lines(doc_path: Path, pattern: re.Pattern[str]) -> list[tuple[int, str]]:
    """Every line matching *pattern* inside a fenced code block of *doc_path*.

    Backslash line-continuations are joined into one logical example so a
    multi-line ``studyloop plan new --title X \\`` invocation is validated
    as a whole.
    """
    lines = doc_path.read_text().splitlines()
    results: list[tuple[int, str]] = []
    in_fence = False
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        if line.strip().startswith("```"):
            in_fence = not in_fence
            i += 1
            continue
        if in_fence and pattern.match(line):
            start_no = i + 1
            joined = line
            while joined.rstrip().endswith("\\") and i + 1 < n:
                i += 1
                joined = joined.rstrip()[:-1] + " " + lines[i].strip()
            results.append((start_no, joined.strip()))
        i += 1
    return results


def _load_cli_group() -> click.Group:
    """Import the real Click group behind the ``studyloop`` command.

    Reads the entry point from ``[project.scripts]`` rather than hardcoding
    ``studyloop.cli:cli`` -- if the entry point ever moves, this test should
    follow it instead of silently importing a stale module.
    """
    data = tomllib.loads(STUDYLOOP_PYPROJECT.read_text())
    target = data["project"]["scripts"]["studyloop"]
    module_name, attr_name = target.split(":", 1)
    module = import_module(module_name)
    group = getattr(module, attr_name)
    assert isinstance(group, click.Group), f"{target} is not a click.Group"
    return group


def _find_line_no(source_lines: list[str], text: str, start: int) -> int:
    """1-based line number of the first exact match at or after *start*."""
    for offset, source_line in enumerate(source_lines[start:], start=start):
        if source_line.strip() == text:
            return offset + 1
    return -1


def _iter_click_examples(
    root: click.Group, ctx: click.Context, prefix: str = ""
) -> list[tuple[str, str]]:
    """Every ``studyloop ...`` line in an ``Examples:`` docstring section,
    walked recursively from *root*. Returns (location, example_text) with
    location formatted as ``<source file>:<line>`` when it can be found."""
    results: list[tuple[str, str]] = []
    for name in sorted(root.list_commands(ctx)):
        cmd = root.get_command(ctx, name)
        if cmd is None:
            continue
        loc_name = f"{prefix}{name}" if prefix else name
        help_text = cmd.help or ""
        if "Examples:" in help_text:
            after = help_text.split("Examples:", 1)[1]
            callback = getattr(cmd, "callback", None)
            source_file = None
            start_line = 0
            if callback is not None:
                try:
                    source_file = inspect.getsourcefile(callback)
                    start_line = inspect.getsourcelines(callback)[1] - 1
                except (TypeError, OSError):
                    source_file = None
            source_lines = Path(source_file).read_text().splitlines() if source_file else []
            for raw_line in after.splitlines():
                stripped = raw_line.strip()
                if _STUDYLOOP_LINE_RE.match(stripped):
                    if source_file:
                        line_no = _find_line_no(source_lines, stripped, start_line)
                        location = f"{Path(source_file).name}:{line_no}"
                    else:
                        location = loc_name
                    results.append((location, stripped))
        if isinstance(cmd, click.Group):
            sub_ctx = click.Context(cmd, parent=ctx, info_name=name)
            results.extend(_iter_click_examples(cmd, sub_ctx, prefix=f"{loc_name} "))
    return results


def _strip_option_value(token: str) -> str:
    if token.startswith("-") and "=" in token:
        return token.split("=", 1)[0]
    return token


def _declared_option_strings(cmd: click.Command) -> set[str]:
    opts: set[str] = {"--help"}
    for param in cmd.params:
        if isinstance(param, click.Option):
            opts.update(param.opts)
            opts.update(param.secondary_opts)
    return opts


def _validate_example(example: str, root: click.Group, root_ctx: click.Context) -> list[str]:
    """Return a list of problems (empty means the example resolves cleanly)."""
    cut = _cut_at_shell_metachar(example)
    try:
        tokens = shlex.split(cut, comments=True)
    except ValueError as exc:
        return [f"could not tokenize example: {exc}"]
    if not tokens or tokens[0] != "studyloop":
        return []  # nothing left to validate after cutting at a shell operator

    problems: list[str] = []
    current: click.Command = root
    current_ctx = root_ctx
    still_descending = True
    for token in tokens[1:]:
        if token.startswith("-"):
            opt = _strip_option_value(token)
            if opt not in _declared_option_strings(current):
                problems.append(
                    f"{opt!r} is not a declared option of resolved command {current.name!r}"
                )
        elif still_descending and isinstance(current, click.Group):
            sub = current.get_command(current_ctx, token)
            if sub is not None:
                current_ctx = click.Context(sub, parent=current_ctx, info_name=token)
                current = sub
                continue
            still_descending = False
        # else: positional argument, not validated beyond this point.
    return problems


def _build_studyloop_cases() -> list[tuple[str, str]]:
    doc_cases = [
        (f"cli-reference.md:{line_no}", text)
        for line_no, text in _iter_fenced_lines(DOCS_DIR / "cli-reference.md", _STUDYLOOP_LINE_RE)
    ]
    root = _load_cli_group()
    ctx = click.Context(root, info_name="studyloop")
    click_cases = _iter_click_examples(root, ctx)
    return doc_cases + click_cases


# Exact (location, example) signatures the review already found and filed as
# R-31: `studyloop backlog`'s `list`/`add` help text tells users to run
# `studyloop topics ...` -- a different, real top-level command (the `topics`
# lazy_subcommand routes to _sync.py, not _topics.py's group, which is
# mounted at `backlog`). See cli/_topics.py:34,36,38,101,103,132 and
# cli/__init__.py:63. Only the four examples that actually carry an
# `--option` get caught here -- the two bare `studyloop topics list` /
# `studyloop topics resolve 42` lines have nothing to validate beyond
# positional count, which this test deliberately doesn't check.
_R31_XFAIL_EXAMPLES = {
    'studyloop topics add "Python decorators" --tech Python',
    'studyloop topics add "Window functions" --tech SQL --note "Need for analytics work"',
    "studyloop topics list --tech Python",
    "studyloop topics list --source struggled",
}


def _studyloop_example_params() -> list:
    params = []
    for location, example in _build_studyloop_cases():
        if example in _R31_XFAIL_EXAMPLES:
            marks = pytest.mark.xfail(
                strict=True,
                reason=(
                    "R-31: cli/_topics.py's Examples: docstrings say "
                    "'studyloop topics ...' but that group is mounted at "
                    "'studyloop backlog' -- 'topics' is a different real "
                    "command (_sync.py). Fix is in cli/_topics.py, owned by "
                    "another lane; remove this marker when it's renamed."
                ),
            )
            params.append(pytest.param(location, example, marks=marks, id=location))
        else:
            params.append(pytest.param(location, example, id=location))
    return params


@pytest.mark.parametrize(("location", "example"), _studyloop_example_params())
def test_studyloop_example_resolves(location: str, example: str) -> None:
    root = _load_cli_group()
    ctx = click.Context(root, info_name="studyloop")
    problems = _validate_example(example, root, ctx)
    assert not problems, f"{location}: {example!r} -> {problems}"


# ---------------------------------------------------------------------------
# (a) extension: agent-session-tools' `session-query --since` (R-61)
# ---------------------------------------------------------------------------

_SINCE_VALUE_RE = re.compile(r"--since[= ]+(\S+)")


def _build_session_query_since_cases() -> list[tuple[str, str, str]]:
    """(location, example, since_value) for every session-query example that
    passes a --since value, across both docs pages that cite it."""
    cases = []
    for doc_name in ("setup-guide.md", "cli-reference.md"):
        for line_no, text in _iter_fenced_lines(DOCS_DIR / doc_name, _SESSION_QUERY_LINE_RE):
            match = _SINCE_VALUE_RE.search(text)
            if match:
                cases.append((f"{doc_name}:{line_no}", text, match.group(1)))
    return cases


def _session_query_since_params() -> list:
    return [
        pytest.param(location, since_value, id=location)
        for location, _example, since_value in _build_session_query_since_cases()
    ]


@pytest.mark.parametrize(("location", "since_value"), _session_query_since_params())
def test_session_query_since_examples(location: str, since_value: str) -> None:
    from agent_session_tools.query_utils import parse_date

    try:
        parse_date(since_value)
    except ValueError as exc:
        pytest.fail(f"{location}: --since {since_value!r} is rejected by parse_date: {exc}")


# ---------------------------------------------------------------------------
# (b) YAML keys in docs must be real settings
# ---------------------------------------------------------------------------

_RAW_GET_RE = re.compile(r'\braw(?:_config)?\.get\(\s*["\']([a-zA-Z_][a-zA-Z0-9_]*)["\']')
_DATA_GET_RE = re.compile(r'\bdata\.get\(\s*["\']([a-zA-Z_][a-zA-Z0-9_]*)["\']')
_CONFIG_GET_RE = re.compile(r'\bconfig\.get\(\s*["\']([a-zA-Z_][a-zA-Z0-9_]*)["\']')


def _static_function_source(module: ModuleType, name: str) -> str:
    """Source of a module-level function, read statically from its file.

    Deliberately *not* ``inspect.getsource(module.the_function)``: this
    test suite's own conftest.py has an autouse fixture that
    ``monkeypatch.setattr``\\s ``studyloop.settings.load_settings`` to a
    thin state_dir-isolation wrapper for every single test (including this
    one) -- so by the time this module's test bodies run,
    ``studyloop.settings.load_settings`` the *live attribute* is that
    wrapper, and ``inspect.getsource`` on it returns the wrapper's three
    lines, not the real function. Parsing the module's file with ``ast``
    and pulling out the named top-level function by name sidesteps that
    entirely -- it reads what's on disk, not what a fixture swapped in.
    """
    source_file = inspect.getsourcefile(module)
    if source_file is None:
        raise LookupError(f"no source file for module {module.__name__}")
    source = Path(source_file).read_text()
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            segment = ast.get_source_segment(source, node)
            if segment is not None:
                return segment
    raise LookupError(f"no top-level function {name!r} in {module.__name__}")


def _known_top_level_keys() -> set[str]:
    """Every top-level ``config.yaml`` key some real loader in the codebase
    reads -- derived from source, not a guessed list.

    ``studyloop.settings._SCALAR_FIELDS`` is imported directly. The section
    names aren't collected in one constant anywhere, so they're extracted by
    regex from the *specific* functions found by
    `grep -rn "load_raw_config()" packages/studyloop/src/studyloop`: that
    turned up settings.py (load_settings, resolve_study_dirs, get_db_path),
    shared.py (_resolve_hosts), focus.py (get_focus), doctor/voice.py and
    learning/voice.py (both _tts_config), and cli/_review.py (resume, for
    the medication window). Extraction is scoped to each function's own
    source (not the whole module) and to the exact identifier each function
    uses for the top-level raw dict (``raw``/``raw_config``/``data``/
    ``config``) so a *nested* sub-dict's own ``.get("...")`` calls (e.g.
    ``agents.priority``) can't leak in as if they were top-level keys.

    ``agent_session_tools.config_loader.DEFAULT_CONFIG`` is imported
    directly too: that package reads database/thresholds/semantic_search/etc
    from the *same* shared config.yaml (see that module's own docstring for
    why studyloop.settings doesn't cover them -- the two packages are
    independently publishable and deliberately don't import each other's
    loaders).
    """
    import studyloop.cli._review as cli_review_mod
    import studyloop.doctor.voice as doctor_voice_mod
    import studyloop.focus as focus_mod
    import studyloop.learning.voice as learning_voice_mod
    import studyloop.settings as settings_mod
    import studyloop.shared as shared_mod
    from agent_session_tools.config_loader import DEFAULT_CONFIG

    keys: set[str] = {name for name, _coerce in settings_mod._SCALAR_FIELDS}
    keys.update(_RAW_GET_RE.findall(_static_function_source(settings_mod, "load_settings")))
    keys.update(_RAW_GET_RE.findall(_static_function_source(settings_mod, "resolve_study_dirs")))
    keys.update(_DATA_GET_RE.findall(_static_function_source(settings_mod, "get_db_path")))
    keys.update(_CONFIG_GET_RE.findall(_static_function_source(shared_mod, "_resolve_hosts")))
    keys.update(_RAW_GET_RE.findall(_static_function_source(focus_mod, "get_focus")))
    keys.update(_RAW_GET_RE.findall(_static_function_source(doctor_voice_mod, "_tts_config")))
    keys.update(_RAW_GET_RE.findall(_static_function_source(learning_voice_mod, "_tts_config")))
    keys.update(_RAW_GET_RE.findall(_static_function_source(cli_review_mod, "resume")))
    keys.update(DEFAULT_CONFIG.keys())
    return keys


def _iter_yaml_blocks(doc_path: Path) -> list[tuple[int, int, str]]:
    """(block_index, start_line, block_text) for every ```yaml fenced block."""
    lines = doc_path.read_text().splitlines()
    blocks: list[tuple[int, int, str]] = []
    in_block = False
    start = 0
    idx = 0
    for i, line in enumerate(lines, start=1):
        if line.strip() == "```yaml":
            in_block = True
            start = i + 1
        elif line.strip() == "```" and in_block:
            in_block = False
            blocks.append((idx, start, "\n".join(lines[start - 1 : i - 1])))
            idx += 1
    return blocks


def _yaml_block_params() -> list:
    params = []
    for doc_name in ("setup-guide.md", "cli-reference.md"):
        for idx, start_line, _text in _iter_yaml_blocks(DOCS_DIR / doc_name):
            location = f"{doc_name}:{start_line}"
            params.append(pytest.param(doc_name, idx, id=location))
    return params


#: Top-level keys that identify a fenced YAML block as something other than a
#: studyloop config.yaml example: an Ansible playbook (name/hosts/tasks), an
#: Obsidian note's frontmatter (type/id/created/tags), a GitHub workflow
#: (on/jobs), an mkdocs config (site_name). A block is skipped ONLY when one of
#: these is present. The earlier rule -- skip when no key overlaps a known key --
#: let a block whose every key was misspelled pass silently (M0 council finding
#: A5, openai.gpt-5.6-sol); now such a block fails with the unknown keys listed.
_NON_CONFIG_MARKER_KEYS: frozenset[str] = frozenset(
    {"name", "tasks", "type", "id", "created", "on", "jobs", "site_name"}
)

#: Keys that must ALWAYS be in the derived known-key set. The derivation reads
#: loader source statically and is tied to the identifiers those loaders use; a
#: refactor that renamed one (or the earlier monkeypatch-induced shrink recorded
#: in evidence/M0/0.8-doc-drift/01-drift-found.md) would otherwise only surface
#: when a doc happened to mention the lost key (M0 council finding A2,
#: deepseek-r1). Extend this list when a new section is added to config.yaml.
_SENTINEL_KNOWN_KEYS: frozenset[str] = frozenset({"web_port", "browser", "lan_password", "tts"})


def test_non_config_markers_never_overlap_real_config_keys() -> None:
    """A marker that is also a real key would silently skip real config blocks.

    `hosts` was in the first marker list and IS a studyloop key (shared.py
    `_resolve_hosts`); this test is what would have caught it.
    """
    overlap = _NON_CONFIG_MARKER_KEYS & _known_top_level_keys()
    assert not overlap, f"marker key(s) {sorted(overlap)} are real config keys; remove them"


def test_known_key_derivation_has_not_shrunk() -> None:
    known = _known_top_level_keys()
    missing = _SENTINEL_KNOWN_KEYS - known
    assert not missing, (
        f"known-key derivation lost {sorted(missing)}; a loader was probably refactored "
        f"(see _known_top_level_keys). Derived set: {sorted(known)}"
    )


@pytest.mark.parametrize(("doc_name", "block_index"), _yaml_block_params())
def test_yaml_block_keys_are_known(doc_name: str, block_index: int) -> None:
    _idx, start_line, text = _iter_yaml_blocks(DOCS_DIR / doc_name)[block_index]
    location = f"{doc_name}:{start_line}"

    try:
        parsed = yaml.safe_load(text)
    except yaml.YAMLError:
        pytest.skip(f"{location}: not parseable as a single YAML document (not config)")

    if not isinstance(parsed, dict):
        pytest.skip(f"{location}: top-level YAML is a {type(parsed).__name__}, not a mapping")

    known = _known_top_level_keys()
    top_level = set(parsed.keys())
    markers = top_level & _NON_CONFIG_MARKER_KEYS
    if markers:
        pytest.skip(
            f"{location}: top-level key(s) {sorted(markers)} mark this block as "
            "not a studyloop config.yaml example (playbook / frontmatter / workflow)"
        )

    unknown = top_level - known
    assert not unknown, (
        f"{location}: unknown top-level key(s) {sorted(unknown)} not in {sorted(known)}"
    )
