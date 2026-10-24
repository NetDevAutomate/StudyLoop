"""The OpenSpec split checker: a split may change the shape of a spec, never what it requires.

Drives ``scripts/check-openspec-split.py`` against fixture trees: a *base* tree (what the spec said
before a split) and a *head* tree (what a lane produced), each a bare ``openspec/`` directory. The
checker is what lets plan 7's lanes prove, per spec file, that splitting an overlong requirement
dropped, reworded, re-scoped or re-homed nothing without a named exception. Every fixture here is a
case the council (pass 9, ``ARBITRATION-pass9.md`` §3 and §8.2) said the checker must catch or must
honestly admit it cannot; the names F1-F15 are the council's.

The checker is loaded as a module (not run as a subprocess) so each rule is a plain assertion on its
report; one test proves the CLI entry point and exit codes.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Iterable

CHECKER = Path(__file__).resolve().parents[3] / "scripts" / "check-openspec-split.py"


@pytest.fixture(scope="module")
def checker():
    spec = importlib.util.spec_from_file_location("check_openspec_split", CHECKER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


# --------------------------------------------------------------------------------------------
# Fixture helpers
# --------------------------------------------------------------------------------------------


def _dedent_mixed(text: str) -> str:
    """Dedent by the first non-blank line's indent only; column-0 lines (the embedded
    ``SCENARIO_OK``) are left alone, which plain ``textwrap.dedent`` cannot do."""
    lines = text.split("\n")
    first = next((line for line in lines if line.strip()), "")
    indent = first[: len(first) - len(first.lstrip())]
    out = [line[len(indent) :] if indent and line.startswith(indent) else line for line in lines]
    return "\n".join(out).lstrip("\n")


def _write_spec(root: Path, spec_id: str, body: str) -> Path:
    path = root / "openspec" / "specs" / spec_id / "spec.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_dedent_mixed(body), encoding="utf-8")
    return path


def _write_exceptions(root: Path, toml_text: str) -> Path:
    path = root / "openspec" / ".split-exceptions.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(toml_text).lstrip("\n"), encoding="utf-8")
    return path


def _pair(tmp_path: Path) -> tuple[Path, Path]:
    base = tmp_path / "base"
    head = tmp_path / "head"
    (base / "openspec").mkdir(parents=True)
    (head / "openspec").mkdir(parents=True)
    return base, head


SCENARIO_OK = """
#### Scenario: Plan present
- **WHEN** the learner has an active plan
- **THEN** the engine shows the next milestone
"""


def _codes(report, spec_id: str | None = None) -> list[str]:
    findings = (
        report.findings if spec_id is None else [f for f in report.findings if f.spec == spec_id]
    )
    return sorted(f.code for f in findings)


def _run(checker, base: Path, head: Path, **kwargs):
    return checker.check_trees(base_root=base / "openspec", head_root=head / "openspec", **kwargs)


def _assert_only(report, codes: Iterable[str]) -> None:
    assert sorted(f.code for f in report.findings if f.level == "FAIL") == sorted(codes), [
        (f.code, f.detail) for f in report.findings
    ]


# --------------------------------------------------------------------------------------------
# Identity and the plain cases from the plan
# --------------------------------------------------------------------------------------------


def test_identical_trees_pass_with_no_findings(checker, tmp_path: Path) -> None:
    base, head = _pair(tmp_path)
    body = f"""
    # demo Specification

    ## Purpose
    A purpose someone wrote, long enough to clear the tool's minimum length for a purpose.

    ## Requirements
    ### Requirement: The engine shows the next milestone
    The engine SHALL show the next milestone.
    {SCENARIO_OK}
    """
    _write_spec(base, "demo", body)
    _write_spec(head, "demo", body)
    report = _run(checker, base, head)
    assert report.ok
    assert report.findings == []


def test_dropped_shall_fails(checker, tmp_path: Path) -> None:
    base, head = _pair(tmp_path)
    _write_spec(
        base,
        "demo",
        f"""
        # demo Specification
        ## Purpose
        A purpose someone wrote, long enough to clear the tool's minimum length for a purpose.
        ## Requirements
        ### Requirement: Two duties
        The engine SHALL show the next milestone.
        The engine SHALL never block on voice.
        {SCENARIO_OK}
        """,
    )
    _write_spec(
        head,
        "demo",
        f"""
        # demo Specification
        ## Purpose
        A purpose someone wrote, long enough to clear the tool's minimum length for a purpose.
        ## Requirements
        ### Requirement: Two duties
        The engine SHALL show the next milestone.
        {SCENARIO_OK}
        """,
    )
    report = _run(checker, base, head)
    assert not report.ok
    _assert_only(report, ["unit-lost"])
    (finding,) = [f for f in report.findings if f.code == "unit-lost"]
    assert "never block on voice" in finding.detail


def test_reworded_shall_without_exception_fails_and_with_exception_passes(
    checker, tmp_path: Path
) -> None:
    base, head = _pair(tmp_path)
    _write_spec(
        base,
        "demo",
        f"""
        # demo Specification
        ## Purpose
        A purpose someone wrote, long enough to clear the tool's minimum length for a purpose.
        ## Requirements
        ### Requirement: Milestone display
        It SHALL show the next milestone.
        {SCENARIO_OK}
        """,
    )
    _write_spec(
        head,
        "demo",
        f"""
        # demo Specification
        ## Purpose
        A purpose someone wrote, long enough to clear the tool's minimum length for a purpose.
        ## Requirements
        ### Requirement: Milestone display
        The engine SHALL show the next milestone.
        {SCENARIO_OK}
        """,
    )
    report = _run(checker, base, head)
    assert not report.ok
    assert "unit-lost" in _codes(report) and "unit-added" in _codes(report)

    _write_exceptions(
        head,
        """
        [[reference-expansion]]
        spec = "demo"
        heading = "Milestone display"
        ordinal = 1
        old = "It SHALL show the next milestone."
        new = "The engine SHALL show the next milestone."
        reason = "the pronoun lost its referent when the requirement was split"
        """,
    )
    report = _run(checker, base, head)
    assert report.ok, [(f.code, f.detail) for f in report.findings]


def test_unused_exception_is_itself_a_failure(checker, tmp_path: Path) -> None:
    base, head = _pair(tmp_path)
    body = f"""
    # demo Specification
    ## Purpose
    A purpose someone wrote, long enough to clear the tool's minimum length for a purpose.
    ## Requirements
    ### Requirement: Milestone display
    The engine SHALL show the next milestone.
    {SCENARIO_OK}
    """
    _write_spec(base, "demo", body)
    _write_spec(head, "demo", body)
    _write_exceptions(
        head,
        """
        [[reference-expansion]]
        spec = "demo"
        heading = "Milestone display"
        ordinal = 1
        old = "It SHALL show the next milestone."
        new = "The engine SHALL show the next milestone."
        reason = "never consumed"
        """,
    )
    report = _run(checker, base, head)
    assert not report.ok
    _assert_only(report, ["exception-unused"])


def test_dropped_scenario_fails(checker, tmp_path: Path) -> None:
    base, head = _pair(tmp_path)
    _write_spec(
        base,
        "demo",
        f"""
        # demo Specification
        ## Purpose
        A purpose someone wrote, long enough to clear the tool's minimum length for a purpose.
        ## Requirements
        ### Requirement: Milestone display
        The engine SHALL show the next milestone.
        {SCENARIO_OK}
        #### Scenario: No plan
        - **WHEN** there is no active plan
        - **THEN** nothing plan-related is shown
        """,
    )
    _write_spec(
        head,
        "demo",
        f"""
        # demo Specification
        ## Purpose
        A purpose someone wrote, long enough to clear the tool's minimum length for a purpose.
        ## Requirements
        ### Requirement: Milestone display
        The engine SHALL show the next milestone.
        {SCENARIO_OK}
        """,
    )
    report = _run(checker, base, head)
    assert not report.ok
    _assert_only(report, ["scenario-lost"])


def test_prose_hidden_in_a_fence_fails(checker, tmp_path: Path) -> None:
    """A fence is skipped by the tool's length measure, so prose moved into one dodges the limit."""
    base, head = _pair(tmp_path)
    _write_spec(
        base,
        "demo",
        f"""
        # demo Specification
        ## Purpose
        A purpose someone wrote, long enough to clear the tool's minimum length for a purpose.
        ## Requirements
        ### Requirement: Milestone display
        The engine SHALL show the next milestone.
        Scoring adds one bounded bias.
        {SCENARIO_OK}
        """,
    )
    _write_spec(
        head,
        "demo",
        f"""
        # demo Specification
        ## Purpose
        A purpose someone wrote, long enough to clear the tool's minimum length for a purpose.
        ## Requirements
        ### Requirement: Milestone display
        The engine SHALL show the next milestone.
        ```text
        Scoring adds one bounded bias.
        ```
        {SCENARIO_OK}
        """,
    )
    report = _run(checker, base, head)
    assert not report.ok
    assert "fence-added" in _codes(report)
    assert "unit-lost" in _codes(report)


