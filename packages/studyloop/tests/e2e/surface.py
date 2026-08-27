"""Product-surface introspection for the mandatory e2e coverage gate.

WHY THIS EXISTS
---------------
A hand-maintained list of "things we test" rots the moment someone adds a
route, a nav view, or a CLI command. This module derives the surface from the
*running product* instead:

- HTTP/WS routes come from ``create_app()`` (the real FastAPI router)
- nav views come from the real ``index.html`` Alpine nav bindings
- CLI commands come from the real Click group tree
- render surfaces (html / terminal / markdown / mermaid) come from a fixed
  taxonomy — the four render classes the user asked to be validated

``tests/test_e2e_coverage_gate.py`` compares this surface against what the
test suite actually exercises, so *new functionality fails the build until it
is covered or explicitly waived*. That is the "mandatory checkmark" property:
extensibility is automatic because the surface is introspected, never typed.

Importable without any server running: everything here is static analysis or
in-process app construction.
"""

from __future__ import annotations

import ast
import json
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from functools import cache, lru_cache
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

# --------------------------------------------------------------------------
# Repo layout
# --------------------------------------------------------------------------


@lru_cache(maxsize=1)
def package_root() -> Path:
    """Return ``packages/studyloop`` (the dir holding ``src/`` and ``tests/``)."""
    for parent in Path(__file__).resolve().parents:
        if (parent / "src" / "studyloop").is_dir() and (parent / "tests").is_dir():
            return parent
    msg = f"Could not locate packages/studyloop from {__file__}"
    raise RuntimeError(msg)


def tests_root() -> Path:
    return package_root() / "tests"


def index_html() -> Path:
    return package_root() / "src" / "studyloop" / "web" / "static" / "index.html"


# --------------------------------------------------------------------------
# Surface records
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Route:
    """One HTTP or WebSocket endpoint of the web app."""

    method: str  # "GET", "POST", ..., or "WS"
    path: str  # FastAPI path with {params}

    @property
    def key(self) -> str:
        return f"{self.method} {self.path}"

    @property
    def literal_prefix(self) -> str:
        """The path up to the first ``{param}`` — what tests literally type."""
        return self.path.split("{", 1)[0].rstrip("/") or "/"


# --------------------------------------------------------------------------
# 1. Routes — from the real FastAPI app
# --------------------------------------------------------------------------

# Framework-provided endpoints that are not StudyLoop functionality.
_FRAMEWORK_PATHS = {"/openapi.json", "/docs", "/redoc", "/docs/oauth2-redirect"}


@lru_cache(maxsize=1)
def discover_routes() -> tuple[Route, ...]:
    """Return every StudyLoop route exposed by ``create_app()``.

    Static mounts (``/static``) are excluded — they are asset serving, not
    functionality; their *contents* are covered by the render surface.
    """
    from studyloop.web.app import create_app

    app = create_app()
    found: set[Route] = set()
    for r in app.routes:
        path = getattr(r, "path", None)
        if not path or path in _FRAMEWORK_PATHS or path.startswith("/static"):
            continue
        methods = getattr(r, "methods", None)
        if methods:
            for m in methods:
                if m in {"HEAD", "OPTIONS"}:  # implied by GET
                    continue
                found.add(Route(m, path))
        else:  # websocket route
            found.add(Route("WS", path))
    return tuple(sorted(found, key=lambda r: (r.path, r.method)))


# --------------------------------------------------------------------------
# 2. Nav views — from the real index.html
# --------------------------------------------------------------------------

_VIEW_RE = re.compile(r"""\$store\.nav\.(?:is|go)\(\s*['"]([a-z0-9-]+)['"]""")


@lru_cache(maxsize=1)
def discover_views() -> tuple[str, ...]:
    """Return every nav view id the SPA can display."""
    html = index_html().read_text(encoding="utf-8")
    return tuple(sorted(set(_VIEW_RE.findall(html))))


# --------------------------------------------------------------------------
# 3. CLI commands — from the real Click tree
# --------------------------------------------------------------------------


