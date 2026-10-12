"""The twenty contributor-guide pages must stay true to the tree they describe.

The drift test of ``openspec/changes/contributor-guide-v1/design.md`` §6. ``GUIDE_PAGES``
is the §2 inventory, ``(stem, group, line_cap)``; every test is parameterised over it
(``-k contributor-cli`` runs one page) and ``_pins`` is the §2 "Pin" column. Default
tier, no network, nothing written outside ``tmp_path``. What each test proves:

C  ``test_fenced_command_resolves`` -- each fenced shell line (bash/sh/console/untagged
   fence; ``$``, ``env -u VIRTUAL_ENV`` and ``VAR=x`` prefixes stripped) that begins
   ``just <recipe>`` names a recipe parsed from the Justfile; each
   ``uv run --group dev pytest <path>`` path exists; each ``uv run studyloop ...`` line
   resolves against the real Click tree, with the resolver imported from
   ``test_docs_drift`` (bare ``studyloop ...`` lines are that module's own case via
   ``_STUDYLOOP_EXAMPLE_DOCS``). Exactly four forms are EXECUTED, by ``subprocess.run``
   under a ``tmp_path`` HOME/TMPDIR with exit 0 asserted: ``uv run studyloop --version``,
   ``uv run studyloop --help``, ``uv run studyloop doctor --help`` and
   ``git log -1 --format='%h %s' <F14 sha>``. Nothing else runs.
   ``test_backticked_repo_paths_exist`` -- a backticked token anchored at a top-level
   repo directory, with a file extension or trailing slash, is a repo path and must
   exist (``*`` globs need one match; ``:NN``/``::node`` suffixes dropped; ``<...>``,
   ``…`` and ``NNNN`` placeholders skipped).
H  ``test_structure`` -- one H1 on line 1; the first block after it (HTML comments
   skipped) is a paragraph of at most three sentences or a numbered list; at least one
   numbered list; at most ``line_cap`` lines; no ``<!-- GUIDE-STUB -->`` left.
L  ``test_links_resolve`` -- every ``[text](target)`` without a scheme resolves
   relative to the page and a ``#anchor`` is a heading slug of the target
   (python-markdown's toc slugify, what mkdocs renders). ``test_router_h2_set_is_f10``
   -- the router's H2 list equals F10.
M  ``test_module_pages_stay_proposals`` -- page 20 says "design stage" in its first
   paragraph, links ``module-contract-v1/proposal.md`` and never says "is available" /
   "install it" / "the index lists"; page 19 says "proposal" in its first paragraph;
   neither fences a ``studyloop module`` or ``studyloop drill`` line (K4).
F  ``test_facts_match_source`` -- every page, bites only on a mention: harness counts
   ("the six harnesses", "4 core + 2 preview", "<n> harnesses are") and tier lists
   written ``core: a, b`` / ``preview (a, b)`` against ``studyloop.harnesses``; ``-m``
   expressions use declared pyproject markers; branch names (``feat/slug`` in backticks
   on a line about branches, or the ``git switch -c`` / ``git checkout -b`` argument)
   use the F1 prefixes; backticked commit subjects use the §4.1 type set.
"""

from __future__ import annotations

import os
import re
import shlex
import subprocess
import sys
import tomllib
import unicodedata
from itertools import pairwise
from pathlib import Path

import click
import pytest
from test_docs_drift import _cut_at_shell_metachar, _load_cli_group, _validate_example

from studyloop.harnesses import CORE_HARNESSES, HARNESSES, PREVIEW_HARNESSES, RELEASE_HARNESSES

REPO_ROOT = Path(__file__).resolve().parents[3]
DOCS_DIR = REPO_ROOT / "docs"
JUSTFILE = REPO_ROOT / "Justfile"  # the git-tracked spelling; CI runs on a case-sensitive host
PYPROJECT = REPO_ROOT / "pyproject.toml"
STUB_MARKER = "<!-- GUIDE-STUB -->"