def test_fragment_without_scenario_or_without_shall_fails_tool_rules(
    checker, tmp_path: Path
) -> None:
    base, head = _pair(tmp_path)
    _write_spec(
        base,
        "demo",
        f"""
        # demo Specification
        ## Purpose
        A purpose someone wrote, long enough to clear the tool's minimum length for a purpose.
        ## Requirements
        ### Requirement: Two duties
        The engine SHALL show the next milestone.
        Scoring adds one bounded bias.
        {SCENARIO_OK}
        """,
    )
    _write_spec(
        head,
        "demo",
        f"""
        # demo Specification
        ## Purpose
        A purpose someone wrote, long enough to clear the tool's minimum length for a purpose.
        ## Requirements
        ### Requirement: Two duties
        The engine SHALL show the next milestone.
        {SCENARIO_OK}
        ### Requirement: Two duties — scoring bias
        Scoring adds one bounded bias.
        """,
    )
    report = _run(checker, base, head)
    assert not report.ok
    codes = _codes(report)
    assert "tool-no-scenario" in codes
    assert "tool-no-shall" in codes


def test_body_over_500_by_the_tools_measure_fails(checker, tmp_path: Path) -> None:
    base, head = _pair(tmp_path)
    long_sentence = (
        "The engine SHALL " + ("keep every candidate it ranks visible " * 14).strip() + "."
    )
    assert len(long_sentence) > 500
    body = f"""
    # demo Specification
    ## Purpose
    A purpose someone wrote, long enough to clear the tool's minimum length for a purpose.
    ## Requirements
    ### Requirement: Long duty
    {long_sentence}
    {SCENARIO_OK}
    """
    _write_spec(base, "demo", body)
    _write_spec(head, "demo", body)
    report = _run(checker, base, head)
    assert not report.ok
    _assert_only(report, ["tool-body-too-long"])


# --------------------------------------------------------------------------------------------
# F1 — conditional lead-in lost (scope envelope travels)
# --------------------------------------------------------------------------------------------


def test_f1_conditional_lead_in_must_travel_with_every_governed_shall(
    checker, tmp_path: Path
) -> None:
    base, head = _pair(tmp_path)
    _write_spec(
        base,
        "demo",
        f"""
        # demo Specification
        ## Purpose
        A purpose someone wrote, long enough to clear the tool's minimum length for a purpose.
        ## Requirements
        ### Requirement: Plan-aware ranking
        When the learner has an active plan:
        - The engine SHALL show the plan's next milestone.
        - The engine SHALL mark the primary as plan-related.
        {SCENARIO_OK}
        #### Scenario: Primary marked
        - **WHEN** the primary matches the plan
        - **THEN** it is marked plan-related
        """,
    )
    _write_spec(
        head,
        "demo",
        f"""
        # demo Specification
        ## Purpose
        A purpose someone wrote, long enough to clear the tool's minimum length for a purpose.
        ## Requirements
        ### Requirement: Plan-aware ranking
        When the learner has an active plan:
        - The engine SHALL show the plan's next milestone.
        {SCENARIO_OK}
        ### Requirement: Plan-aware ranking — primary marking
        - The engine SHALL mark the primary as plan-related.
        #### Scenario: Primary marked
        - **WHEN** the primary matches the plan
        - **THEN** it is marked plan-related
        """,
    )
    report = _run(checker, base, head)
    assert not report.ok
    _assert_only(report, ["context-lost"])
    (finding,) = [f for f in report.findings if f.code == "context-lost"]
    assert "When the learner has an active plan:" in finding.detail

    # Duplicating the lead-in into the second fragment is the expected repair and is NOT a unit
    # change.
    _write_spec(
        head,
        "demo",
        f"""
        # demo Specification
        ## Purpose
        A purpose someone wrote, long enough to clear the tool's minimum length for a purpose.
        ## Requirements
        ### Requirement: Plan-aware ranking
        When the learner has an active plan:
        - The engine SHALL show the plan's next milestone.
        {SCENARIO_OK}
        ### Requirement: Plan-aware ranking — primary marking
        When the learner has an active plan:
        - The engine SHALL mark the primary as plan-related.
        #### Scenario: Primary marked
        - **WHEN** the primary matches the plan
        - **THEN** it is marked plan-related
        """,
    )
    report = _run(checker, base, head)
    assert report.ok, [(f.code, f.detail) for f in report.findings]


# --------------------------------------------------------------------------------------------
# F2 / F3 — keyword-less normative text is conserved too (opus O1)
# --------------------------------------------------------------------------------------------


def test_f2_list_item_under_a_shall_lead_in_cannot_move_into_a_scenario(
    checker, tmp_path: Path
) -> None:
    base, head = _pair(tmp_path)
    _write_spec(
        base,
        "demo",
        f"""
        # demo Specification
        ## Purpose
        A purpose someone wrote, long enough to clear the tool's minimum length for a purpose.
        ## Requirements
        ### Requirement: Ranking rules
        It SHALL apply these rules, in this order:
        1. A candidate is plan-related only on key equality.
        2. The engine SHALL defer a milestone above the energy floor.
        {SCENARIO_OK}
        """,
    )
    _write_spec(
        head,
        "demo",
        f"""
        # demo Specification
        ## Purpose
        A purpose someone wrote, long enough to clear the tool's minimum length for a purpose.
        ## Requirements
        ### Requirement: Ranking rules
        It SHALL apply these rules, in this order:
        2. The engine SHALL defer a milestone above the energy floor.
        {SCENARIO_OK}
        #### Scenario: Key equality
        - **WHEN** a candidate's key equals a plan key
        - **THEN** a candidate is plan-related only on key equality.
        """,
    )
    _write_exceptions(
        head,
        """
        [[moved-body-text]]
        spec = "demo"
        heading = "Ranking rules"
        ordinal = 2
        text = "A candidate is plan-related only on key equality."
        scenario = "Key equality"
        """,
    )
    report = _run(checker, base, head)
    assert not report.ok
    assert "inherited-normative-moved" in _codes(report)


def test_f3_keyword_less_prose_deleted_fails_unless_declared(checker, tmp_path: Path) -> None:
    base, head = _pair(tmp_path)
    _write_spec(
        base,
        "demo",
        f"""
        # demo Specification
        ## Purpose
        A purpose someone wrote, long enough to clear the tool's minimum length for a purpose.
        ## Requirements
        ### Requirement: Milestone display
        The engine SHALL show the next milestone.
        Scoring adds one bounded bias.
        {SCENARIO_OK}
        """,
    )
    _write_spec(
        head,
        "demo",
        f"""
        # demo Specification
        ## Purpose
        A purpose someone wrote, long enough to clear the tool's minimum length for a purpose.
        ## Requirements
        ### Requirement: Milestone display
        The engine SHALL show the next milestone.
        {SCENARIO_OK}
        """,
    )
    report = _run(checker, base, head)
    assert not report.ok
    _assert_only(report, ["unit-lost"])

    _write_exceptions(
        head,
        """
        [[deleted]]
        spec = "demo"
        heading = "Milestone display"
        ordinal = 2
        text = "Scoring adds one bounded bias."
        reason = "duplicated verbatim by the 'Bounded bias' requirement three lines below"
        """,
    )
    report = _run(checker, base, head)
    assert report.ok, [(f.code, f.detail) for f in report.findings]
    assert any(e.kind == "deleted" for e in report.drift)


# --------------------------------------------------------------------------------------------
# F4 — deictic reference orphaned; F6/F7 — self/structural references
# --------------------------------------------------------------------------------------------


def test_f4_deictic_reference_must_resolve_in_its_own_body(checker, tmp_path: Path) -> None:
    base, head = _pair(tmp_path)
    _write_spec(
        base,
        "demo",
        f"""
        # demo Specification
        ## Purpose
        A purpose someone wrote, long enough to clear the tool's minimum length for a purpose.
        ## Requirements
        ### Requirement: Tool registration
        Tools: `a`, `b`.
        The server SHALL register the list above.
        {SCENARIO_OK}
        """,
    )
    _write_spec(
        head,
        "demo",
        f"""
        # demo Specification
        ## Purpose
        A purpose someone wrote, long enough to clear the tool's minimum length for a purpose.
        ## Requirements
        ### Requirement: Tool registration
        The server SHALL register the list above.
        {SCENARIO_OK}
        #### Scenario: The tools
        - **WHEN** the server starts
        - **THEN** Tools: `a`, `b`.
        """,
    )
    _write_exceptions(
        head,
        """
        [[moved-body-text]]
        spec = "demo"
        heading = "Tool registration"
        ordinal = 1
        text = "Tools: `a`, `b`."
        scenario = "The tools"
        """,
    )
    report = _run(checker, base, head)
    assert not report.ok
    assert "orphaned-reference" in _codes(report)