@lru_cache(maxsize=1)
def discover_cli_commands() -> tuple[str, ...]:
    """Return every invocable command path, e.g. ``content generate-cards``.

    Groups that only namespace subcommands (``content``) are included too —
    ``studyloop content`` prints help and is a user-visible surface.
    """
    import click

    from studyloop.cli import cli

    ctx = click.Context(cli)
    out: list[str] = []

    def walk(group: click.Group, prefix: str = "") -> None:
        for name in group.list_commands(ctx):
            sub = group.get_command(ctx, name)
            full = f"{prefix}{name}"
            out.append(full)
            if isinstance(sub, click.Group):
                walk(sub, full + " ")

    walk(cli)
    return tuple(sorted(out))


# --------------------------------------------------------------------------
# 4. Terminal multiplexer backends
#
# `studyloop study` drives a terminal multiplexer to lay out the agent pane +
# sidebar. Today that is tmux; the roadmap replaces it with herdr
# (https://github.com/herdrdev/herdr — an agent multiplexer with a socket API).
# A swap of that size must not land untested, so the backend set is
# INTROSPECTED from the source tree: adding `studyloop/herdr.py` (or any other
# backend module) automatically adds a gate assertion demanding a
# session-lifecycle test for it.
# --------------------------------------------------------------------------

#: Module basename → the multiplexer it drives. Extend only by adding a real
#: backend module; the gate reads the filesystem, not this map.
_KNOWN_MULTIPLEXERS = ("tmux", "herdr", "zellij", "screen")


@lru_cache(maxsize=1)
def discover_multiplexers() -> tuple[str, ...]:
    """Return the multiplexer backends the package actually implements.

    Detection is by module presence (``src/studyloop/<name>.py`` or
    ``src/studyloop/<name>/``) so a new backend cannot be added silently.
    """
    src = package_root() / "src" / "studyloop"
    found = [
        name
        for name in _KNOWN_MULTIPLEXERS
        if (src / f"{name}.py").is_file() or (src / name).is_dir()
    ]
    return tuple(found)


def multiplexer_references(name: str) -> tuple[Path, ...]:
    """Return test modules that exercise the ``name`` multiplexer backend."""
    needles = (f"studyloop.{name}", f"from studyloop import {name}", f'"{name}"', f"'{name}'")
    return tuple(
        sorted({f.path for f in _evidence_fragments() if any(n in f.text for n in needles)})
    )


# --------------------------------------------------------------------------
# 5. Render surfaces — the four classes the harness must validate
# --------------------------------------------------------------------------

#: Each render class maps to the browser-observable evidence that proves it
#: renders (not merely that the DOM node exists).
RENDER_SURFACES: dict[str, str] = {
    "html": "served SPA parses, has no console errors, and lays out without overlap/clipping",
    "terminal": "xterm.js paints agent bytes into a sized canvas/rows in the live session view",
    "markdown": "marked.js converts lesson markdown into real block elements (h*/p/ul/code)",
    "mermaid": "mermaid.js turns a ```mermaid fence into an <svg> with rendered nodes",
}


# --------------------------------------------------------------------------
# Runnable-item evidence
#
# WHY THIS REPLACED RAW SOURCE SCANNING
# -------------------------------------
# Coverage evidence used to come from module SOURCE TEXT: every reference
# query searched whole test files. A ``@pytest.mark.skip`` test therefore still
# certified any surface whose needle appeared in its text — across every needle
# class (routes, views, CLI, multiplexers, render proofs), not just routes.
# Quarantining a suite kept the gate green while the real proof vanished.
#
# Evidence now comes from the set of test items pytest can actually COLLECT AND
# RUN. A collection subprocess (see ``e2e/coverage_collector.py``) writes a
# manifest flagging each concrete item ``eligible`` or not, using pytest's own
# marker evaluation. Only eligible items contribute searchable text, and that
# text is attributed PER ITEM via ``ast``:
#
#   * the runnable test body (decorators excluded, so a skipped
#     ``pytest.param("/api/foo", marks=...)`` cannot leak its route);
#   * that concrete item's serialised parameter values; and
#   * a recursive name-dependency closure over module-local fixtures, helpers,
#     constants and imports the runnable test actually references.
#
# So a skipped test can no longer lend its strings to an active neighbour, and
# a whole module is never treated as one undifferentiated blob of evidence.
# --------------------------------------------------------------------------