#: design.md §2 -- (stem, nav group, line cap). The router carries 15 anchors, hence 200.
GUIDE_PAGES: tuple[tuple[str, str, int], ...] = (
    ("contributing", "welcome", 200),
    ("contributor-environment", "welcome", 150),
    ("contributor-debugging", "welcome", 150),
    ("contributor-cli", "contribute", 150),
    ("contributor-web", "contribute", 150),
    ("contributor-mcp", "contribute", 150),
    ("contributor-doctor", "contribute", 150),
    ("contributor-harnesses-agents", "contribute", 150),
    ("contributor-content", "contribute", 150),
    ("contributor-documentation", "contribute", 150),
    ("contributor-testing", "testing", 220),  # pinned collected examples are code (design.md §6)
    ("acceptance-testing", "testing", 150),
    ("contributor-changelog", "process", 150),
    ("contributor-pull-requests", "process", 150),
    ("contributor-issues-prioritisation", "process", 150),
    ("contributor-ai", "process", 150),
    ("contributor-code-map", "reference", 150),
    ("contributor-conventions", "reference", 150),
    ("contributor-modules", "proposals", 150),
    ("contributor-module-index", "proposals", 150),
    # module-contract v1 (lane W5, the S3 page): the SHIPPED contract, so it takes the full
    # C/H/L pins -- its fenced `studyloop module` / `drill` commands resolve against the tree.
    ("module-contract", "reference", 150),
)

