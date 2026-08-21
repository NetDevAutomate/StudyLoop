"""Self-test for the coverage gate — proves the gate can actually fail.

A gate that passes no matter what is worse than no gate: it converts "untested"
into "certified". These tests inject synthetic surface (a route, a nav view, a
CLI command, a render class that nothing covers) and assert the corresponding
gate check *fails*. If the gate ever becomes vacuous — a matcher that always
finds a reference, a waiver list that swallows everything — these tests break.

Runs in the default selection alongside the gate itself.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_tests_dir = str(Path(__file__).resolve().parent)
if _tests_dir not in sys.path:
    sys.path.insert(0, _tests_dir)

import test_e2e_coverage_gate as gate  # noqa: E402
from e2e.surface import (  # noqa: E402
    Route,
    cli_references,
    full_stack_route_references,
    route_references,
    view_references,
)

# A surface that provably appears in no test module. The literal strings are
# built at runtime so this file's own source cannot satisfy the matchers.
_UNIQUE = "zz" + "-never-implemented-" + "surface"


def test_synthetic_route_has_no_references() -> None:
    """The route matcher does not hallucinate coverage for an unknown path."""
    fake = Route("GET", f"/api/{_UNIQUE}/{{id}}")
    assert route_references(fake) == (), (
        "route_references found 'coverage' for a route that does not exist — the "
        "matcher is too loose and the gate would pass anything"
    )
    assert full_stack_route_references(fake) == ()


def test_gate_fails_when_a_new_route_is_untested(monkeypatch: pytest.MonkeyPatch) -> None:
    """Adding an endpoint without a test breaks the build."""
    real = gate.discover_routes()
    fake = Route("POST", f"/api/{_UNIQUE}")
    monkeypatch.setattr(gate, "discover_routes", lambda: (*real, fake))

    with pytest.raises(AssertionError) as excinfo:
        gate.test_every_route_has_a_test()
    assert fake.key in str(excinfo.value)

    with pytest.raises(AssertionError):
        gate.test_every_route_has_a_full_stack_test()


def test_gate_fails_when_a_new_nav_view_is_unwalked(monkeypatch: pytest.MonkeyPatch) -> None:
    """Adding a view without a browser walk breaks the build."""
    real = gate.discover_views()
    monkeypatch.setattr(gate, "discover_views", lambda: (*real, _UNIQUE))
    assert view_references(_UNIQUE) == ()
    with pytest.raises(AssertionError) as excinfo:
        gate.test_every_nav_view_has_a_browser_test()
    assert _UNIQUE in str(excinfo.value)


def test_gate_fails_when_a_new_cli_command_is_untested(monkeypatch: pytest.MonkeyPatch) -> None:
    """Adding a CLI command without a test breaks the build."""
    real = gate.discover_cli_commands()
    command = f"{_UNIQUE} run"
    monkeypatch.setattr(gate, "discover_cli_commands", lambda: (*real, command))
    assert cli_references(command) == ()
    with pytest.raises(AssertionError) as excinfo:
        gate.test_every_cli_command_has_a_test()
    assert command in str(excinfo.value)


def test_gate_fails_when_a_render_class_has_no_proof(monkeypatch: pytest.MonkeyPatch) -> None:
    """Adding a render surface without a proof test breaks the build."""
    monkeypatch.setitem(gate.RENDER_SURFACES, _UNIQUE, "a new thing that must render")
    with pytest.raises(AssertionError):
        gate.test_render_proofs_cover_every_render_surface()
    with pytest.raises(AssertionError):
        gate.test_render_class_has_a_named_proof_test(_UNIQUE)


def test_gate_fails_on_a_named_proof_that_does_not_exist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A RENDER_PROOFS entry must name a test that really exists."""
    monkeypatch.setitem(gate.RENDER_PROOFS, "html", f"test_{_UNIQUE.replace('-', '_')}")
    with pytest.raises(AssertionError) as excinfo:
        gate.test_render_class_has_a_named_proof_test("html")
    assert "no test module defines that function" in str(excinfo.value)


def test_gate_fails_when_a_new_multiplexer_backend_is_untested(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Swapping the session substrate (tmux → herdr) cannot land untested.

    Simulates the herdr backend module appearing with no test driving it: the
    gate must refuse. This is the assertion that makes the planned tmux
    replacement a tested change by construction rather than by discipline.
    """
    real = gate.discover_multiplexers()
    monkeypatch.setattr(gate, "discover_multiplexers", lambda: (*real, _UNIQUE))
    with pytest.raises(AssertionError) as excinfo:
        gate.test_every_multiplexer_backend_has_a_lifecycle_test()
    assert _UNIQUE in str(excinfo.value)


def test_tmux_is_currently_the_detected_multiplexer() -> None:
    """Pins today's reality so the herdr migration is a visible diff.

    When `studyloop/herdr.py` lands this test is the reminder to update the
    expectation — and the gate above is what forces herdr to arrive with tests.
    """
    from e2e.surface import discover_multiplexers as discover

    backends = discover()
    assert "tmux" in backends, f"tmux backend module disappeared: {backends}"


def test_gate_rejects_a_waiver_without_a_reason(monkeypatch: pytest.MonkeyPatch) -> None:
    """A waiver cannot be a bare entry — it must justify itself."""
    monkeypatch.setitem(gate.CLI_WAIVERS, f"{_UNIQUE} cmd", "TODO")
    with pytest.raises(AssertionError):
        gate.test_all_route_waivers_carry_a_reason()


def test_gate_rejects_a_waiver_for_surface_that_does_not_exist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Dead waivers are flagged so the list cannot silently accumulate."""
    monkeypatch.setitem(
        gate.ROUTE_NO_FULL_STACK_WAIVERS,
        f"GET /api/{_UNIQUE}",
        "A reason long enough to pass the substantive-reason check.",
    )
    with pytest.raises(AssertionError):
        gate.test_waivers_reference_live_surface()


def test_gate_flags_a_stale_waiver(monkeypatch: pytest.MonkeyPatch) -> None:
    """Once a waived route is covered, the waiver must be removed."""
    covered = next(r for r in gate.discover_routes() if full_stack_route_references(r))
    monkeypatch.setitem(
        gate.ROUTE_NO_FULL_STACK_WAIVERS,
        covered.key,
        "A reason long enough to pass the substantive-reason check.",
    )
    with pytest.raises(AssertionError) as excinfo:
        gate.test_route_full_stack_waivers_are_not_stale()
    assert covered.key in str(excinfo.value)