#: The gate's own modules and this machinery must never count as coverage
#: evidence — they name every route/command/view in waiver registries and
#: assertion messages, so scanning them would report the whole surface as
#: "covered by itself".
_SELF_EXCLUDED = {
    "test_e2e_coverage_gate.py",
    "test_e2e_coverage_gate_selftest.py",
    "surface.py",
    "coverage_collector.py",
}

_MANIFEST_ENV = "STUDYLOOP_COVERAGE_MANIFEST"


@dataclass(frozen=True)
class _CollectedItem:
    """One row of the collection manifest: a single concrete pytest item."""

    path: Path
    nodeid: str
    qualname: str
    name: str
    firstlineno: int | None
    fixtures: tuple[str, ...]
    params: tuple[str, ...]
    eligible: bool
    exclusion_kind: str
    exclusion_reason: str


@dataclass(frozen=True)
class _EvidenceFragment:
    """Searchable text owned by exactly one collected item.

    Ineligible items are represented too (so failures can name the skipped
    candidate that *would* have matched); callers that supply coverage filter
    on :attr:`eligible`.
    """

    path: Path
    nodeid: str
    text: str
    is_browser: bool
    is_full_stack: bool
    eligible: bool
    exclusion_kind: str
    exclusion_reason: str


def _is_inside(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


@cache
def _collect_test_items(root: Path) -> tuple[_CollectedItem, ...]:
    """Collect ``root`` in an isolated subprocess and parse the manifest.

    Runs ``sys.executable -m pytest --collect-only`` with the coverage
    collector plugin loaded. ``-o addopts=`` neutralises the repository default
    (``-m 'not e2e ...'`` plus ``--cov``); without it the e2e evidence being
    audited would be deselected and hidden. Cached once per gate process.

    On ANY failure — non-zero exit, missing manifest, invalid JSON — raises
    ``RuntimeError`` with the command and the useful tail of stderr. It never
    falls back to source scanning: a silent fallback would restore exactly the
    false green the manifest exists to remove.
    """
    root = Path(root)
    tests_dir = tests_root()

    fd, manifest_name = tempfile.mkstemp(prefix="sl-coverage-manifest-", suffix=".json")
    os.close(fd)
    manifest = Path(manifest_name)

    cmd = [
        sys.executable,
        "-m",
        "pytest",
        "--collect-only",
        "-q",
        "-o",
        "addopts=",
        "-p",
        "e2e.coverage_collector",
    ]

    if _is_inside(root, package_root()):
        # Inside the repo: let pytest discover the real rootdir/config so the
        # true conftest and marker set apply; only addopts is neutralised.
        cwd: str = str(package_root())
    else:
        # Outside the repo (self-tests point at a tmp dir): pytest would resolve
        # its rootdir UPWARD to ``$HOME`` and die on the first unreadable
        # dotfile it stats. Anchor it with a generated ``pytest.ini`` and run
        # from inside the directory so the search stops dead.
        ini = root / "pytest.ini"
        if not ini.exists():
            ini.write_text("[pytest]\n", encoding="utf-8")
        cmd += ["-c", str(ini)]
        cwd = str(root)

    cmd += [str(root)]

    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        part for part in (str(tests_dir), env.get("PYTHONPATH")) if part
    )
    env[_MANIFEST_ENV] = str(manifest)

    try:
        proc = subprocess.run(
            cmd,
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            timeout=900,
            check=False,
        )
        if proc.returncode != 0 or not manifest.exists():
            tail = (proc.stderr or proc.stdout or "")[-3000:]
            msg = (
                "coverage collection subprocess failed; refusing to fall back "
                "to source scanning.\n"
                f"cmd: {' '.join(cmd)}\n"
                f"returncode: {proc.returncode}\n"
                f"stderr tail:\n{tail}"
            )
            raise RuntimeError(msg)
        try:
            payload = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            msg = f"coverage manifest at {manifest} was absent or invalid: {exc}"
            raise RuntimeError(msg) from exc
    finally:
        manifest.unlink(missing_ok=True)

    items: list[_CollectedItem] = []
    for row in payload.get("items", ()):
        items.append(
            _CollectedItem(
                path=Path(row["path"]),
                nodeid=row["nodeid"],
                qualname=row.get("qualname") or row.get("name") or "",
                name=row.get("name") or "",
                firstlineno=row.get("firstlineno"),
                fixtures=tuple(row.get("fixtures") or ()),
                params=tuple(str(v) for v in (row.get("params") or {}).values()),
                eligible=bool(row.get("eligible")),
                exclusion_kind=row.get("exclusion_kind") or "",
                exclusion_reason=row.get("exclusion_reason") or "",
            )
        )
    return tuple(items)