@pytest.mark.parametrize(
    "phrase",
    [
        "Both transports SHALL follow this requirement identically.",
        "The nine tools of the two study-plan requirements in this specification SHALL be named.",
    ],
)
def test_f6_f7_self_and_structural_references_fail_once_the_requirement_is_split(
    checker, tmp_path: Path, phrase: str
) -> None:
    base, head = _pair(tmp_path)
    _write_spec(
        base,
        "demo",
        f"""
        # demo Specification
        ## Purpose
        A purpose someone wrote, long enough to clear the tool's minimum length for a purpose.
        ## Requirements
        ### Requirement: Transport parity
        The PTY transport SHALL deliver one envelope.
        The ACP transport SHALL deliver one envelope.
        {phrase}
        {SCENARIO_OK}
        """,
    )
    _write_spec(
        head,
        "demo",
        f"""
        # demo Specification
        ## Purpose
        A purpose someone wrote, long enough to clear the tool's minimum length for a purpose.
        ## Requirements
        ### Requirement: Transport parity
        The PTY transport SHALL deliver one envelope.
        {SCENARIO_OK}
        ### Requirement: Transport parity — ACP
        The ACP transport SHALL deliver one envelope.
        {phrase}
        #### Scenario: ACP
        - **WHEN** ACP is live
        - **THEN** one envelope arrives
        """,
    )
    report = _run(checker, base, head)
    assert not report.ok
    assert "orphaned-reference" in _codes(report)


# --------------------------------------------------------------------------------------------
# F5 — order; F8/F9 — headings
# --------------------------------------------------------------------------------------------


def test_f5_normative_order_is_preserved_across_fragments(checker, tmp_path: Path) -> None:
    base, head = _pair(tmp_path)
    _write_spec(
        base,
        "demo",
        f"""
        # demo Specification
        ## Purpose
        A purpose someone wrote, long enough to clear the tool's minimum length for a purpose.
        ## Requirements
        ### Requirement: Two steps
        The service SHALL authenticate the request.
        The service SHALL persist the request.
        {SCENARIO_OK}
        """,
    )
    _write_spec(
        head,
        "demo",
        f"""
        # demo Specification
        ## Purpose
        A purpose someone wrote, long enough to clear the tool's minimum length for a purpose.
        ## Requirements
        ### Requirement: Two steps
        The service SHALL persist the request.
        {SCENARIO_OK}
        ### Requirement: Two steps — authentication
        The service SHALL authenticate the request.
        #### Scenario: Auth
        - **WHEN** a request arrives
        - **THEN** it is authenticated
        """,
    )
    report = _run(checker, base, head)
    assert not report.ok
    assert "normative-order-changed" in _codes(report)


def test_f8_original_heading_must_survive_verbatim_exactly_once(checker, tmp_path: Path) -> None:
    base, head = _pair(tmp_path)
    _write_spec(
        base,
        "demo",
        f"""
        # demo Specification
        ## Purpose
        A purpose someone wrote, long enough to clear the tool's minimum length for a purpose.
        ## Requirements
        ### Requirement: Voice is optional and never blocks
        Voice SHALL be optional.
        {SCENARIO_OK}
        """,
    )
    _write_spec(
        head,
        "demo",
        f"""
        # demo Specification
        ## Purpose
        A purpose someone wrote, long enough to clear the tool's minimum length for a purpose.
        ## Requirements
        ### Requirement: Voice handling
        Voice SHALL be optional.
        {SCENARIO_OK}
        """,
    )
    report = _run(checker, base, head)
    assert not report.ok
    assert "heading-lost" in _codes(report)


def test_f9_compound_heading_split_is_reported_for_pass_10(checker, tmp_path: Path) -> None:
    """A heading with a conjunction stays on a fragment missing one conjunct: WARN, not FAIL."""
    base, head = _pair(tmp_path)
    _write_spec(
        base,
        "demo",
        f"""
        # demo Specification
        ## Purpose
        A purpose someone wrote, long enough to clear the tool's minimum length for a purpose.
        ## Requirements
        ### Requirement: Delivery reports six outcomes and no learner observation
        Delivery SHALL report exactly one of six outcomes.
        Nothing SHALL be written to learner history.
        {SCENARIO_OK}
        """,
    )
    _write_spec(
        head,
        "demo",
        f"""
        # demo Specification
        ## Purpose
        A purpose someone wrote, long enough to clear the tool's minimum length for a purpose.
        ## Requirements
        ### Requirement: Delivery reports six outcomes and no learner observation
        Delivery SHALL report exactly one of six outcomes.
        {SCENARIO_OK}
        ### Requirement: Delivery — learner history untouched
        Nothing SHALL be written to learner history.
        #### Scenario: History
        - **WHEN** delivery completes
        - **THEN** learner history is unchanged
        """,
    )
    _write_exceptions(
        head,
        """
        [[restates-shall]]
        spec = "demo"
        heading = "Delivery — learner history untouched"
        scenario = "History"
        restates = "Nothing SHALL be written to learner history."
        searched_tests = "none"
        """,
    )
    report = _run(checker, base, head)
    assert report.ok, [(f.code, f.detail) for f in report.findings]
    assert [f.code for f in report.findings if f.level == "WARN"] == ["compound-heading-split"]


def test_near_miss_heading_against_a_living_spec_fails(checker, tmp_path: Path) -> None:
    """Archive refuses an ADDED name that differs from a living one only in case or spacing."""
    base, head = _pair(tmp_path)
    living = f"""
    # web-ui Specification
    ## Purpose
    A purpose someone wrote, long enough to clear the tool's minimum length for a purpose.
    ## Requirements
    ### Requirement: Labs lists installed drills
    Labs SHALL list every installed module's drills.
    {SCENARIO_OK}
    """
    _write_spec(base, "web-ui", living)
    _write_spec(head, "web-ui", living)
    delta_base = """
    ## ADDED Requirements
    ### Requirement: Labs starts a drill in the claimed session
    Labs SHALL start the drill in the claimed session and SHALL refuse without a claim.
    #### Scenario: Start
    - **WHEN** the learner picks a drill
    - **THEN** it starts in the claimed session
    """
    delta_head = """
    ## ADDED Requirements
    ### Requirement: Labs starts a drill in the claimed session
    Labs SHALL start the drill in the claimed session.
    #### Scenario: Start
    - **WHEN** the learner picks a drill
    - **THEN** it starts in the claimed session
    ### Requirement: Labs  lists installed drills
    Labs SHALL refuse without a claim.
    #### Scenario: Refuse
    - **WHEN** there is no claim
    - **THEN** the start is refused
    """
    for root, text in ((base, delta_base), (head, delta_head)):
        p = root / "openspec" / "changes" / "mc" / "specs" / "web-ui" / "spec.md"
        p.parent.mkdir(parents=True)
        p.write_text(textwrap.dedent(text).lstrip("\n"), encoding="utf-8")
    _write_exceptions(
        head,
        """
        [[split-sentence]]
        spec = "changes/mc/web-ui"
        heading = "Labs starts a drill in the claimed session"
        ordinal = 1
        old = "Labs SHALL start the drill in the claimed session and SHALL refuse without a claim."
        new = [
            "Labs SHALL start the drill in the claimed session.",
            "Labs SHALL refuse without a claim.",
        ]
        added_tokens = ["Labs", "."]
        """,
    )
    report = _run(checker, base, head)
    assert not report.ok
    assert "archive-name-collision" in _codes(report)


# --------------------------------------------------------------------------------------------
# F10 — metadata laundering; F11 — mis-homed scenario (undetectable, reported)
# --------------------------------------------------------------------------------------------


