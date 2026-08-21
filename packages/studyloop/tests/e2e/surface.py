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

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

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
    return tuple(p for p, text in _test_sources() if any(n in text for n in needles))


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
# Test-source scanning
# --------------------------------------------------------------------------


#: The gate's own modules must never count as coverage evidence — they name
#: every route/command/view in their waiver registries and assertion messages,
#: so scanning them would report the whole surface as "covered by itself".
_SELF_EXCLUDED = {
    "test_e2e_coverage_gate.py",
    "test_e2e_coverage_gate_selftest.py",
    "surface.py",
}


@lru_cache(maxsize=1)
def _test_sources() -> tuple[tuple[Path, str], ...]:
    """Return (path, text) for every test module in the studyloop package."""
    out = []
    for p in sorted(tests_root().rglob("test_*.py")):
        if "__pycache__" in p.parts or p.name in _SELF_EXCLUDED:
            continue
        try:
            out.append((p, p.read_text(encoding="utf-8")))
        except OSError:  # pragma: no cover - unreadable file
            continue
    return tuple(out)


def _is_browser_test(path: Path, text: str) -> bool:
    """True when the module drives a real browser via Playwright.

    Deliberately narrower than "lives in tests/e2e/": an API-level test that
    happens to sit in the e2e package is full-stack but is not a *browser*
    test, and conflating the two let render/view regressions hide behind a
    passing requests call.
    """
    lowered = text.lower()
    return (
        "playwright" in lowered
        or "browser.new_page" in text
        or "browser.new_context" in text
        or ("page:" in text and "locator(" in text)
    )


def _is_full_stack_test(path: Path, text: str) -> bool:
    """True when the module exercises a real running server.

    Either it lives in the ``tests/e2e`` package (which launches a subprocess
    server against an isolated vault) or it drives a browser.
    """
    return "e2e" in path.parts or _is_browser_test(path, text)


def files_referencing(needle: str) -> tuple[Path, ...]:
    """Return test modules whose source contains ``needle``."""
    return tuple(p for p, text in _test_sources() if needle in text)


def _path_boundary_re(prefix: str) -> re.Pattern[str]:
    """Compile a matcher for ``prefix`` that respects URL path boundaries.

    ``/artefacts/`` must not be found inside ``/api/artefacts/`` — those are
    different routes with different handlers. Requiring the character before
    the prefix to be a non-path character (a quote, ``}`` from an f-string,
    whitespace) keeps sibling prefixes from crediting each other's coverage.
    """
    return re.compile(r"(?<![A-Za-z0-9_/])" + re.escape(prefix))


def _route_reference_files(route: Route, predicate=None) -> tuple[Path, ...]:
    pattern = _path_boundary_re(route.literal_prefix)
    return tuple(
        p
        for p, text in _test_sources()
        if pattern.search(text) and (predicate is None or predicate(p, text))
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
    return _route_reference_files(route, _is_full_stack_test)


def browser_route_references(route: Route) -> tuple[Path, ...]:
    """Same as :func:`route_references` but only Playwright-driven tests."""
    return _route_reference_files(route, _is_browser_test)


def view_references(view: str) -> tuple[Path, ...]:
    """Return browser test modules that navigate to ``view``."""
    needles = (f"'{view}'", f'"{view}"', f"#{view}")
    return tuple(
        p
        for p, text in _test_sources()
        if _is_browser_test(p, text) and any(n in text for n in needles)
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
    out = []
    for p, text in _test_sources():
        if shell_form in text or any(f in text for f in argv_forms):
            out.append(p)
    return tuple(out)