# --------------------------------------------------------------------------
# Per-item AST attribution
# --------------------------------------------------------------------------


def _node_source(lines: Sequence[str], node: ast.stmt) -> str:
    """Source of ``node`` EXCLUDING any decorators.

    Since Python 3.8 ``node.lineno`` is the ``def``/``class`` line, so slicing
    from it drops the decorator lines above — which is precisely what keeps a
    skipped ``pytest.param("/api/foo", marks=...)`` from leaking its route
    literal into an active sibling's evidence.
    """
    start = (node.lineno or 1) - 1
    end = node.end_lineno or node.lineno or 1
    return "".join(lines[start:end])


def _decorator_start(node: ast.stmt) -> int:
    """First line the item occupies including decorators (matches co_firstlineno)."""
    candidates = [node.lineno]
    for dec in getattr(node, "decorator_list", ()) or ():
        candidates.append(dec.lineno)
    return min(line for line in candidates if line)


def _referenced_names(node: ast.AST) -> set[str]:
    """Bare names referenced inside ``node``, EXCLUDING its own decorators."""
    if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
        subtrees: list[ast.AST] = [node.args, *node.body]
    elif isinstance(node, ast.ClassDef):
        subtrees = [*node.bases, *node.keywords, *node.body]
    else:
        subtrees = [node]
    names: set[str] = set()
    for sub in subtrees:
        for child in ast.walk(sub):
            if isinstance(child, ast.Name):
                names.add(child.id)
    return names


def _assign_target_names(target: ast.expr) -> list[str]:
    if isinstance(target, ast.Name):
        return [target.id]
    if isinstance(target, ast.Tuple | ast.List):
        out: list[str] = []
        for elt in target.elts:
            out.extend(_assign_target_names(elt))
        return out
    return []


@dataclass(frozen=True)
class _ModuleAst:
    lines: tuple[str, ...]
    nodes_by_qualname: dict[str, tuple[ast.stmt, ...]]
    #: name -> (source text, defining node or None for imports)
    name_defs: dict[str, tuple[str, ast.stmt | None]]


@cache
def _parse_module(path: Path) -> _ModuleAst | None:
    try:
        source = path.read_text(encoding="utf-8")
    except OSError:  # pragma: no cover - unreadable file
        return None
    try:
        tree = ast.parse(source)
    except SyntaxError:  # pragma: no cover - a test module that will not import
        return None
    lines = tuple(source.splitlines(keepends=True))

    nodes: dict[str, list[ast.stmt]] = {}

    def walk_defs(body: list[ast.stmt], prefix: str) -> None:
        for stmt in body:
            if isinstance(stmt, ast.FunctionDef | ast.AsyncFunctionDef):
                nodes.setdefault(f"{prefix}{stmt.name}", []).append(stmt)
            elif isinstance(stmt, ast.ClassDef):
                walk_defs(stmt.body, f"{prefix}{stmt.name}.")

    walk_defs(tree.body, "")

    name_defs: dict[str, tuple[str, ast.stmt | None]] = {}
    for stmt in tree.body:
        if isinstance(stmt, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            name_defs.setdefault(stmt.name, (_node_source(lines, stmt), stmt))
        elif isinstance(stmt, ast.Assign):
            text = _node_source(lines, stmt)
            for tgt in stmt.targets:
                for nm in _assign_target_names(tgt):
                    name_defs.setdefault(nm, (text, stmt))
        elif isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
            name_defs.setdefault(stmt.target.id, (_node_source(lines, stmt), stmt))
        elif isinstance(stmt, ast.Import):
            text = _node_source(lines, stmt)
            for alias in stmt.names:
                bound = alias.asname or alias.name.split(".")[0]
                name_defs.setdefault(bound, (text, None))
        elif isinstance(stmt, ast.ImportFrom):
            text = _node_source(lines, stmt)
            for alias in stmt.names:
                if alias.name == "*":
                    continue
                bound = alias.asname or alias.name
                name_defs.setdefault(bound, (text, None))

    return _ModuleAst(lines, {q: tuple(ns) for q, ns in nodes.items()}, name_defs)


def _match_node(mod: _ModuleAst, item: _CollectedItem) -> ast.stmt | None:
    """Find the AST node owning ``item`` by qualified name, then by line."""
    candidates = list(mod.nodes_by_qualname.get(item.qualname, ()))
    if not candidates:
        tail = item.qualname.rsplit(".", 1)[-1]
        candidates = [
            n
            for qn, ns in mod.nodes_by_qualname.items()
            if qn.rsplit(".", 1)[-1] == tail
            for n in ns
        ]
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]
    if item.firstlineno is not None:
        for node in candidates:
            if _decorator_start(node) == item.firstlineno:
                return node
    return candidates[0]