def test_f10_turning_prose_into_a_metadata_line_fails(checker, tmp_path: Path) -> None:
    base, head = _pair(tmp_path)
    _write_spec(
        base,
        "demo",
        f"""
        # demo Specification
        ## Purpose
        A purpose someone wrote, long enough to clear the tool's minimum length for a purpose.
        ## Requirements
        ### Requirement: Milestone display
        The engine SHALL show the next milestone.
        Rule 4: scoring adds a bias.
        {SCENARIO_OK}
        """,
    )
    _write_spec(
        head,
        "demo",
        f"""
        # demo Specification
        ## Purpose
        A purpose someone wrote, long enough to clear the tool's minimum length for a purpose.
        ## Requirements
        ### Requirement: Milestone display
        The engine SHALL show the next milestone.
        **Rule 4**: scoring adds a bias.
        {SCENARIO_OK}
        """,
    )
    report = _run(checker, base, head)
    assert not report.ok
    assert "metadata-line-introduced" in _codes(report)


def test_f11_rehomed_scenario_is_silent_but_listed_in_the_drift_report(
    checker, tmp_path: Path
) -> None:
    base, head = _pair(tmp_path)
    _write_spec(
        base,
        "demo",
        f"""
        # demo Specification
        ## Purpose
        A purpose someone wrote, long enough to clear the tool's minimum length for a purpose.
        ## Requirements
        ### Requirement: Two duties
        The engine SHALL show the next milestone.
        The engine SHALL never block on voice.
        {SCENARIO_OK}
        #### Scenario: Voice down
        - **WHEN** voice is unavailable
        - **THEN** the engine keeps going
        """,
    )
    _write_spec(
        head,
        "demo",
        f"""
        # demo Specification
        ## Purpose
        A purpose someone wrote, long enough to clear the tool's minimum length for a purpose.
        ## Requirements
        ### Requirement: Two duties
        The engine SHALL show the next milestone.
        {SCENARIO_OK}
        ### Requirement: Two duties — voice never blocks
        The engine SHALL never block on voice.
        #### Scenario: Voice down
        - **WHEN** voice is unavailable
        - **THEN** the engine keeps going
        """,
    )
    report = _run(checker, base, head)
    assert report.ok, [(f.code, f.detail) for f in report.findings]
    rehomed = [e for e in report.drift if e.kind == "scenario-rehomed"]
    assert {e.name for e in rehomed} == {"Voice down"}
    assert "Two duties -> Two duties — voice never blocks" in rehomed[0].detail


# --------------------------------------------------------------------------------------------
# F14 — split-sentence; F15 / inherit-shall / scenario sources
# --------------------------------------------------------------------------------------------


def test_f14_split_sentence_passes_on_token_equality_and_fails_on_drift(
    checker, tmp_path: Path
) -> None:
    base, head = _pair(tmp_path)
    _write_spec(
        base,
        "demo",
        f"""
        # demo Specification
        ## Purpose
        A purpose someone wrote, long enough to clear the tool's minimum length for a purpose.
        ## Requirements
        ### Requirement: Registration
        The server SHALL register the tools and SHALL not expose a write tool.
        {SCENARIO_OK}
        """,
    )
    _write_spec(
        head,
        "demo",
        f"""
        # demo Specification
        ## Purpose
        A purpose someone wrote, long enough to clear the tool's minimum length for a purpose.
        ## Requirements
        ### Requirement: Registration
        The server SHALL register the tools.
        {SCENARIO_OK}
        ### Requirement: Registration — no write tool
        The server SHALL not expose a write tool.
        #### Scenario: No writes
        - **WHEN** the inventory is listed
        - **THEN** no write tool appears
        """,
    )
    _write_exceptions(
        head,
        """
        [[split-sentence]]
        spec = "demo"
        heading = "Registration"
        ordinal = 1
        old = "The server SHALL register the tools and SHALL not expose a write tool."
        new = ["The server SHALL register the tools.", "The server SHALL not expose a write tool."]
        added_tokens = ["The", "server", "."]

        [[restates-shall]]
        spec = "demo"
        heading = "Registration — no write tool"
        scenario = "No writes"
        restates = "The server SHALL not expose a write tool."
        searched_tests = "none"
        """,
    )
    report = _run(checker, base, head)
    assert report.ok, [(f.code, f.detail) for f in report.findings]
    assert any(e.kind == "split-sentence" for e in report.drift)

    # Dropping `not` through a fission is drift, however the entry is written.
    _write_spec(
        head,
        "demo",
        f"""
        # demo Specification
        ## Purpose
        A purpose someone wrote, long enough to clear the tool's minimum length for a purpose.
        ## Requirements
        ### Requirement: Registration
        The server SHALL register the tools.
        {SCENARIO_OK}
        ### Requirement: Registration — no write tool
        The server SHALL expose a write tool.
        #### Scenario: No writes
        - **WHEN** the inventory is listed
        - **THEN** no write tool appears
        """,
    )
    _write_exceptions(
        head,
        """
        [[split-sentence]]
        spec = "demo"
        heading = "Registration"
        ordinal = 1
        old = "The server SHALL register the tools and SHALL not expose a write tool."
        new = ["The server SHALL register the tools.", "The server SHALL expose a write tool."]
        added_tokens = ["The", "server", ".", "not"]

        [[restates-shall]]
        spec = "demo"
        heading = "Registration — no write tool"
        scenario = "No writes"
        restates = "The server SHALL expose a write tool."
        searched_tests = "none"
        """,
    )
    report = _run(checker, base, head)
    assert not report.ok
    assert "split-sentence-token-drift" in _codes(report)


def test_inherit_shall_adds_only_the_modal_and_subject(checker, tmp_path: Path) -> None:
    base, head = _pair(tmp_path)
    _write_spec(
        base,
        "demo",
        f"""
        # demo Specification
        ## Purpose
        A purpose someone wrote, long enough to clear the tool's minimum length for a purpose.
        ## Requirements
        ### Requirement: Ranking rules
        It SHALL apply these rules, in this order:
        1. A candidate is plan-related only on key equality.
        2. The engine SHALL defer a milestone above the energy floor.
        {SCENARIO_OK}
        """,
    )
    _write_spec(
        head,
        "demo",
        f"""
        # demo Specification
        ## Purpose
        A purpose someone wrote, long enough to clear the tool's minimum length for a purpose.
        ## Requirements
        ### Requirement: Ranking rules
        It SHALL apply these rules, in this order:
        2. The engine SHALL defer a milestone above the energy floor.
        {SCENARIO_OK}
        ### Requirement: Ranking rules — rule 1: plan-relatedness is key equality
        It SHALL apply these rules, in this order:
        1. A candidate SHALL be plan-related only on key equality.
        #### Scenario: Key equality
        - **WHEN** a candidate's key equals a plan key
        - **THEN** it is plan-related
        """,
    )
    _write_exceptions(
        head,
        """
        [[inherit-shall]]
        spec = "demo"
        heading = "Ranking rules"
        ordinal = 2
        old = "1. A candidate is plan-related only on key equality."
        new = "1. A candidate SHALL be plan-related only on key equality."

        [[list-split]]
        spec = "demo"
        heading = "Ranking rules"
        fragments = "rule 1 -> 'Ranking rules — rule 1: …'; rule 2 stays"

        [[restates-shall]]
        spec = "demo"
        heading = "Ranking rules — rule 1: plan-relatedness is key equality"
        scenario = "Key equality"
        restates = "1. A candidate SHALL be plan-related only on key equality."
        searched_tests = "grep -rn 'key equality' packages/studyloop/tests: no test"
        """,
    )
    report = _run(checker, base, head)
    assert report.ok, [(f.code, f.detail) for f in report.findings]
    kinds = [e.kind for e in report.drift]
    assert "inherit-shall" in kinds and "restates-shall" in kinds


def test_f15_restates_shall_may_not_add_a_literal_absent_from_its_body(
    checker, tmp_path: Path
) -> None:
    base, head = _pair(tmp_path)
    _write_spec(
        base,
        "demo",
        f"""
        # demo Specification
        ## Purpose
        A purpose someone wrote, long enough to clear the tool's minimum length for a purpose.
        ## Requirements
        ### Requirement: Two duties
        The reply SHALL be awaited up to the bound.
        The engine SHALL never block on voice.
        {SCENARIO_OK}
        """,
    )
    _write_spec(
        head,
        "demo",
        f"""
        # demo Specification
        ## Purpose
        A purpose someone wrote, long enough to clear the tool's minimum length for a purpose.
        ## Requirements
        ### Requirement: Two duties
        The engine SHALL never block on voice.
        {SCENARIO_OK}
        ### Requirement: Two duties — bounded wait
        The reply SHALL be awaited up to the bound.
        #### Scenario: Bounded wait
        - **WHEN** the agent is slow
        - **THEN** the reply is awaited up to the bound, `120` seconds
        """,
    )
    _write_exceptions(
        head,
        """
        [[restates-shall]]
        spec = "demo"
        heading = "Two duties — bounded wait"
        scenario = "Bounded wait"
        restates = "The reply SHALL be awaited up to the bound."
        searched_tests = "none"
        """,
    )
    report = _run(checker, base, head)
    assert not report.ok
    assert "restates-shall-adds-literal" in _codes(report)