#: design.md §3 F10 -- the router's H2s in order; every one is an anchor other pages link to.
_ROUTER_H2 = [
    "Contents",
    "Development environment",
    "Your first contribution",
    "How the repository is organised",
    "Making changes",
    "Testing",
    "Continuous integration",
    "Documentation standards",
    "Changelog process",
    "Raising a pull request",
    "Submitting an issue",
    "How we prioritise",
    "AI usage, and models through a LiteLLM gateway",
    "Security",
    "FAQ",
]
#: design.md §3 F14 -- the only shas ``git log -1`` may be run for (K5: no fabricated history).
_F14_SHAS = frozenset(
    {"e659f8cf", "019624c3", "93f30789", "711459c1", "fa5d76be", "2883588f", "6b6a35bd", "8d31f1ec"}
)
_BRANCH_PREFIXES = ("feat", "fix", "docs", "test")  # F1; `lane/` is reserved, never on a page
_COMMIT_TYPES = ("feat", "fix", "docs", "test", "chore", "ci")  # §4.1, F13
_SHELL_LANGS = frozenset({"", "bash", "sh", "shell", "console", "zsh"})
_EXECUTED_STUDYLOOP = (("--version",), ("--help",), ("doctor", "--help"))
_FENCE_RE = re.compile(r"^\s*(?:`{3,}|~{3,})\s*([A-Za-z0-9_+-]*)")
_LINK_RE = re.compile(r"(?<!!)\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
_RECIPE_RE = re.compile(r"^@?([A-Za-z_][A-Za-z0-9_-]*)(?:\s[^:]*)?:(?!=)")
_ALIAS_RE = re.compile(r"^alias\s+([A-Za-z_][A-Za-z0-9_-]*)\s*:=")
_WORDS = ("zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten")
_N = rf"(\d+|{'|'.join(_WORDS[1:])})"
_COUNT_RES = (
    re.compile(rf"\b(?:the|all)\s+{_N}\s+(?:(core|preview)\s+)?(?:\w+\s+)?harnesses\b", re.I),
    re.compile(rf"\b{_N}\s+(?:(core|preview)\s+)?(?:\w+\s+)?harnesses\s+(?:are|is)\b", re.I),
)
_SPLIT_RE = re.compile(rf"\b{_N}\s+core\s*\+\s*{_N}\s+preview\b", re.I)
_TIER_LIST_RE = re.compile(
    r"\b(core|preview)\b(?:\s+tier)?\s*(?::|\()\s*([^()\n;.]+?)(?=[)\n;.]|$)", re.I
)
_TIER_SETS = {"core": set(CORE_HARNESSES), "preview": set(PREVIEW_HARNESSES)}
_M_EXPR_RE = re.compile(r"(?:^|\s)-m\s+(?:'([^']*)'|\"([^\"]*)\"|(\S+))")
_BRANCH_RE = re.compile(r"^([a-z]+)/([a-z0-9][a-z0-9-]*)$")
_COMMIT_RE = re.compile(r"^([a-z]+)(?:\([a-z0-9-]+\))?: \S+(?: \S+){2,}$")


def _pins(stem: str, group: str) -> frozenset[str]:
    """design.md §2 'Pin' column (F is applied everywhere and bites only on a mention)."""
    if group == "proposals":
        return frozenset("HLM")
    if stem == "acceptance-testing":  # §2 page 12: exists, light touch -- C and L only
        return frozenset("CL")
    return frozenset("CHL")


def _page_params(pattern: str) -> list:
    pages = [(s, g, c) for s, g, c in GUIDE_PAGES if pattern in _pins(s, g)]
    return [pytest.param(s, g, c, id=f"{s}.md") for s, g, c in pages]


# -- markdown slicing -------------------------------------------------------------------
def _read(stem: str) -> str:
    return (DOCS_DIR / f"{stem}.md").read_text(encoding="utf-8")


def _split_fences(text: str) -> tuple[list[str], list[tuple[int, str, str]]]:
    """(prose lines with fenced lines blanked, fenced lines as (line_no, fence lang, line))."""
    prose: list[str] = []
    fenced: list[tuple[int, str, str]] = []
    lang: str | None = None
    for no, line in enumerate(text.splitlines(), start=1):
        if match := _FENCE_RE.match(line):
            lang = match.group(1).lower() if lang is None else None
            prose.append("")
        elif lang is not None:
            fenced.append((no, lang, line))
            prose.append("")
        else:
            prose.append(line)
    return prose, fenced


def _code_spans(prose: list[str]) -> list[str]:
    return re.findall(r"`([^`\n]+)`", "\n".join(prose))


def _without_code_spans(prose: list[str]) -> list[str]:
    return [re.sub(r"`[^`\n]*`", "", line) for line in prose]


def _shell_lines(text: str) -> list[tuple[int, str]]:
    """Fenced shell commands: ``$`` stripped, comments dropped, ``\\`` continuations joined."""
    out: list[tuple[int, str]] = []
    start, joined = 0, ""
    for no, lang, raw in _split_fences(text)[1]:
        line = raw.strip()
        if lang not in _SHELL_LANGS or (not joined and (not line or line.startswith("#"))):
            continue
        start, joined = (start, f"{joined} {line}") if joined else (no, re.sub(r"^\$\s*", "", line))
        if joined.endswith("\\"):
            joined = joined[:-1].rstrip()
        else:
            out.append((start, joined))
            joined = ""
    return out


def _tokens(command: str) -> list[str]:
    tokens = shlex.split(_cut_at_shell_metachar(command), comments=True)
    if tokens and tokens[0] == "env":  # env -u VIRTUAL_ENV <command>
        tokens = tokens[1:]
        while tokens and tokens[0] in {"-u", "-i"}:
            tokens = tokens[2:] if tokens[0] == "-u" else tokens[1:]
    while tokens and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", tokens[0]):  # FOO=bar <command>
        tokens = tokens[1:]
    return tokens


def _form(tokens: list[str]) -> str | None:
    """Which §6 command form a fenced line is, or None when the test has no check for it."""
    if tokens[:1] == ["just"]:
        return "just"
    if tokens[:5] == ["uv", "run", "--group", "dev", "pytest"]:
        return "pytest"
    if tokens[:3] == ["uv", "run", "studyloop"]:
        return "studyloop"
    return "git-log" if tokens[:2] == ["git", "log"] else None


def _first_block(prose: list[str]) -> list[str]:
    """Lines of the first block after the H1, skipping blanks and HTML comments."""
    block: list[str] = []
    in_comment = False
    for line in prose[1:]:
        stripped = line.strip()
        if in_comment or (not block and stripped.startswith("<!--")):
            in_comment = "-->" not in stripped
        elif stripped:
            block.append(stripped)
        elif block:
            break
    return block


def _sentence_count(paragraph: str) -> int:
    text = re.sub(r"\]\([^)]*\)", "]", re.sub(r"`[^`]*`", "", paragraph))
    return max(1, len(re.findall(r"[.!?](?=\s|$)", text)))


def _headings(prose: list[str]) -> list[tuple[int, str]]:
    found = [re.match(r"^(#{1,6})\s+(.+?)\s*#*\s*$", line) for line in prose]
    return [(len(m.group(1)), m.group(2)) for m in found if m]


def _slug(heading: str) -> str:
    """python-markdown's ``toc`` slugify -- the ids mkdocs actually renders."""
    if custom := re.search(r"\{#([^}]+)\}", heading):
        return custom.group(1)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", heading)
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[-\s]+", "-", re.sub(r"[^\w\s-]", "", text).strip().lower())


# -- facts read from source -------------------------------------------------------------
def _recipes() -> frozenset[str]:
    names: set[str] = set()
    for line in JUSTFILE.read_text(encoding="utf-8").splitlines():
        if alias := _ALIAS_RE.match(line):
            names.add(alias.group(1))
        elif not line[:1].isspace() and (m := _RECIPE_RE.match(line)):
            names.add(m.group(1))
    assert "preflight" in names, "Justfile parse lost the preflight recipe"
    return frozenset(names)


def _declared_markers() -> frozenset[str]:
    options = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["tool"]["pytest"]["ini_options"]
    declared = frozenset(entry.split(":", 1)[0].strip() for entry in options["markers"])
    deselect = re.search(r"-m\s+'([^']*)'", options["addopts"])
    assert deselect, "pyproject addopts no longer carries a -m expression"
    used = set(re.findall(r"[A-Za-z_]\w*", deselect.group(1))) - {"and", "or", "not"}
    assert used <= declared, f"addopts deselects undeclared markers {sorted(used - declared)}"
    return declared


def _top_level_entries() -> frozenset[str]:
    skip = {".git", ".venv", ".cache", "site", "node_modules"}
    return frozenset(
        p.name for p in REPO_ROOT.iterdir() if p.name not in skip and ".egg-info" not in p.name
    )


def _number(token: str) -> int:
    return int(token) if token.isdigit() else _WORDS.index(token.lower())


def _harness_names_in(text: str) -> set[str]:
    """Harnesses named in *text* by label or name, longest labels first ("Kiro CLI" before "pi")."""
    found: set[str] = set()
    for name, harness in sorted(HARNESSES.items(), key=lambda kv: -len(kv[1].label)):
        for needle in (harness.label, name):
            pattern = rf"(?<![A-Za-z]){re.escape(needle)}(?![A-Za-z])"
            if re.search(pattern, text, re.I):
                found.add(name)
                text = re.sub(pattern, " ", text, flags=re.I)
    return found


def _run(argv: list[str], home: Path) -> subprocess.CompletedProcess[str]:
    """Run one allowlisted command with HOME/TMPDIR in *home*; uv offline, cache passed through.

    ``UV_PYTHON`` is pinned to the interpreter this suite runs on. ``uv run`` resolves its
    interpreter from ``.python-version`` (3.12) when the environment names none, and when
    that disagrees with the project ``.venv`` it REMOVES and recreates the venv -- which is
    the venv this very test process is running from. CI's 3.13 job did exactly that on
    2026-10-12 (``Removed virtual environment at: .venv``, then an offline download
    failure), and every later test that shelled out to ``.venv/bin/python`` or the
    ``studyloop`` console script failed with ``No module named ...``: 68 failures and 15
    errors from four fenced commands. The fresh env below strips the ``UV_PYTHON`` that
    ``setup-uv`` exports, so the pin has to be explicit.
    """
    cache = os.environ.get("UV_CACHE_DIR", str(Path.home() / ".cache" / "uv"))
    env = {"PATH": os.environ["PATH"], "HOME": str(home), "TMPDIR": str(home), "NO_COLOR": "1"}
    env |= {"UV_OFFLINE": "1", "UV_CACHE_DIR": cache}
    env["UV_PYTHON"] = f"{sys.version_info[0]}.{sys.version_info[1]}"
    return subprocess.run(
        argv, cwd=REPO_ROOT, env=env, capture_output=True, text=True, timeout=180, check=False
    )


# -- C: commands ------------------------------------------------------------------------
def _command_params() -> list:
    return [
        pytest.param(stem, command, id=f"{stem}.md:{line_no}")
        for stem, group, _cap in GUIDE_PAGES
        if "C" in _pins(stem, group)
        for line_no, command in _shell_lines(_read(stem))
        if _form(_tokens(command))
    ]


@pytest.mark.parametrize(("stem", "command"), _command_params())
def test_fenced_command_resolves(stem: str, command: str, tmp_path: Path) -> None:
    tokens = _tokens(command)
    where = f"{stem}.md: {command!r}"
    form = _form(tokens)
    if form == "just":
        assert len(tokens) > 1 and tokens[1] in _recipes(), f"{where}: no such Justfile recipe"
    elif form == "pytest":
        takes_value = {"-k", "-m", "-p", "-o", "-W", "-c", "-n", "--basetemp", "--tb"}
        paths = [
            tok.split("::", 1)[0]
            for prev, tok in pairwise(tokens[4:])
            if not tok.startswith("-")
            and prev not in takes_value
            and ("/" in tok or tok.endswith(".py"))
        ]
        missing = [p for p in paths if not ((REPO_ROOT / p).exists() or any(REPO_ROOT.glob(p)))]
        assert not missing, f"{where}: pytest paths do not exist: {missing}"
    elif form == "studyloop":
        if tuple(tokens[3:]) in _EXECUTED_STUDYLOOP:
            result = _run(tokens, tmp_path)
            assert result.returncode == 0, f"{where}: exit {result.returncode}\n{result.stderr}"
        else:
            root = _load_cli_group()
            ctx = click.Context(root, info_name="studyloop")
            problems = _validate_example(shlex.join(tokens[2:]), root, ctx)
            assert not problems, f"{where}: {problems}"
    else:  # git-log
        assert tokens[2:4] == ["-1", "--format=%h %s"] and len(tokens) == 5, (
            f"{where}: only `git log -1 --format='%h %s' <sha>` is allowlisted (design.md §6)"
        )
        assert tokens[4] in _F14_SHAS, f"{where}: {tokens[4]} is not an F14 sha (K5)"
        result = _run(tokens, tmp_path)
        if result.returncode != 0:
            shallow = _run(["git", "rev-parse", "--is-shallow-repository"], tmp_path).stdout
            if shallow.strip() == "true":
                pytest.skip(f"shallow checkout does not hold {tokens[4]}")
        assert result.returncode == 0, f"{where}: exit {result.returncode}\n{result.stderr}"
        assert result.stdout.startswith(tokens[4]), f"{where}: git printed {result.stdout!r}"


@pytest.mark.parametrize(("stem", "group", "cap"), _page_params("C"))
def test_backticked_repo_paths_exist(stem: str, group: str, cap: int) -> None:
    roots = _top_level_entries()
    missing: list[str] = []
    for span in _code_spans(_split_fences(_read(stem))[0]):
        token = span.strip().removeprefix("./")
        if " " in token or re.search(r"[<>{}…]|([A-Z])\1\1", token):
            continue
        token = re.sub(r"(::.*|:\d+(-\d+)?)$", "", token)
        first = token.partition("/")[0]
        last = token.rstrip("/").rsplit("/", 1)[-1]
        if first not in roots or not (token.endswith("/") or "." in last[1:]):
            continue
        if not ((REPO_ROOT / token).exists() or ("*" in token and any(REPO_ROOT.glob(token)))):
            missing.append(span)
    assert not missing, f"{stem}.md names repo paths that do not exist: {missing}"


# -- H: structure -----------------------------------------------------------------------
@pytest.mark.parametrize(("stem", "group", "cap"), _page_params("H"))
def test_structure(stem: str, group: str, cap: int) -> None:
    text = _read(stem)
    prose = _split_fences(text)[0]
    problems: list[str] = []
    if STUB_MARKER in text:
        problems.append("still a stub (marker present)")
    if (count := len(text.splitlines())) > cap:
        problems.append(f"{count} lines > cap {cap}")
    h1 = [title for level, title in _headings(prose) if level == 1]
    if len(h1) != 1 or not prose[0].startswith("# "):
        problems.append(f"expected exactly one H1 on line 1, found {h1}")
    block = _first_block(prose)
    if not block:
        problems.append("no content after the title")
    elif not re.match(r"^\d+[.)]\s", block[0]):
        if re.match(r"^([-*+]\s|>|\||!\[|#|```)", block[0]):
            problems.append(f"first block is not a paragraph or numbered list: {block[0][:40]!r}")
        elif (sentences := _sentence_count(" ".join(block))) > 3:
            problems.append(f"first paragraph has {sentences} sentences (max 3)")
    if not any(re.match(r"^\s*\d+[.)]\s+", line) for line in prose):
        problems.append("no numbered list")
    assert not problems, f"{stem}.md: " + "; ".join(problems)


# -- L: links ---------------------------------------------------------------------------
@pytest.mark.parametrize(("stem", "group", "cap"), _page_params("L"))
def test_links_resolve(stem: str, group: str, cap: int) -> None:
    page = DOCS_DIR / f"{stem}.md"
    broken: list[str] = []
    for target in _LINK_RE.findall("\n".join(_without_code_spans(_split_fences(_read(stem))[0]))):
        if "://" in target or target.startswith("mailto:"):
            continue
        path_part, _, anchor = target.partition("#")
        resolved = (page.parent / path_part) if path_part else page
        if not resolved.exists():
            broken.append(f"{target} (missing)")
        elif anchor and (resolved.suffix != ".md" or not resolved.is_relative_to(DOCS_DIR)):
            broken.append(f"{target} (anchor into a non-page)")
        elif anchor:
            headings = _headings(_split_fences(resolved.read_text(encoding="utf-8"))[0])
            if anchor not in {_slug(title) for _level, title in headings}:
                broken.append(f"{target} (no such heading)")
    assert not broken, f"{stem}.md has broken links: {broken}"


def test_router_h2_set_is_f10() -> None:
    h2 = [
        title for level, title in _headings(_split_fences(_read("contributing"))[0]) if level == 2
    ]
    assert h2 == _ROUTER_H2, "contributing.md H2s drifted from design.md §3 F10 (K3)"


# -- M: module pages --------------------------------------------------------------------
@pytest.mark.parametrize(("stem", "group", "cap"), _page_params("M"))
def test_module_pages_stay_proposals(stem: str, group: str, cap: int) -> None:
    text = _read(stem)
    first = " ".join(_first_block(_split_fences(text)[0])).lower()
    problems: list[str] = []
    proposed_re = re.compile(r"^(uv run )?studyloop (module|drill)\b")
    if proposed := [cmd for _no, cmd in _shell_lines(text) if proposed_re.match(cmd)]:
        problems.append(f"fenced proposed commands (K4): {proposed}")
    if stem == "contributor-module-index":
        if "design stage" not in first:
            problems.append('"design stage" missing from the first paragraph')
        if not any("module-contract-v1/proposal.md" in t for t in _LINK_RE.findall(text)):
            problems.append("no link to module-contract-v1/proposal.md")
        claims = [p for p in ("is available", "install it", "the index lists") if p in text.lower()]
        if claims:
            problems.append(f"present-tense claims about the index: {claims}")
    elif stem == "contributor-modules":
        # module-contract v1 shipped (W-review finding 9): the page is design history and
        # boundaries; the first paragraph says the contract is shipped, says there is no
        # registry, and names docs/module-contract.md as the authority.
        if "is shipped" not in first:
            problems.append('"is shipped" missing from the first paragraph')
        if "no registry" not in first:
            problems.append('"no registry" missing from the first paragraph')
        if not any(t.startswith("module-contract.md") for t in _LINK_RE.findall(text)):
            problems.append("no link to module-contract.md (the authority)")
    elif "proposal" not in first:
        problems.append('"proposal" missing from the first paragraph')
    assert not problems, f"{stem}.md: " + "; ".join(problems)


# -- F: facts ---------------------------------------------------------------------------
@pytest.mark.parametrize(("stem", "group", "cap"), _page_params("L"))
def test_facts_match_source(stem: str, group: str, cap: int) -> None:
    text = _read(stem)
    prose = _split_fences(text)[0]
    flat = " ".join(_without_code_spans(prose))
    spans = _code_spans(prose)
    commands = [cmd for _no, cmd in _shell_lines(text)]
    problems: list[str] = []
    for regex in _COUNT_RES:
        for n, tier in regex.findall(flat):
            expected = len(_TIER_SETS[tier.lower()] if tier else RELEASE_HARNESSES)
            if _number(n) != expected:
                problems.append(f"says {n} {tier or ''} harnesses, source has {expected}")
    for core_n, preview_n in _SPLIT_RE.findall(flat):
        if (_number(core_n), _number(preview_n)) != (len(CORE_HARNESSES), len(PREVIEW_HARNESSES)):
            problems.append(f"says {core_n} core + {preview_n} preview")
    for tier, listed in _TIER_LIST_RE.findall("\n".join(prose)):
        names = _harness_names_in(listed)
        if names and names != _TIER_SETS[tier.lower()]:
            problems.append(f"{tier} tier listed as {sorted(names)}")
    declared = _declared_markers()
    for source in spans + commands:
        for groups in _M_EXPR_RE.findall(source):
            expr = next(g for g in groups if g)
            unknown = set(re.findall(r"[A-Za-z_]\w*", expr)) - {"and", "or", "not"} - declared
            if unknown:
                problems.append(f"-m uses undeclared markers {sorted(unknown)} in {source!r}")
    not_prefixes = _top_level_entries() | {"origin", "upstream"}
    branches = [
        span
        for line in prose
        if re.search(r"branch", line, re.I)
        for span in _code_spans([line])
        if (m := _BRANCH_RE.match(span.strip())) and m.group(1) not in not_prefixes
    ]
    for tokens in map(_tokens, commands):
        if tokens[:3] in (["git", "switch", "-c"], ["git", "checkout", "-b"]) and len(tokens) > 3:
            branches.append(tokens[3])
    for branch in branches:
        if "/" in branch and branch.split("/", 1)[0] not in _BRANCH_PREFIXES:
            problems.append(f"branch {branch!r} is outside the F1 prefixes {_BRANCH_PREFIXES}")
    for span in spans:
        if (m := _COMMIT_RE.match(span.strip())) and m.group(1) not in _COMMIT_TYPES:
            problems.append(f"commit subject {span!r} uses a type outside {_COMMIT_TYPES}")
    assert not problems, f"{stem}.md: " + "; ".join(problems)