def _closure_texts(
    node: ast.stmt,
    name_defs: dict[str, tuple[str, ast.stmt | None]],
    seed_names: Sequence[str],
) -> list[str]:
    """Source of every module-local name the runnable ``node`` depends on.

    A recursive name-dependency closure: start from the names the test body and
    its effective fixtures reference, pull in each matching module-local
    definition (fixture, helper, constant, import), and recurse into the names
    *those* reference. This includes a helper only because a runnable test
    reaches it — never the whole module as shared text.
    """
    included: set[str] = set()
    texts: list[str] = []
    stack: list[str] = list(_referenced_names(node) | set(seed_names))
    while stack:
        name = stack.pop()
        if name in included:
            continue
        included.add(name)
        entry = name_defs.get(name)
        if entry is None:
            continue
        text, defnode = entry
        texts.append(text)
        if defnode is not None:
            for nm in _referenced_names(defnode):
                if nm not in included:
                    stack.append(nm)
    return texts


def _is_browser_test(path: Path, text: str) -> bool:
    """True when the evidence drives a real browser via Playwright.

    Deliberately narrower than "lives in tests/e2e/": an API-level test that
    happens to sit in the e2e package is full-stack but is not a *browser*
    test, and conflating the two let render/view regressions hide behind a
    passing requests call. Now classifies one item's evidence fragment rather
    than an entire raw module.
    """
    lowered = text.lower()
    return (
        "playwright" in lowered
        or "browser.new_page" in text
        or "browser.new_context" in text
        or ("page:" in text and "locator(" in text)
    )


def _is_full_stack_test(path: Path, text: str) -> bool:
    """True when the evidence exercises a real running server.

    Either the owning item lives in the ``tests/e2e`` package (which launches a
    subprocess server against an isolated vault) or its evidence drives a
    browser.
    """
    return "e2e" in path.parts or _is_browser_test(path, text)


@cache
def _evidence_fragments_for(root: Path) -> tuple[_EvidenceFragment, ...]:
    """Build one evidence fragment per collected item under ``root``.

    Includes ineligible items (flagged) so diagnostics can name a skipped
    candidate; coverage callers use :func:`_evidence_fragments`, which filters
    to eligible items only.
    """
    by_path: dict[Path, list[_CollectedItem]] = {}
    for item in _collect_test_items(root):
        if item.path.name in _SELF_EXCLUDED or "__pycache__" in item.path.parts:
            continue
        by_path.setdefault(item.path, []).append(item)

    fragments: dict[str, _EvidenceFragment] = {}
    for path, path_items in by_path.items():
        mod = _parse_module(path)
        for item in path_items:
            parts: list[str] = []
            if mod is not None:
                node = _match_node(mod, item)
                if node is not None:
                    parts.append(_node_source(mod.lines, node))
                    parts.extend(_closure_texts(node, mod.name_defs, item.fixtures))
            if item.params:
                parts.append(" ".join(item.params))
            text = "\n".join(parts)
            fragments[item.nodeid] = _EvidenceFragment(
                path=path,
                nodeid=item.nodeid,
                text=text,
                is_browser=_is_browser_test(path, text),
                is_full_stack=_is_full_stack_test(path, text),
                eligible=item.eligible,
                exclusion_kind=item.exclusion_kind,
                exclusion_reason=item.exclusion_reason,
            )
    return tuple(fragments.values())


