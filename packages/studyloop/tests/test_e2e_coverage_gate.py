"""MANDATORY coverage gate — new functionality must be tested to merge.

This module is deliberately *not* marked ``e2e``: it runs in the default
``pytest`` selection so it is one of the checkmarks every contributor sees.
It answers one question for each slice of the product surface:

    "Is this reachable by a test, and — for user-facing surfaces — by a test
     that drives a real browser the way a user would?"

The surface is introspected from the running app / real ``index.html`` / real
Click tree (see :mod:`e2e.surface`), so *adding* a route, nav view, or CLI
command automatically adds an assertion here. There is no list to remember to
update — the only way to make this gate pass for new functionality is to test
it, or to register an explicit, reasoned waiver below.

Waivers are self-cleaning: if a waived item becomes covered, the gate fails
and tells you to delete the waiver. Coverage therefore ratchets upward and
cannot silently regress.

Run:  uv run pytest packages/studyloop/tests/test_e2e_coverage_gate.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_tests_dir = str(Path(__file__).resolve().parent)
if _tests_dir not in sys.path:
    sys.path.insert(0, _tests_dir)

from e2e.surface import (  # noqa: E402
    RENDER_SURFACES,
    _inactive_reference_diagnostics,
    cli_references,
    discover_cli_commands,
    discover_multiplexers,
    discover_routes,
    discover_views,
    files_referencing,
    full_stack_route_references,
    multiplexer_references,
    route_references,
    view_references,
)

#: Prepended to every "missing surface" message. Coverage now comes from test
#: items pytest can actually run, so a quarantined test no longer certifies its
#: surface — the single most surprising behaviour change for a contributor who
#: sees a green suite go red after adding ``@pytest.mark.skip``.
_SKIP_NOTE = "Skipped and active-xfail tests do not count as coverage."

# ---------------------------------------------------------------------------
# Waiver registries
#
# Every entry MUST carry a reason explaining why a full-stack/user-level test
# is not the right tool. "Not written yet" is not a reason — write the test.
#
# Three tiers are enforced, from weakest to strongest evidence:
#   1. every route has *a* test                       (test_every_route_has_a_test)
#   2. every route is exercised against a real server (test_every_route_has_a_full_stack_test)
#   3. every nav view + render class is driven by a real browser
#      (test_every_nav_view_has_a_browser_test, test_render_class_has_a_named_proof_test)
#
# Tier 3 is where "as a user would" is strictest, and it has NO waiver list:
# a view a learner can open must be opened by Playwright.
# ---------------------------------------------------------------------------

#: Routes with no test of any kind. Should stay EMPTY.
ROUTE_NO_TEST_WAIVERS: dict[str, str] = {}

#: Routes exercised only by in-process (TestClient) tests, never against a real
#: running server. Each entry names why a full-stack walk is not viable.
ROUTE_NO_FULL_STACK_WAIVERS: dict[str, str] = {
    "GET /artefacts/{course}/{artefact_type}/{filename:path}": (
        "Serves generated artefact files (audio/video/HTML overviews) straight "
        "from disk. A full-stack walk needs a generated artefact set, which is "
        "produced by NotebookLM and is not reproducible in a hermetic run; the "
        "path-resolution and traversal guards are covered by "
        "test_web_artefacts.py against the ASGI app."
    ),
    "WS /api/content/generate/ws": (
        "Streams progress for a real generation job over a WebSocket. The "
        "socket protocol is covered by test_web_content_gen_ws.py in-process; a "
        "full-stack run would need a live LLM provider, which the "
        "live_provider-marked suites own."
    ),
}

#: CLI commands with no test. Maintainer/one-shot commands may be waived;
#: anything a learner runs in the documented workflow may not.
CLI_WAIVERS: dict[str, str] = {
    "content autopilot": (
        "Long-running orchestration across real providers and the network; its "
        "components (discover/ingest/generate) are each tested individually."
    ),
    "content download": (
        "Fetches course material from third-party hosts over the network — not "
        "reproducible in a hermetic run."
    ),
    "content delete": (
        "Destructive maintenance command that removes generated material; "
        "exercised manually to keep data-loss risk out of automated runs."
    ),
}


def _fmt(items: dict[str, str] | list[str]) -> str:
    if isinstance(items, dict):
        return "\n".join(f"  - {k}: {v}" for k, v in sorted(items.items()))
    return "\n".join(f"  - {i}" for i in sorted(items))


def _inactive_note(needle: str) -> str:
    """Append any skipped/xfail candidate that WOULD have matched ``needle``.

    Turns "this surface has no test" into "its only textual candidate is this
    quarantined test, for this reason" — the difference between a mystery and
    an actionable failure.
    """
    cands = _inactive_reference_diagnostics(needle)
    if not cands:
        return ""
    body = "\n".join(f"      · {c}" for c in cands)
    return "\n    inactive textual candidates (skipped/xfail — do not count):\n" + body


def _fmt_missing(pairs: list[tuple[str, str]]) -> str:
    """Format ``(label, needle)`` rows, annotating each inactive candidate."""
    return "\n".join(f"  - {label}{_inactive_note(needle)}" for label, needle in sorted(pairs))


# ---------------------------------------------------------------------------
# 1. Every route is reachable by some test
# ---------------------------------------------------------------------------


def test_every_route_has_a_test() -> None:
    """No endpoint ships without a test touching it."""
    missing = [r for r in discover_routes() if not route_references(r)]
    unwaived = [r for r in missing if r.key not in ROUTE_NO_TEST_WAIVERS]
    assert not unwaived, (
        f"New/untested endpoints detected. {_SKIP_NOTE} Add a test that "
        "exercises each (preferably a browser journey in tests/e2e/), or "
        "register a reasoned waiver in ROUTE_NO_TEST_WAIVERS:\n"
        + _fmt_missing([(r.key, r.literal_prefix) for r in unwaived])
    )


def test_route_no_test_waivers_are_not_stale() -> None:
    """A waived route that is now covered must have its waiver removed."""
    now_covered = [
        r.key for r in discover_routes() if r.key in ROUTE_NO_TEST_WAIVERS and route_references(r)
    ]
    assert not now_covered, (
        "These routes are now tested — delete their ROUTE_NO_TEST_WAIVERS "
        f"entries so the gate keeps ratcheting:\n{_fmt(now_covered)}"
    )


# ---------------------------------------------------------------------------
# 2. Every route is exercised against a real running server
# ---------------------------------------------------------------------------


def test_every_route_has_a_full_stack_test() -> None:
    """Endpoints are exercised against a real server, not only in-process.

    A ``TestClient`` call proves the handler works; it does not prove the route
    survives real ASGI serving, real config loading, real auth middleware and a
    real event loop — which is where StudyLoop's session-start bugs have lived.
    """
    missing = [
        r
        for r in discover_routes()
        if not full_stack_route_references(r) and r.key not in ROUTE_NO_TEST_WAIVERS
    ]
    unwaived = [r for r in missing if r.key not in ROUTE_NO_FULL_STACK_WAIVERS]
    assert not unwaived, (
        f"These endpoints are never exercised against a running server. {_SKIP_NOTE} "
        "Add a walk in tests/e2e/ (see test_remaining_surface.py for the pattern), or "
        "register a reasoned waiver in ROUTE_NO_FULL_STACK_WAIVERS:\n"
        + _fmt_missing([(r.key, r.literal_prefix) for r in unwaived])
    )


def test_route_full_stack_waivers_are_not_stale() -> None:
    """A waived route that now has a full-stack test must lose its waiver."""
    now_covered = [
        r.key
        for r in discover_routes()
        if r.key in ROUTE_NO_FULL_STACK_WAIVERS and full_stack_route_references(r)
    ]
    assert not now_covered, (
        "These routes now have full-stack tests — delete their "
        f"ROUTE_NO_FULL_STACK_WAIVERS entries:\n{_fmt(now_covered)}"
    )


def test_all_route_waivers_carry_a_reason() -> None:
    """Waivers document *why*; an empty reason is a silent skip."""
    blank = [
        k
        for reg in (ROUTE_NO_TEST_WAIVERS, ROUTE_NO_FULL_STACK_WAIVERS, CLI_WAIVERS)
        for k, v in reg.items()
        if not v or len(v.strip()) < 20
    ]
    assert not blank, f"Waivers need a substantive reason (>=20 chars):\n{_fmt(blank)}"


def test_waivers_reference_live_surface() -> None:
    """A waiver for a route/command that no longer exists is dead weight."""
    live_routes = {r.key for r in discover_routes()}
    live_cli = set(discover_cli_commands())
    dead = [k for k in ROUTE_NO_TEST_WAIVERS if k not in live_routes]
    dead += [k for k in ROUTE_NO_FULL_STACK_WAIVERS if k not in live_routes]
    dead += [k for k in CLI_WAIVERS if k not in live_cli]
    assert not dead, f"Waivers reference surface that no longer exists — delete them:\n{_fmt(dead)}"


# ---------------------------------------------------------------------------
# 3. Every nav view is walked in a browser
# ---------------------------------------------------------------------------


def test_every_nav_view_has_a_browser_test() -> None:
    """Each SPA view a user can open is opened by the harness."""
    missing = [v for v in discover_views() if not view_references(v)]
    assert not missing, (
        f"These nav views are never opened by a browser test. {_SKIP_NOTE} Every "
        "view a user can reach must be walked (and its render validated) in "
        "tests/e2e/:\n" + _fmt_missing([(v, v) for v in missing])
    )


# ---------------------------------------------------------------------------
# 4. Every CLI command is invoked by a test
# ---------------------------------------------------------------------------


def test_every_cli_command_has_a_test() -> None:
    """The CLI is the other half of the product surface."""
    missing = [c for c in discover_cli_commands() if not cli_references(c)]
    unwaived = [c for c in missing if c not in CLI_WAIVERS]
    assert not unwaived, (
        f"These CLI commands have no test invoking them. {_SKIP_NOTE} Add one "
        "(CliRunner or subprocess), or register a reasoned waiver in CLI_WAIVERS:\n"
        + _fmt_missing([(c, c) for c in unwaived])
    )


def test_cli_waivers_are_not_stale() -> None:
    """A waived command that is now tested must lose its waiver."""
    now_covered = [c for c in CLI_WAIVERS if c in discover_cli_commands() and cli_references(c)]
    assert not now_covered, (
        "These CLI commands are now tested — delete their CLI_WAIVERS "
        f"entries:\n{_fmt(now_covered)}"
    )


# ---------------------------------------------------------------------------
# 5. Every terminal-multiplexer backend has a session-lifecycle test
#
# `studyloop study` lays out the agent pane + sidebar in a multiplexer. The
# roadmap replaces tmux with herdr (https://github.com/herdrdev/herdr), and a
# swap of the whole session substrate is exactly the change that must not land
# untested. The backend set is introspected from the source tree, so adding
# `studyloop/herdr.py` fails this check until a lifecycle test exists for it.
# ---------------------------------------------------------------------------

#: Backends whose lifecycle test is deliberately absent, with the reason.
MULTIPLEXER_WAIVERS: dict[str, str] = {}


def test_every_multiplexer_backend_has_a_lifecycle_test() -> None:
    """Each multiplexer StudyLoop can drive is exercised by a test."""
    backends = discover_multiplexers()
    assert backends, (
        "no multiplexer backend module found under src/studyloop — either the "
        "detection list in e2e.surface is stale or session layout moved"
    )
    missing = [b for b in backends if not multiplexer_references(b)]
    unwaived = [b for b in missing if b not in MULTIPLEXER_WAIVERS]
    assert not unwaived, (
        f"These terminal-multiplexer backends have no test driving them. {_SKIP_NOTE} "
        "A new backend (e.g. the planned herdr replacement for tmux) must ship with a "
        "session-lifecycle test — start/attach/pane-layout/end — before it can "
        "become the default:\n" + _fmt_missing([(b, b) for b in unwaived])
    )


def test_multiplexer_waivers_are_not_stale() -> None:
    """A waived backend that is now tested must lose its waiver."""
    now_covered = [
        b for b in discover_multiplexers() if b in MULTIPLEXER_WAIVERS and multiplexer_references(b)
    ]
    assert not now_covered, (
        f"These multiplexers are now tested — delete their waivers:\n{_fmt(now_covered)}"
    )


# ---------------------------------------------------------------------------
# 6. Every render class is validated in a browser
# ---------------------------------------------------------------------------

#: The test function that proves each render class actually renders. The gate
#: asserts these exist, so deleting a render test breaks the build.
RENDER_PROOFS: dict[str, str] = {
    "html": "test_spa_html_renders_without_console_errors",
    "terminal": "test_terminal_paints_agent_bytes",
    "markdown": "test_lesson_markdown_renders_to_block_elements",
    "mermaid": "test_mermaid_fence_renders_to_svg",
}


@pytest.mark.parametrize("render_class", sorted(RENDER_SURFACES))
def test_render_class_has_a_named_proof_test(render_class: str) -> None:
    """html / terminal / markdown / mermaid each have a real render assertion."""
    proof = RENDER_PROOFS.get(render_class)
    assert proof, (
        f"Render class {render_class!r} ({RENDER_SURFACES[render_class]}) has "
        "no entry in RENDER_PROOFS — name the test that validates it."
    )
    hits = files_referencing(f"def {proof}(")
    assert hits, (
        f"Render class {render_class!r} claims to be proven by {proof}(), but "
        "no test module defines that function. Render validation must be a "
        f"real executable test. {_SKIP_NOTE}\n"
        f"Expected: {RENDER_SURFACES[render_class]}" + _inactive_note(f"def {proof}(")
    )


def test_render_proofs_cover_every_render_surface() -> None:
    """Adding a render class to the taxonomy forces a new proof test."""
    unproven = sorted(set(RENDER_SURFACES) - set(RENDER_PROOFS))
    assert not unproven, f"Render surfaces without a named proof test:\n{_fmt(unproven)}"