def test_test_sourced_scenario_must_name_a_collected_nodeid(checker, tmp_path: Path) -> None:
    base, head = _pair(tmp_path)
    _write_spec(
        base,
        "demo",
        f"""
        # demo Specification
        ## Purpose
        A purpose someone wrote, long enough to clear the tool's minimum length for a purpose.
        ## Requirements
        ### Requirement: Two duties
        The reply SHALL be awaited up to the bound.
        The engine SHALL never block on voice.
        {SCENARIO_OK}
        """,
    )
    _write_spec(
        head,
        "demo",
        f"""
        # demo Specification
        ## Purpose
        A purpose someone wrote, long enough to clear the tool's minimum length for a purpose.
        ## Requirements
        ### Requirement: Two duties
        The reply SHALL be awaited up to the bound.
        #### Scenario: Bounded wait
        - **WHEN** the agent is slow
        - **THEN** the reply is awaited up to the bound
        ### Requirement: Two duties — voice
        The engine SHALL never block on voice.
        {SCENARIO_OK}
        """,
    )
    _write_exceptions(
        head,
        """
        [[test-sourced]]
        spec = "demo"
        heading = "Two duties"
        scenario = "Bounded wait"
        test = "packages/studyloop/tests/test_demo.py::test_bounded_wait"
        """,
    )
    collected = tmp_path / "collected.txt"
    collected.write_text(
        "packages/studyloop/tests/test_other.py::test_something\n", encoding="utf-8"
    )
    report = _run(checker, base, head, collected_nodeids=collected)
    assert not report.ok
    assert "test-nodeid-unresolved" in _codes(report)

    collected.write_text(
        "packages/studyloop/tests/test_demo.py::test_bounded_wait\n", encoding="utf-8"
    )
    report = _run(checker, base, head, collected_nodeids=collected)
    assert report.ok, [(f.code, f.detail) for f in report.findings]


def test_duplicate_scenario_names_within_a_spec_file_fail(checker, tmp_path: Path) -> None:
    base, head = _pair(tmp_path)
    _write_spec(
        base,
        "demo",
        f"""
        # demo Specification
        ## Purpose
        A purpose someone wrote, long enough to clear the tool's minimum length for a purpose.
        ## Requirements
        ### Requirement: Two duties
        The reply SHALL be awaited up to the bound.
        The engine SHALL never block on voice.
        {SCENARIO_OK}
        """,
    )
    _write_spec(
        head,
        "demo",
        f"""
        # demo Specification
        ## Purpose
        A purpose someone wrote, long enough to clear the tool's minimum length for a purpose.
        ## Requirements
        ### Requirement: Two duties
        The engine SHALL never block on voice.
        {SCENARIO_OK}
        ### Requirement: Two duties — bounded wait
        The reply SHALL be awaited up to the bound.
        #### Scenario: Plan present
        - **WHEN** the agent is slow
        - **THEN** the reply is awaited up to the bound
        """,
    )
    _write_exceptions(
        head,
        """
        [[restates-shall]]
        spec = "demo"
        heading = "Two duties — bounded wait"
        scenario = "Plan present"
        restates = "The reply SHALL be awaited up to the bound."
        searched_tests = "none"
        """,
    )
    report = _run(checker, base, head)
    assert not report.ok
    assert "scenario-name-duplicate" in _codes(report)


# --------------------------------------------------------------------------------------------
# Purpose, fences anchored, positional citations
# --------------------------------------------------------------------------------------------


def test_purpose_change_must_be_declared(checker, tmp_path: Path) -> None:
    base, head = _pair(tmp_path)
    _write_spec(
        base,
        "demo",
        f"""
        # demo Specification
        ## Purpose
        TBD - created by archiving change complete-e2e-harness. Update Purpose after archive.
        ## Requirements
        ### Requirement: Milestone display
        The engine SHALL show the next milestone.
        {SCENARIO_OK}
        """,
    )
    _write_spec(
        head,
        "demo",
        f"""
        # demo Specification
        ## Purpose
        The representative journey proves a learner can start, study and end a session end to end.
        ## Requirements
        ### Requirement: Milestone display
        The engine SHALL show the next milestone.
        {SCENARIO_OK}
        """,
    )
    report = _run(checker, base, head)
    assert not report.ok
    _assert_only(report, ["purpose-changed"])
    report = _run(checker, base, head, purpose_rewritten={"demo"})
    assert report.ok, [(f.code, f.detail) for f in report.findings]


def test_fence_must_stay_anchored_to_its_obligation(checker, tmp_path: Path) -> None:
    base, head = _pair(tmp_path)
    _write_spec(
        base,
        "demo",
        f"""
        # demo Specification
        ## Purpose
        A purpose someone wrote, long enough to clear the tool's minimum length for a purpose.
        ## Requirements
        ### Requirement: Two duties
        The payload SHALL carry these fields.
        ```json
        {{"source": "body_double"}}
        ```
        The engine SHALL never block on voice.
        {SCENARIO_OK}
        """,
    )
    _write_spec(
        head,
        "demo",
        f"""
        # demo Specification
        ## Purpose
        A purpose someone wrote, long enough to clear the tool's minimum length for a purpose.
        ## Requirements
        ### Requirement: Two duties
        The payload SHALL carry these fields.
        {SCENARIO_OK}
        ### Requirement: Two duties — voice
        The engine SHALL never block on voice.
        ```json
        {{"source": "body_double"}}
        ```
        #### Scenario: Voice
        - **WHEN** voice is down
        - **THEN** the engine continues
        """,
    )
    report = _run(checker, base, head)
    assert not report.ok
    assert "fence-moved" in _codes(report)


def test_positional_scenario_citation_to_a_split_file_fails(checker, tmp_path: Path) -> None:
    base, head = _pair(tmp_path)
    body_base = f"""
    # web-ui Specification
    ## Purpose
    A purpose someone wrote, long enough to clear the tool's minimum length for a purpose.
    ## Requirements
    ### Requirement: Labs
    Labs SHALL list drills.
    Labs SHALL start drills.
    {SCENARIO_OK}
    """
    body_head = f"""
    # web-ui Specification
    ## Purpose
    A purpose someone wrote, long enough to clear the tool's minimum length for a purpose.
    ## Requirements
    ### Requirement: Labs
    Labs SHALL list drills.
    {SCENARIO_OK}
    ### Requirement: Labs — start
    Labs SHALL start drills.
    #### Scenario: Start
    - **WHEN** a drill is picked
    - **THEN** it starts
    """
    _write_spec(base, "web-ui", body_base)
    _write_spec(head, "web-ui", body_head)
    _write_exceptions(
        head,
        """
        [[restates-shall]]
        spec = "web-ui"
        heading = "Labs — start"
        scenario = "Start"
        restates = "Labs SHALL start drills."
        searched_tests = "none"
        """,
    )
    src = head / "packages" / "studyloop" / "src" / "mod.py"
    src.parent.mkdir(parents=True)
    # built from parts so the repo-wide sweep does not read this fixture as a real citation
    positional = "scenario" + " 2"
    src.write_text(f'"""Lists drills (web-ui spec {positional})."""\n', encoding="utf-8")
    report = _run(checker, base, head, citation_roots=[head / "packages"])
    assert not report.ok
    assert "positional-citation" in _codes(report)


# --------------------------------------------------------------------------------------------
# Tool parity and the CLI entry point
# --------------------------------------------------------------------------------------------


def test_body_length_matches_the_installed_tools_measure(checker, tmp_path: Path) -> None:
    """The checker's body measure is the tool's: fences and blanks skipped, lines trimmed, joined
    with newlines."""
    text = textwrap.dedent(
        """
        ### Requirement: Measured
        The engine SHALL do a thing.

           Indented second line.
        ```python
        not counted at all
        ```
        **ID**: metadata-only-when-prose-exists
        #### Scenario: S
        - **WHEN** x
        - **THEN** y
        """
    ).lstrip("\n")
    body = checker.requirement_body(text.splitlines()[1:])
    assert body == "The engine SHALL do a thing.\nIndented second line."
    assert checker.body_length(body) == len(body)