def _evidence_fragments() -> tuple[_EvidenceFragment, ...]:
    """Evidence from ELIGIBLE runnable items in the real tests tree (cached)."""
    return tuple(f for f in _evidence_fragments_for(tests_root()) if f.eligible)


def _inactive_reference_diagnostics(needle: str) -> tuple[str, ...]:
    """Node IDs + skip/xfail reasons for EXCLUDED items whose text matches.

    Explains a red gate: a surface can be uncovered precisely because its only
    textual candidate is a skipped or active-xfail test. Substring matching is
    deliberately looser than the route boundary matcher — this is a diagnostic
    hint about why coverage is missing, not a coverage decision.
    """
    out: list[str] = []
    for f in _evidence_fragments_for(tests_root()):
        if f.eligible or needle not in f.text:
            continue
        reason = f.exclusion_reason or "(no reason given)"
        out.append(f"{f.nodeid} [{f.exclusion_kind}: {reason}]")
    return tuple(sorted(out))


# --------------------------------------------------------------------------
# Public reference queries — surface used by the gate. Return types unchanged:
# each yields unique source ``Path`` values.
# --------------------------------------------------------------------------


def files_referencing(needle: str) -> tuple[Path, ...]:
    """Return test modules whose runnable evidence contains ``needle``."""
    return tuple(sorted({f.path for f in _evidence_fragments() if needle in f.text}))


def _path_boundary_re(prefix: str) -> re.Pattern[str]:
    """Compile a matcher for ``prefix`` that respects URL path boundaries.

    ``/artefacts/`` must not be found inside ``/api/artefacts/`` — those are
    different routes with different handlers. Requiring the character before
    the prefix to be a non-path character (a quote, ``}`` from an f-string,
    whitespace) keeps sibling prefixes from crediting each other's coverage.
    """
    return re.compile(r"(?<![A-Za-z0-9_/])" + re.escape(prefix))


def _route_reference_files(
    route: Route,
    fragment_filter: Callable[[_EvidenceFragment], bool] | None = None,
) -> tuple[Path, ...]:
    pattern = _path_boundary_re(route.literal_prefix)
    return tuple(
        sorted(
            {
                f.path
                for f in _evidence_fragments()
                if pattern.search(f.text) and (fragment_filter is None or fragment_filter(f))
            }
        )
    )


def route_references(route: Route) -> tuple[Path, ...]:
    """Return test modules that appear to exercise ``route``.

    Matching is on the literal path prefix (everything before the first path
    parameter) because that is what a test types: ``/api/cards/`` for
    ``/api/cards/{course}``. Prefix matching can still over-match a *nested*
    sibling (``/api/parking/`` vs ``/api/parking/columns``), so the gate treats
    this as *evidence of coverage*, not proof of assertion depth — depth is
    what the journey tests add.
    """
    return _route_reference_files(route)


def full_stack_route_references(route: Route) -> tuple[Path, ...]:
    """Same as :func:`route_references` but only full-stack (real server) tests."""
    return _route_reference_files(route, lambda f: f.is_full_stack)


def browser_route_references(route: Route) -> tuple[Path, ...]:
    """Same as :func:`route_references` but only Playwright-driven tests."""
    return _route_reference_files(route, lambda f: f.is_browser)


def view_references(view: str) -> tuple[Path, ...]:
    """Return browser test modules that navigate to ``view``."""
    needles = (f"'{view}'", f'"{view}"', f"#{view}")
    return tuple(
        sorted(
            {
                f.path
                for f in _evidence_fragments()
                if f.is_browser and any(n in f.text for n in needles)
            }
        )
    )


def cli_references(command: str) -> tuple[Path, ...]:
    """Return test modules that invoke ``command``.

    Accepts the shell form (``"content generate-cards"``), the argv-list form
    (``["content", "generate-cards"]``) and the CliRunner form.
    """
    parts = command.split()
    shell_form = " ".join(parts)
    argv_forms = [
        ", ".join(f'"{p}"' for p in parts),
        ", ".join(f"'{p}'" for p in parts),
    ]
    return tuple(
        sorted(
            {
                f.path
                for f in _evidence_fragments()
                if shell_form in f.text or any(a in f.text for a in argv_forms)
            }
        )
    )
