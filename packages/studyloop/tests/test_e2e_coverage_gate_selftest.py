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
from e2e import surface  # noqa: E402
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


# ---------------------------------------------------------------------------
# The regression this whole change exists to prevent: quarantining the ONLY
# covering test for a surface must turn the gate RED. The control phase proves
# the very same test made the gate GREEN while unmarked, so the red result is
# attributable to the skip and nothing else.
# ---------------------------------------------------------------------------


def _clear_evidence_caches() -> None:
    surface._collect_test_items.cache_clear()
    surface._evidence_fragments_for.cache_clear()


def _eligible(fragments: tuple) -> tuple:
    return tuple(f for f in fragments if f.eligible)


def test_gate_goes_red_when_only_covering_test_is_skipped(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A skip on the sole covering test flips the gate from green to red.

    The route literal is built at runtime so this file's own source cannot
    satisfy the matcher, and the probe lives in its own tmp tree so it is
    collected in isolation from the real suite.
    """
    route = "/api/" + "zz-skip-probe-" + "route"
    fake = Route("GET", route)
    module = tmp_path / "test_skip_probe.py"

    unmarked = (
        "def test_probe() -> None:\n"
        f"    resp = client.get({route!r})  # noqa: F821\n"
        "    assert resp\n"
    )
    module.write_text(unmarked, encoding="utf-8")

    _clear_evidence_caches()
    frags_green = _eligible(surface._evidence_fragments_for(tmp_path))
    assert any(route in f.text for f in frags_green), (
        "the unmarked probe must supply route evidence — the control phase is "
        "only meaningful if the gate is genuinely green first"
    )

    monkeypatch.setattr(gate, "discover_routes", lambda: (fake,))
    monkeypatch.setattr(surface, "_evidence_fragments", lambda: frags_green)
    # CONTROL: unmarked → covered → the gate passes. Must not raise.
    gate.test_every_route_has_a_test()

    # Now quarantine the only covering test.
    skipped = (
        "import pytest\n\n"
        '@pytest.mark.skip(reason="quarantined panel journey")\n'
        "def test_probe() -> None:\n"
        f"    resp = client.get({route!r})  # noqa: F821\n"
        "    assert resp\n"
    )
    module.write_text(skipped, encoding="utf-8")

    _clear_evidence_caches()
    frags_red = _eligible(surface._evidence_fragments_for(tmp_path))
    assert not any(route in f.text for f in frags_red), (
        "a skipped test must not supply route evidence"
    )

    monkeypatch.setattr(surface, "_evidence_fragments", lambda: frags_red)
    with pytest.raises(AssertionError) as excinfo:
        gate.test_every_route_has_a_test()
    message = str(excinfo.value)
    assert route in message, "the failure must name the now-uncovered route"
    assert "do not count" in message, "the failure must explain that skipped tests do not count"

    # Leave the caches clean for the rest of the suite.
    _clear_evidence_caches()


# ---------------------------------------------------------------------------
# Collector-contract self-test: the SURFACE pipeline (subprocess collect + AST
# attribution) must reproduce pytest's marker semantics. Six cases, one
# collection. Literals are built at runtime so this file cannot match itself.
# ---------------------------------------------------------------------------

_MODULE_SKIP = """\
import pytest

pytestmark = pytest.mark.skip(reason="module-level pytestmark")


def test_module_level() -> None:
    assert "/api/TOKEN-module"
"""

_CLASS_SKIP = """\
import pytest


@pytest.mark.skip(reason="class-level skip")
class TestClass:
    def test_class_level(self) -> None:
        assert "/api/TOKEN-class"
"""

_PARAM_SKIP = """\
import pytest


@pytest.mark.parametrize(
    "route",
    [
        "/api/TOKEN-active",
        pytest.param("/api/TOKEN-skipped", marks=pytest.mark.skip(reason="param skipped")),
    ],
)
def test_param(route: str) -> None:
    assert route
"""

_SKIPIF = """\
import pytest


@pytest.mark.skipif(True, reason="condition true")
def test_skipif_true() -> None:
    assert "/api/TOKEN-skipif-true"


@pytest.mark.skipif(False, reason="condition false")
def test_skipif_false() -> None:
    assert "/api/TOKEN-skipif-false"
"""

_XFAIL = """\
import pytest


@pytest.mark.xfail(run=True, reason="runs but cannot fail the build")
def test_xfail() -> None:
    assert "/api/TOKEN-xfail"
"""


@pytest.fixture(scope="module")
def marker_probe(tmp_path_factory: pytest.TempPathFactory) -> tuple[str, tuple]:
    """Collect a directory of marker cases through the surface pipeline once."""
    token = "zz" + "-marker-probe-" + "xyzzy"
    workdir = tmp_path_factory.mktemp("marker_probe")
    for name, template in (
        ("test_module_skip.py", _MODULE_SKIP),
        ("test_class_skip.py", _CLASS_SKIP),
        ("test_param_skip.py", _PARAM_SKIP),
        ("test_skipif.py", _SKIPIF),
        ("test_xfail.py", _XFAIL),
    ):
        (workdir / name).write_text(template.replace("TOKEN", token), encoding="utf-8")

    surface._collect_test_items.cache_clear()
    surface._evidence_fragments_for.cache_clear()
    fragments = surface._evidence_fragments_for(workdir)
    # Do not leave the tmp collection cached for the real suite.
    surface._collect_test_items.cache_clear()
    surface._evidence_fragments_for.cache_clear()
    return token, fragments


@pytest.mark.parametrize(
    "case",
    [
        "module_pytestmark_skip",
        "class_level_skip",
        "parametrized_skip_and_active_sibling",
        "skipif_true",
        "skipif_false",
        "active_xfail",
    ],
)
def test_collector_marker_attribution(marker_probe: tuple[str, tuple], case: str) -> None:
    """Only items pytest can run AND fail contribute evidence."""
    token, fragments = marker_probe

    def has_evidence(suffix: str) -> bool:
        needle = f"/api/{token}{suffix}"
        return any(needle in f.text for f in fragments if f.eligible)

    if case == "module_pytestmark_skip":
        assert not has_evidence("-module"), "module-level pytestmark skip must not count"
    elif case == "class_level_skip":
        assert not has_evidence("-class"), "an inherited class-level skip must not count"
    elif case == "parametrized_skip_and_active_sibling":
        assert has_evidence("-active"), "the runnable parameter must remain evidence"
        assert not has_evidence("-skipped"), "the skip-marked parameter must not leak"
    elif case == "skipif_true":
        assert not has_evidence("-skipif-true"), "an active skipif must not count"
    elif case == "skipif_false":
        assert has_evidence("-skipif-false"), "an inactive skipif is still real coverage"
    elif case == "active_xfail":
        assert not has_evidence("-xfail"), "an xfail asserts breakage, not coverage"
    else:  # pragma: no cover - defensive
        raise AssertionError(f"unknown case {case!r}")