def test_cli_exit_codes_and_json_report(checker, tmp_path: Path) -> None:
    base, head = _pair(tmp_path)
    body = f"""
    # demo Specification
    ## Purpose
    A purpose someone wrote, long enough to clear the tool's minimum length for a purpose.
    ## Requirements
    ### Requirement: Milestone display
    The engine SHALL show the next milestone.
    {SCENARIO_OK}
    """
    _write_spec(base, "demo", body)
    _write_spec(head, "demo", body)
    out = tmp_path / "report.json"
    proc = subprocess.run(
        [
            sys.executable,
            str(CHECKER),
            "--base-dir",
            str(base / "openspec"),
            "--head-dir",
            str(head / "openspec"),
            "--json",
            str(out),
        ],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["ok"] is True and data["findings"] == []

    _write_spec(
        head,
        "demo",
        f"""
        # demo Specification
        ## Purpose
        A purpose someone wrote, long enough to clear the tool's minimum length for a purpose.
        ## Requirements
        ### Requirement: Milestone display
        The engine SHALL show the previous milestone.
        {SCENARIO_OK}
        """,
    )
    proc = subprocess.run(
        [
            sys.executable,
            str(CHECKER),
            "--base-dir",
            str(base / "openspec"),
            "--head-dir",
            str(head / "openspec"),
        ],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert proc.returncode == 1
    assert "unit-lost" in proc.stdout and "Milestone display" in proc.stdout


# --------------------------------------------------------------------------------------------
# Differential parity with the installed OpenSpec CLI (ARBITRATION-pass9 §3 rule 9)
# --------------------------------------------------------------------------------------------

_PURPOSE = "A purpose someone wrote, long enough to clear the tool's minimum length for a purpose."
_SCENARIO = "#### Scenario: S\n- **WHEN** x\n- **THEN** y\n"
PARITY_CASES: dict[str, str] = {
    "p-plain": "The engine SHALL do a thing.\n" + _SCENARIO,
    "p-fenced-header": (
        "The engine SHALL do a thing.\n```md\n#### Scenario: not a scenario\n```\n" + _SCENARIO
    ),
    "p-tilde-fence": "The engine SHALL do a thing.\n~~~\n### Requirement: fake\n~~~\n" + _SCENARIO,
    "p-metadata-only": "**Constraint**: The system MUST do a thing.\n" + _SCENARIO,
    "p-metadata-with-prose": "**ID**: R1\nThe engine SHALL do a thing.\n" + _SCENARIO,
    "p-level4-no-scenario-word": (
        "The engine SHALL do a thing.\n#### Edge case\n- **WHEN** x\n- **THEN** y\n"
    ),
    "p-empty-scenario-body": "The engine SHALL do a thing.\n#### Scenario: Empty\n" + _SCENARIO,
    "p-no-shall": "The engine does a thing.\n" + _SCENARIO,
    "p-no-scenario": "The engine SHALL do a thing.\n",
    "p-exactly-500": "The engine SHALL " + "x" * 482 + ".\n" + _SCENARIO,
    "p-501": "The engine SHALL " + "x" * 483 + ".\n" + _SCENARIO,
    "p-long-fence-not-counted": "The engine SHALL do a thing.\n```\n"
    + "z" * 600
    + "\n```\n"
    + _SCENARIO,
    "p-indented-lines": "The engine SHALL do\n    a thing with indented continuation.\n"
    + _SCENARIO,
    "p-shall-lowercase": "The engine shall do a thing.\n" + _SCENARIO,
    "p-must-in-code-span": "The engine `MUST` do a thing.\n" + _SCENARIO,
}


def _tool_codes(item: dict) -> set[str]:
    out: set[str] = set()
    for issue in item["issues"]:
        msg = issue["message"]
        if "very long" in msg:
            out.add("tool-body-too-long")
        elif "at least one scenario" in msg:
            out.add("tool-no-scenario")
        elif "SHALL" in msg or "MUST" in msg:
            out.add("tool-no-shall")
        elif issue["level"] != "INFO":
            out.add("OTHER:" + msg[:40])
    return out


def test_tool_rules_agree_with_the_installed_openspec_cli(checker, tmp_path: Path) -> None:
    """The checker's body measure, keyword and scenario rules must match the real validator on every
    parser boundary; a drift here is exactly the risk the council ranked second."""
    import shutil

    if shutil.which("openspec") is None:
        pytest.skip("openspec CLI not installed; the recipe skips too (CI runs it)")
    root = tmp_path / "parity"
    for cid, body in PARITY_CASES.items():
        d = root / "openspec" / "specs" / cid
        d.mkdir(parents=True)
        (d / "spec.md").write_text(
            f"# {cid} Specification\n\n## Purpose\n{_PURPOSE}\n\n## Requirements\n"
            f"### Requirement: R\n{body}",
            encoding="utf-8",
        )
    proc = subprocess.run(
        ["openspec", "validate", "--specs", "--all", "--strict", "--json", "--no-interactive"],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
        env={**__import__("os").environ, "OPENSPEC_TELEMETRY": "0"},
    )
    tool = {item["id"]: item for item in json.loads(proc.stdout)["items"]}
    report = checker.check_trees(base_root=root / "openspec", head_root=root / "openspec")
    mine: dict[str, set[str]] = {}
    for f in report.findings:
        mine.setdefault(f.spec, set()).add(f.code)
    disagreements = {
        cid: (sorted(_tool_codes(tool[cid])), sorted(mine.get(cid, set())))
        for cid in PARITY_CASES
        if _tool_codes(tool[cid]) != mine.get(cid, set())
    }
    assert disagreements == {}, disagreements
    # the 500 boundary is strict `>`: a 500-char body passes, 501 fails, on both sides
    assert "tool-body-too-long" not in mine.get("p-exactly-500", set())
    assert "tool-body-too-long" in mine["p-501"]


# --------------------------------------------------------------------------------------------
# Lane E ruling correction 2: a cross-requirement re-home must be declarable and declared
# --------------------------------------------------------------------------------------------


def test_scenario_moved_to_a_different_original_requirement_needs_a_declared_rehome(
    checker, tmp_path: Path
) -> None:
    """Re-homing within the fragments of one original requirement is routine (a drift note).
    Moving an unchanged scenario under a *different* original requirement changes what the
    scenario claims to prove, so it fails until a `[[scenario-rehome]]` entry names the move,
    and that entry is consumed (not reported unused)."""
    base, head = _pair(tmp_path)
    _write_spec(
        base,
        "demo",
        f"""
        # demo Specification
        ## Purpose
        A purpose someone wrote, long enough to clear the tool's minimum length for a purpose.
        ## Requirements
        ### Requirement: Delivery
        The envelope SHALL be delivered once.
        {SCENARIO_OK}
        #### Scenario: ACP keeps order
        - **WHEN** two prompts are queued
        - **THEN** they reach the agent in order
        ### Requirement: Ordering
        Prompts SHALL go to the agent in the order their callers asked.
        #### Scenario: Order
        - **WHEN** callers race
        - **THEN** the order is the callers' order
        """,
    )
    _write_spec(
        head,
        "demo",
        f"""
        # demo Specification
        ## Purpose
        A purpose someone wrote, long enough to clear the tool's minimum length for a purpose.
        ## Requirements
        ### Requirement: Delivery
        The envelope SHALL be delivered once.
        {SCENARIO_OK}
        ### Requirement: Ordering
        Prompts SHALL go to the agent in the order their callers asked.
        #### Scenario: Order
        - **WHEN** callers race
        - **THEN** the order is the callers' order
        #### Scenario: ACP keeps order
        - **WHEN** two prompts are queued
        - **THEN** they reach the agent in order
        """,
    )
    report = _run(checker, base, head)
    assert not report.ok
    _assert_only(report, ["scenario-rehomed-across-requirements"])

    _write_exceptions(
        head,
        """
        [[scenario-rehome]]
        spec = "demo"
        scenario = "ACP keeps order"
        from = "Delivery"
        to = "Ordering"
        test = "packages/studyloop/tests/test_demo.py::test_acp_order"
        reason = "the scenario exercises the ordering rule, not delivery"
        """,
    )
    report = _run(checker, base, head)
    assert report.ok, [(f.code, f.detail) for f in report.findings]
    assert any(e.kind == "scenario-rehome" for e in report.drift)


# --------------------------------------------------------------------------------------------
# Lane D ruling: an indicative keyword-less sentence that cannot share a fragment with its SHALL
# may become a body of its own by inserting the modal and de-inflecting exactly one finite verb
# --------------------------------------------------------------------------------------------


def test_modalise_inserts_the_modal_and_changes_exactly_one_verb(checker, tmp_path: Path) -> None:
    base, head = _pair(tmp_path)
    _write_spec(
        base,
        "demo",
        f"""
        # demo Specification
        ## Purpose
        A purpose someone wrote, long enough to clear the tool's minimum length for a purpose.
        ## Requirements
        ### Requirement: Orphan cleanup
        `auto_clean_zombies()` SHALL run at the start of every invocation.
        It delegates the decision to `plan_clean()` and executes the plan.
        {SCENARIO_OK}
        """,
    )
    _write_spec(
        head,
        "demo",
        f"""
        # demo Specification
        ## Purpose
        A purpose someone wrote, long enough to clear the tool's minimum length for a purpose.
        ## Requirements
        ### Requirement: Orphan cleanup
        `auto_clean_zombies()` SHALL run at the start of every invocation.
        {SCENARIO_OK}
        ### Requirement: Orphan cleanup — the plan is delegated and executed
        It SHALL delegate the decision to `plan_clean()` and executes the plan.
        #### Scenario: Plan executed
        - **WHEN** zombies are identified
        - **THEN** the plan from `plan_clean()` is executed
        """,
    )
    # without an entry the rewritten sentence is a lost unit plus an added one
    report = _run(checker, base, head)
    assert not report.ok
    assert "unit-lost" in _codes(report)

    _write_exceptions(
        head,
        """
        [[modalise]]
        spec = "demo"
        heading = "Orphan cleanup"
        ordinal = 2
        old = "It delegates the decision to `plan_clean()` and executes the plan."
        new = "It SHALL delegate the decision to `plan_clean()` and executes the plan."
        verb = ["delegates", "delegate"]
        reason = "cannot share a fragment with its SHALL sibling (585 together); not an example"

        [[restates-shall]]
        spec = "demo"
        heading = "Orphan cleanup — the plan is delegated and executed"
        scenario = "Plan executed"
        restates = "It SHALL delegate the decision to `plan_clean()` and executes the plan."
        searched_tests = "none"
        """,
    )
    report = _run(checker, base, head)
    assert report.ok, [(f.code, f.detail) for f in report.findings]
    assert any(e.kind == "modalise" for e in report.drift)

    # changing a second word (here `executes` -> `never executes`) is drift, whatever the entry says
    _write_spec(
        head,
        "demo",
        f"""
        # demo Specification
        ## Purpose
        A purpose someone wrote, long enough to clear the tool's minimum length for a purpose.
        ## Requirements
        ### Requirement: Orphan cleanup
        `auto_clean_zombies()` SHALL run at the start of every invocation.
        {SCENARIO_OK}
        ### Requirement: Orphan cleanup — the plan is delegated and executed
        It SHALL delegate the decision to `plan_clean()` and never executes the plan.
        #### Scenario: Plan executed
        - **WHEN** zombies are identified
        - **THEN** the plan from `plan_clean()` is executed
        """,
    )
    _write_exceptions(
        head,
        """
        [[modalise]]
        spec = "demo"
        heading = "Orphan cleanup"
        ordinal = 2
        old = "It delegates the decision to `plan_clean()` and executes the plan."
        new = "It SHALL delegate the decision to `plan_clean()` and never executes the plan."
        verb = ["delegates", "delegate"]
        reason = "smuggling a negation"

        [[restates-shall]]
        spec = "demo"
        heading = "Orphan cleanup — the plan is delegated and executed"
        scenario = "Plan executed"
        restates = "It SHALL delegate the decision to `plan_clean()` and never executes the plan."
        searched_tests = "none"
        """,
    )
    report = _run(checker, base, head)
    assert not report.ok
    assert "modalise-token-drift" in _codes(report)


# --------------------------------------------------------------------------------------------
# Lane D checker findings: double-backtick code spans; compound-heading WARN after a fission
# --------------------------------------------------------------------------------------------


def test_double_backtick_code_span_does_not_swallow_the_rest_of_the_paragraph(checker) -> None:
    """A `` `` ` `` `` span (a literal backtick in a code span) must close on the same run of
    backticks, otherwise every sentence after it is fused into one unit and the ordinals that
    exception entries address are wrong (lane D found the real case in "Session purpose")."""
    text = (
        "On a start the dump SHALL be rendered as a fourth section whose lines keep a leading "
        "block marker (`#`, `-`, `*`, `+`, `>`, `` ` ``, `~`) out of column one. "
        "Z SHALL stop. "
        "Y SHALL go. "
        "The topic string SHALL never determine the purpose."
    )
    units = checker._sentences(text)
    assert len(units) == 4, units
    assert units[1:] == [
        "Z SHALL stop.",
        "Y SHALL go.",
        "The topic string SHALL never determine the purpose.",
    ]


def test_compound_heading_split_is_reported_even_when_the_first_sentence_was_fissioned(
    checker, tmp_path: Path
) -> None:
    base, head = _pair(tmp_path)
    long_first = "Session end SHALL flush the summary and SHALL clear the IPC files."
    _write_spec(
        base,
        "demo",
        f"""
        # demo Specification
        ## Purpose
        A purpose someone wrote, long enough to clear the tool's minimum length for a purpose.
        ## Requirements
        ### Requirement: Session end flushes summary to DB and clears IPC files
        {long_first}
        {SCENARIO_OK}
        """,
    )
    _write_spec(
        head,
        "demo",
        f"""
        # demo Specification
        ## Purpose
        A purpose someone wrote, long enough to clear the tool's minimum length for a purpose.
        ## Requirements
        ### Requirement: Session end flushes summary to DB and clears IPC files
        Session end SHALL flush the summary.
        {SCENARIO_OK}
        ### Requirement: Session end — IPC files are cleared
        Session end SHALL clear the IPC files.
        #### Scenario: IPC cleared
        - **WHEN** the session ends
        - **THEN** no IPC file remains
        """,
    )
    _write_exceptions(
        head,
        f"""
        [[split-sentence]]
        spec = "demo"
        heading = "Session end flushes summary to DB and clears IPC files"
        ordinal = 1
        old = "{long_first}"
        new = [
            "Session end SHALL flush the summary.",
            "Session end SHALL clear the IPC files.",
        ]
        added_tokens = ["Session", "end", "."]

        [[restates-shall]]
        spec = "demo"
        heading = "Session end — IPC files are cleared"
        scenario = "IPC cleared"
        restates = "Session end SHALL clear the IPC files."
        searched_tests = "none"
        """,
    )
    report = _run(checker, base, head)
    assert report.ok, [(f.code, f.detail) for f in report.findings]
    assert [f.code for f in report.findings if f.level == "WARN"] == ["compound-heading-split"]


# --------------------------------------------------------------------------------------------
# Lane B rulings: tables, lead-in scope, restated lead-ins
# --------------------------------------------------------------------------------------------

TABLE_BASE = """
# demo Specification
## Purpose
A purpose someone wrote, long enough to clear the tool's minimum length for a purpose.
## Requirements
### Requirement: Study-plan tools
`register_tools(mcp)` SHALL register three study-plan tools, each a thin seam adapter:

| Tool | Seam call |
|---|---|
| `list_study_plans()` | `browse()` |
| `get_study_plan(id)` | `inspect(id)` |
| `delete_study_plan(id)` | `apply(DeletePlan(id))` |

Every response SHALL be the seam view's `to_json_dict()`.

#### Scenario: Discover
- **WHEN** `list_study_plans()` is called
- **THEN** `browse()` answers
#### Scenario: Delete
- **WHEN** `delete_study_plan` is called
- **THEN** `apply(DeletePlan)` runs
"""


def test_table_rows_are_governed_units_and_header_rows_are_duplicable_structure(
    checker, tmp_path: Path
) -> None:
    """One fragment per tool: the lead-in and the table's header + delimiter are repeated, the
    rows are distributed. No unit is lost or added; a governed row moved into a scenario is a
    demotion."""
    base, head = _pair(tmp_path)
    _write_spec(base, "demo", TABLE_BASE)
    _write_spec(
        head,
        "demo",
        """
        # demo Specification
        ## Purpose
        A purpose someone wrote, long enough to clear the tool's minimum length for a purpose.
        ## Requirements
        ### Requirement: Study-plan tools
        `register_tools(mcp)` SHALL register three study-plan tools, each a thin seam adapter:

        | Tool | Seam call |
        |---|---|
        | `list_study_plans()` | `browse()` |
        | `get_study_plan(id)` | `inspect(id)` |

        #### Scenario: Discover
        - **WHEN** `list_study_plans()` is called
        - **THEN** `browse()` answers
        ### Requirement: Study-plan tools — `delete_study_plan`
        `register_tools(mcp)` SHALL register three study-plan tools, each a thin seam adapter:

        | Tool | Seam call |
        |---|---|
        | `delete_study_plan(id)` | `apply(DeletePlan(id))` |

        Every response SHALL be the seam view's `to_json_dict()`.
        #### Scenario: Delete
        - **WHEN** `delete_study_plan` is called
        - **THEN** `apply(DeletePlan)` runs
        """,
    )
    report = _run(checker, base, head)
    assert report.ok, [(f.code, f.detail) for f in report.findings]
    kinds = [e.kind for e in report.drift]
    assert "lead-in-duplicated" in kinds and "table-header-duplicated" in kinds

    # a governed row moved into a scenario is a demotion, whatever the entry says
    _write_spec(
        head,
        "demo",
        """
        # demo Specification
        ## Purpose
        A purpose someone wrote, long enough to clear the tool's minimum length for a purpose.
        ## Requirements
        ### Requirement: Study-plan tools
        `register_tools(mcp)` SHALL register three study-plan tools, each a thin seam adapter:

        | Tool | Seam call |
        |---|---|
        | `list_study_plans()` | `browse()` |
        | `get_study_plan(id)` | `inspect(id)` |

        Every response SHALL be the seam view's `to_json_dict()`.

        #### Scenario: Discover
        - **WHEN** `list_study_plans()` is called
        - **THEN** `browse()` answers
        #### Scenario: Delete
        - **WHEN** `delete_study_plan` is called
        - **THEN** | `delete_study_plan(id)` | `apply(DeletePlan(id))` |
        """,
    )
    _write_exceptions(
        head,
        """
        [[moved-body-text]]
        spec = "demo"
        heading = "Study-plan tools"
        ordinal = 6
        text = "| `delete_study_plan(id)` | `apply(DeletePlan(id))` |"
        scenario = "Delete"
        """,
    )
    report = _run(checker, base, head)
    assert not report.ok
    assert "inherited-normative-moved" in _codes(report)


def test_lead_in_scope_ends_with_its_paragraph_or_table(checker, tmp_path: Path) -> None:
    """The trailing paragraph after the table is not governed by the colon lead-in: a fragment that
    holds only it does not need the lead-in repeated."""
    base, head = _pair(tmp_path)
    _write_spec(base, "demo", TABLE_BASE)
    _write_spec(
        head,
        "demo",
        """
        # demo Specification
        ## Purpose
        A purpose someone wrote, long enough to clear the tool's minimum length for a purpose.
        ## Requirements
        ### Requirement: Study-plan tools
        `register_tools(mcp)` SHALL register three study-plan tools, each a thin seam adapter:

        | Tool | Seam call |
        |---|---|
        | `list_study_plans()` | `browse()` |
        | `get_study_plan(id)` | `inspect(id)` |
        | `delete_study_plan(id)` | `apply(DeletePlan(id))` |

        #### Scenario: Discover
        - **WHEN** `list_study_plans()` is called
        - **THEN** `browse()` answers
        ### Requirement: Study-plan tools — responses are seam views
        Every response SHALL be the seam view's `to_json_dict()`.
        #### Scenario: Delete
        - **WHEN** `delete_study_plan` is called
        - **THEN** `apply(DeletePlan)` runs
        """,
    )
    report = _run(checker, base, head)
    assert report.ok, [(f.code, f.detail) for f in report.findings]


def test_a_restated_lead_in_may_be_duplicated_across_fragments(checker, tmp_path: Path) -> None:
    """When the verbatim lead-in does not fit beside a long row, one `context-restated` entry gives
    a shorter lead-in that every fragment may carry (like a verbatim one)."""
    base, head = _pair(tmp_path)
    _write_spec(base, "demo", TABLE_BASE)
    short = "`register_tools(mcp)` SHALL register the study-plan tool below as a thin seam adapter:"
    verbatim = (
        "`register_tools(mcp)` SHALL register three study-plan tools, each a thin seam adapter:"
    )
    _write_spec(
        head,
        "demo",
        f"""
        # demo Specification
        ## Purpose
        A purpose someone wrote, long enough to clear the tool's minimum length for a purpose.
        ## Requirements
        ### Requirement: Study-plan tools
        {short}

        | Tool | Seam call |
        |---|---|
        | `list_study_plans()` | `browse()` |

        Every response SHALL be the seam view's `to_json_dict()`.
        #### Scenario: Discover
        - **WHEN** `list_study_plans()` is called
        - **THEN** `browse()` answers
        ### Requirement: Study-plan tools — `get_study_plan`
        {short}

        | Tool | Seam call |
        |---|---|
        | `get_study_plan(id)` | `inspect(id)` |

        #### Scenario: Inspect
        - **WHEN** `get_study_plan` is called
        - **THEN** `inspect` answers
        ### Requirement: Study-plan tools — `delete_study_plan`
        {short}

        | Tool | Seam call |
        |---|---|
        | `delete_study_plan(id)` | `apply(DeletePlan(id))` |

        #### Scenario: Delete
        - **WHEN** `delete_study_plan` is called
        - **THEN** `apply(DeletePlan)` runs
        """,
    )
    _write_exceptions(
        head,
        f"""
        [[context-restated]]
        spec = "demo"
        heading = "Study-plan tools"
        ordinal = 1
        old = "{verbatim}"
        new = "{short}"
        reason = "the verbatim lead-in does not fit beside the longest row"

        [[restates-shall]]
        spec = "demo"
        heading = "Study-plan tools — `get_study_plan`"
        scenario = "Inspect"
        restates = "{short}"
        searched_tests = "none"
        """,
    )
    report = _run(checker, base, head)
    assert report.ok, [(f.code, f.detail) for f in report.findings]
    assert sum(1 for e in report.drift if e.kind == "lead-in-duplicated") == 2


def test_pass10_a_governing_clause_may_be_repeated_verbatim_into_a_fragment(
    checker, tmp_path: Path
) -> None:
    """Pass 10 (seat gpt-5.6-sol, reproduced): a condition that governs a whole sentence
    ("Whenever the resulting document would be active, apply SHALL evaluate … and SHALL raise …")
    was attached to the first fragment only, so the second fragment read as unconditional. The
    repair repeats the clause; `added_tokens` refuses polarity words (`not`, `only`) by design, so a
    clause containing them needs its own declaration: `repeated_clause`, which must be a verbatim
    substring of the sentence (sentence-initial capitalisation aside) and lands in the drift report
    as `clause-restated` for the reader."""
    base, head = _pair(tmp_path)
    _write_spec(
        base,
        "demo",
        f"""
        # demo Specification
        ## Purpose
        A purpose someone wrote, long enough to clear the tool's minimum length for a purpose.
        ## Requirements
        ### Requirement: Gate
        When not ready, the seam SHALL refuse the write and SHALL report the blockers.
        {SCENARIO_OK}
        """,
    )
    _write_spec(
        head,
        "demo",
        f"""
        # demo Specification
        ## Purpose
        A purpose someone wrote, long enough to clear the tool's minimum length for a purpose.
        ## Requirements
        ### Requirement: Gate
        When not ready, the seam SHALL refuse the write.
        {SCENARIO_OK}
        ### Requirement: Gate — the blockers are reported
        When not ready, the seam SHALL report the blockers.
        #### Scenario: Blockers listed
        - **WHEN** an unready plan is written
        - **THEN** the refusal lists the blockers
        """,
    )
    entry = """
        [[split-sentence]]
        spec = "demo"
        heading = "Gate"
        ordinal = 1
        old = "When not ready, the seam SHALL refuse the write and SHALL report the blockers."
        new = [
          "When not ready, the seam SHALL refuse the write.",
          "When not ready, the seam SHALL report the blockers.",
        ]
        added_tokens = ["the", "seam", "."]
        {clause}

        [[restates-shall]]
        spec = "demo"
        heading = "Gate — the blockers are reported"
        scenario = "Blockers listed"
        restates = "When not ready, the seam SHALL report the blockers."
        searched_tests = "none"
        """
    # Declaring the polarity word as a plain added token is refused, as before.
    _write_exceptions(
        head,
        entry.replace("{clause}", "").replace(
            '"the", "seam", "."',
            '"When", "not", "ready", ",", "the", "seam", "."',
        ),
    )
    report = _run(checker, base, head)
    assert "split-sentence-token-drift" in _codes(report)

    # The same words as a verbatim repeat of the sentence's own clause pass and are reported.
    _write_exceptions(head, entry.replace("{clause}", 'repeated_clause = "When not ready,"'))
    report = _run(checker, base, head)
    assert report.ok, [(f.code, f.detail) for f in report.findings]
    assert any(e.kind == "clause-restated" for e in report.drift)

    # A clause the sentence never contained is not a repeat.
    _write_exceptions(
        head, entry.replace("{clause}", 'repeated_clause = "Unless the plan is ready,"')
    )
    report = _run(checker, base, head)
    assert "split-sentence-clause-not-in-sentence" in _codes(report)
