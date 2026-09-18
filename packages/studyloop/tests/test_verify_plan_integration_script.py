"""``scripts/verify/plan_integration.py`` — the receipt is the definition of done (D-15, design §8).

The script runs a fixed registry of checks and writes
``docs/architecture/plan-integration/receipts/verify-<sha>.json``. These
tests are about the *registry and the receipt*, not about the checks'
subjects (each of those has its own suite): every check has a name, a
command and an expected exit status; the design-§8 checks are all present by
name; a check that cannot run is recorded as a FAILURE, never as "not
applicable"; the receipt carries every exit code and every pytest node count;
and the process exit status is non-zero the moment one required check fails.

The real registry is exercised here with an injected runner, so the tests are
fast and hermetic; the receipt committed under ``receipts/`` is the real run.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from collections.abc import Callable

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts/verify/plan_integration.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("plan_integration_verify", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    # ``@dataclass`` resolves string annotations through ``sys.modules`` — a
    # module executed without being registered there has no namespace to look in.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def script():
    return _load_script()


#: Design §8 + review 4's T6.2 list, by registry name. A rename here is a
#: deliberate change to the receipt's vocabulary, not a drift.
REQUIRED_CHECK_NAMES = {
    "full-suite-studyloop",
    "full-suite-agent-session-tools",
    "ruff-check",
    "ruff-format",
    "pyright",
    "bug-a-readiness-gated-doors",
    "bug-b-partial-recording-reported",
    "architecture-guard",
    "golden-no-active-sha",
    "golden-no-active-byte-identity",
    "stdio-inventory",
    "inventory-in-process",
    "plan-suites",
    "docs-contract",
    "protected-files-early-base",
    "protected-files-late-base",
    "rg-plan-application-cli",
    "rg-plan-application-web-routes",
    "rg-plan-application-mcp",
    "rg-no-adapter-storage-imports",
    "rg-no-adapter-storage-imports-from-package",
    "rg-no-focus-literal-under-session-routes",
    "combined-journey",
    "integration-combined",
    "integration-combined-reverse",
    "browser-journey-e2e",
    "js-unit",
    "openspec-validate",
    "mkdocs-strict",
    # Follow-on programme, design §6 (items 1 and 3/4): the two architect grants
    # derived from the inventory, and the `plan repair` / `plan close` refusal
    # texts as the seam tests pin them.
    "architect-grants",
    "repair-close-refusals",
}


class TestRegistry:
    def test_every_check_has_a_name_a_command_and_an_expected_exit(self, script) -> None:
        checks = script.build_checks(REPO_ROOT)
        assert checks, "the registry is empty"
        names = [check.name for check in checks]
        assert len(names) == len(set(names)), f"duplicate check names: {names}"
        for check in checks:
            assert check.name and check.name == check.name.strip()
            assert isinstance(check.expected_exit, int)
            if callable(check.command):
                continue
            assert isinstance(check.command, (list, tuple)) and check.command, check.name
            assert all(isinstance(part, str) and part for part in check.command), check.name

    def test_design_section_eight_checks_are_all_present(self, script) -> None:
        names = {check.name for check in script.build_checks(REPO_ROOT)}
        missing = REQUIRED_CHECK_NAMES - names
        assert not missing, f"design §8 checks absent from the registry: {sorted(missing)}"

    def test_every_check_is_required(self, script) -> None:
        """D-15: a missing check is a failure, never N/A — so there is no
        optional flag to hide behind."""
        for check in script.build_checks(REPO_ROOT):
            assert check.required is True, check.name

    def test_combined_run_is_verified_in_both_orders(self, script) -> None:
        """#15 DoD: "the combined integration run has no nested-event-loop
        ordering regression". One order proves one order (council review 5,
        GPT F10): the registry runs the stdio smoke + the combined journey in
        BOTH file orders, as two checks over the same two modules, so the
        receipt can say "both orders" and mean it."""
        by_name = {check.name: check for check in script.build_checks(REPO_ROOT)}
        forward = by_name["integration-combined"].command
        reverse = by_name["integration-combined-reverse"].command
        assert not callable(forward) and not callable(reverse)
        modules = [part for part in forward if part.endswith(".py")]
        assert len(modules) == 2, forward
        assert [part for part in reverse if part.endswith(".py")] == list(reversed(modules))
        assert "-m" in forward and "integration" in forward
        assert "-m" in reverse and "integration" in reverse
        assert [part for part in forward if not part.endswith(".py")] == [
            part for part in reverse if not part.endswith(".py")
        ]

    def test_zero_hit_rg_invariants_expect_exit_one(self, script) -> None:
        """``rg`` exits 1 when nothing matches, which is the desired state for
        the three "zero …" invariants; the "used by" invariants expect matches."""
        by_name = {check.name: check for check in script.build_checks(REPO_ROOT)}
        for name in (
            "rg-no-adapter-storage-imports",
            "rg-no-adapter-storage-imports-from-package",
            "rg-no-focus-literal-under-session-routes",
        ):
            assert by_name[name].expected_exit == 1, name
        for name in (
            "rg-plan-application-cli",
            "rg-plan-application-web-routes",
            "rg-plan-application-mcp",
        ):
            assert by_name[name].expected_exit == 0, name

    def test_protected_file_checks_name_the_ten_files_against_their_bases(self, script) -> None:
        by_name = {check.name: check for check in script.build_checks(REPO_ROOT)}
        early = by_name["protected-files-early-base"].command
        late = by_name["protected-files-late-base"].command
        assert not callable(early) and not callable(late)
        assert script.PROTECTED_EARLY_BASE in early and script.PROTECTED_LATE_BASE in late
        # Both bases are moving pins by design: a base advances only when a
        # protected file legitimately changes and the diff has been read
        # (recorded next to the constant), and the check is named by role so
        # the name never has to move with it. The late base must never regress
        # to the early one.
        assert script.PROTECTED_LATE_BASE != script.PROTECTED_EARLY_BASE
        early_files = [part for part in early if part.endswith(".py")]
        late_files = [part for part in late if part.endswith(".py")]
        assert len(early_files) == 3 and len(late_files) == 7
        for rel in (*early_files, *late_files):
            assert (REPO_ROOT / rel).exists(), rel

    def test_protected_file_bases_are_reachable_from_main(self, script) -> None:
        """A base that exists only as an unreachable object in one clone makes the
        check fail on every fresh checkout (2026-09-18: ``3a4f6b01`` survived the
        history consolidation as a dangling object here and nowhere else). Both
        bases must be ancestors of the local ``main`` -- the property a rewritten
        SHA loses.

        Judged only where it can be: CI's ``actions/checkout`` is a depth-1
        clone of the PR ref with no ``main``, where neither base is even an
        object (run 35380095596 failed the 3.12 and 3.13 matrix on exactly
        this). There the test skips and says why, rather than reporting a
        failure the checkout cannot distinguish from the real one."""
        import subprocess

        def git(*args: str) -> subprocess.CompletedProcess[str]:
            return subprocess.run(["git", *args], cwd=REPO_ROOT, capture_output=True, text=True)

        if git("rev-parse", "--is-shallow-repository").stdout.strip() == "true":
            pytest.skip("shallow checkout: the bases' reachability cannot be judged here")
        if git("rev-parse", "--verify", "-q", "main^{commit}").returncode != 0:
            pytest.skip("no local `main` ref: the bases' reachability cannot be judged here")

        for base in (script.PROTECTED_EARLY_BASE, script.PROTECTED_LATE_BASE):
            result = git("merge-base", "--is-ancestor", base, "main")
            assert result.returncode == 0, f"{base} is not an ancestor of main: {result.stderr}"

    def test_architect_grants_check_derives_the_ten_names_from_the_inventory(self, script) -> None:
        """Design §6 (follow-on item 1, D-A): the Kiro and Claude architect
        definitions carry exactly the nine plan tools + ``record_plan_learning``
        in the spelling each harness honours (probe receipt 2026-09-16/17).
        The check is in-process — it reads the two files and the inventory, so a
        tenth plan tool added to the inventory fails the receipt until the grants
        follow — and it measures the names it found, so the receipt can be read."""
        by_name = {check.name: check for check in script.build_checks(REPO_ROOT)}
        check = by_name["architect-grants"]
        assert callable(check.command)
        assert check.command is script.check_architect_grants
        code, measured = script.check_architect_grants(REPO_ROOT)
        assert code == 0, measured
        from studyloop.mcp.inventory import LEARNING_RECORD_TOOL, PLAN_TOOL_NAMES

        expected = [*PLAN_TOOL_NAMES, LEARNING_RECORD_TOOL]
        assert measured["expected"] == expected
        assert measured["kiro"]["granted"] == expected
        assert measured["claude"]["granted"] == expected
        assert measured["kiro"]["file"] == "agents/kiro/study-plan-architect.json"
        assert measured["claude"]["file"] == "agents/claude/study-plan-architect.md"
        assert measured["problems"] == []

    def test_architect_grants_check_fails_when_a_grant_is_missing_or_extra(
        self, script, tmp_path: Path
    ) -> None:
        """The check judges a tree, not the checkout: a copy with one grant
        removed and one stray studyloop grant added fails, naming both."""
        import json as _json
        import shutil

        root = tmp_path / "tree"
        (root / "agents/kiro").mkdir(parents=True)
        (root / "agents/claude").mkdir(parents=True)
        shutil.copy(
            REPO_ROOT / "agents/claude/study-plan-architect.md",
            root / "agents/claude/study-plan-architect.md",
        )
        kiro = _json.loads((REPO_ROOT / "agents/kiro/study-plan-architect.json").read_text())
        allowed = [
            entry for entry in kiro["allowedTools"] if entry != "@studyloop/delete_study_plan"
        ]
        allowed.append("@studyloop/get_next_action")
        kiro["allowedTools"] = allowed
        (root / "agents/kiro/study-plan-architect.json").write_text(_json.dumps(kiro))
        code, measured = script.check_architect_grants(root)
        assert code == 1
        joined = " ".join(measured["problems"])
        assert "delete_study_plan" in joined and "get_next_action" in joined
        assert "kiro" in joined.lower()

    def test_repair_close_refusals_check_names_the_seam_tests_that_pin_the_texts(
        self, script
    ) -> None:
        """Design §6 (items 3/4, D-C/D-G): the refusal texts are pinned by the
        CLI seam tests, so the check runs exactly those node ids — the husk
        refusal (both exits named), `plan repair` on a ready plan and on an
        unknown id, `plan close` on an unfinished plan — and nothing else."""
        by_name = {check.name: check for check in script.build_checks(REPO_ROOT)}
        command = by_name["repair-close-refusals"].command
        assert not callable(command)
        node_ids = [part for part in command if "::" in part]
        assert node_ids == [
            "packages/studyloop/tests/test_cli_plan_seam.py::test_husk_refusal_names_both_pause_and_repair",
            "packages/studyloop/tests/test_cli_plan_seam.py::test_plan_repair_on_a_ready_plan_says_nothing_to_repair",
            "packages/studyloop/tests/test_cli_plan_seam.py::test_plan_repair_unknown_id_is_the_seams_not_found",
            "packages/studyloop/tests/test_cli_plan_seam.py::test_plan_close_on_an_unfinished_plan_refuses",
        ]
        source = (REPO_ROOT / "packages/studyloop/tests/test_cli_plan_seam.py").read_text()
        for node in node_ids:
            assert f"def {node.split('::')[1]}(" in source, node
        assert by_name["repair-close-refusals"].expected_exit == 0


class TestPytestCounts:
    @pytest.mark.parametrize(
        ("tail", "expected"),
        [
            ("4990 passed, 4 skipped in 360.12s (0:06:00)", {"passed": 4990, "skipped": 4}),
            ("2 passed in 3.1s", {"passed": 2}),
            (
                "1 failed, 7 passed, 1 deselected in 0.5s",
                {"failed": 1, "passed": 7, "deselected": 1},
            ),
            ("no tests ran in 0.01s", {}),
            ("3 passed, 2 warnings in 1.0s", {"passed": 3, "warnings": 2}),
        ],
    )
    def test_parse_pytest_counts(self, script, tail: str, expected: dict[str, int]) -> None:
        output = f"....\n=========== {tail} ===========\n"
        assert script.parse_pytest_counts(output) == expected

    @pytest.mark.parametrize(
        ("tail", "expected"),
        [
            ("4990 passed, 4 skipped in 376.3s (0:06:16)", {"passed": 4990, "skipped": 4}),
            ("30 passed in 0.46s", {"passed": 30}),
            ("2 passed, 1 deselected in 1.4s", {"passed": 2, "deselected": 1}),
        ],
    )
    def test_parse_pytest_counts_bare_quiet_form(
        self, script, tail: str, expected: dict[str, int]
    ) -> None:
        """``pytest -q`` under the studyloop package config prints the summary
        line WITHOUT the ``====`` bars; the first real run recorded empty counts
        for every studyloop suite because of it."""
        output = f"..............                                         [100%]\n{tail}\n"
        assert script.parse_pytest_counts(output) == expected

    def test_a_progress_line_is_not_mistaken_for_a_summary(self, script) -> None:
        assert script.parse_pytest_counts("....... [100%]\nsome log line in 3s\n") == {}


def _fake_runner(
    outcomes: dict[str, tuple[int | None, str]],
) -> Callable[[Any], tuple[int | None, str, str | None]]:
    """A runner returning (exit_code, output, error) per check name.

    ``None`` as the exit code models a command that could not start at all
    (missing executable) — the "missing check" case D-15 forbids treating as
    N/A.
    """

    def run(check) -> tuple[int | None, str, str | None]:
        code, output = outcomes.get(check.name, (check.expected_exit, "1 passed in 0.1s"))
        error = "FileNotFoundError: no such executable" if code is None else None
        return code, output, error

    return run


class TestReceipt:
    def test_receipt_records_every_check_with_its_exit_and_counts(
        self, script, tmp_path: Path
    ) -> None:
        checks = script.build_checks(REPO_ROOT)
        out = tmp_path / "verify-abc1234.json"
        status = script.run_and_write(
            checks,
            out=out,
            runner=_fake_runner(
                {"full-suite-studyloop": (0, "=== 4990 passed, 4 skipped in 1s ===")}
            ),
            tree={"sha": "abc1234", "dirty": False},
        )
        assert status == 0
        receipt = json.loads(out.read_text(encoding="utf-8"))
        assert receipt["ok"] is True
        assert receipt["tree"] == {"sha": "abc1234", "dirty": False}
        by_name = {row["name"]: row for row in receipt["checks"]}
        assert set(by_name) == {check.name for check in checks}
        for row in receipt["checks"]:
            assert row["exit_code"] == row["expected_exit"]
            assert row["ok"] is True
            assert isinstance(row["command"], (list, str))
        assert by_name["full-suite-studyloop"]["counts"] == {"passed": 4990, "skipped": 4}
        assert receipt["summary"] == {"total": len(checks), "passed": len(checks), "failed": 0}

    def test_one_failed_check_fails_the_receipt_and_the_process(
        self, script, tmp_path: Path
    ) -> None:
        checks = script.build_checks(REPO_ROOT)
        out = tmp_path / "verify-def5678.json"
        status = script.run_and_write(
            checks,
            out=out,
            runner=_fake_runner({"architecture-guard": (1, "=== 1 failed, 29 passed in 1s ===")}),
            tree={"sha": "def5678", "dirty": True},
        )
        assert status == 1
        receipt = json.loads(out.read_text(encoding="utf-8"))
        assert receipt["ok"] is False
        row = next(r for r in receipt["checks"] if r["name"] == "architecture-guard")
        assert row["ok"] is False and row["exit_code"] == 1
        assert row["counts"] == {"failed": 1, "passed": 29}
        assert receipt["summary"]["failed"] == 1

    def test_a_failed_pytest_check_names_its_failed_nodes(self, script, tmp_path: Path) -> None:
        """A red full suite is only auditable if the receipt says WHICH tests
        failed: the 12-line ``output_tail`` cannot hold 44 ids, so the first
        real run on ``9d10fee6`` recorded ``ok: false`` with no way to
        reconcile it against the named environmental set. Every ``FAILED`` /
        ``ERROR`` short-summary line is kept, in order, on the row."""
        checks = script.build_checks(REPO_ROOT)
        out = tmp_path / "verify-2222222.json"
        output = "\n".join(
            [
                "F.E.                                              [100%]",
                "=================================== ERRORS ===================================",
                "___ ERROR at setup of test_b ___",
                "E   RuntimeError: world",
                "================================== FAILURES ==================================",
                "___ test_a ___",
                "E   assert 1 == 2",
                "=========================== short test summary info ============================",
                "FAILED packages/studyloop/tests/test_x.py::test_a - assert 1 == 2",
                "ERROR packages/studyloop/tests/test_y.py::test_b - RuntimeError: world",
                "1 failed, 2 passed, 1 error in 0.30s",
            ]
        )
        status = script.run_and_write(
            checks,
            out=out,
            runner=_fake_runner({"full-suite-studyloop": (1, output)}),
            tree={"sha": "2222222", "dirty": False},
        )
        assert status == 1
        receipt = json.loads(out.read_text(encoding="utf-8"))
        row = next(r for r in receipt["checks"] if r["name"] == "full-suite-studyloop")
        assert row["failed_nodes"] == [
            "FAILED packages/studyloop/tests/test_x.py::test_a",
            "ERROR packages/studyloop/tests/test_y.py::test_b",
        ]
        green = next(r for r in receipt["checks"] if r["name"] == "architecture-guard")
        assert green["failed_nodes"] == []

    def test_a_check_that_cannot_run_is_a_failure_not_not_applicable(
        self, script, tmp_path: Path
    ) -> None:
        """D-15: "Missing checks are recorded as failures, never as 'not
        applicable'." A missing executable yields no exit code; the receipt
        still has the row, marked failed, with the error text."""
        checks = script.build_checks(REPO_ROOT)
        out = tmp_path / "verify-0000000.json"
        status = script.run_and_write(
            checks,
            out=out,
            runner=_fake_runner({"js-unit": (None, "")}),
            tree={"sha": "0000000", "dirty": False},
        )
        assert status == 1
        receipt = json.loads(out.read_text(encoding="utf-8"))
        row = next(r for r in receipt["checks"] if r["name"] == "js-unit")
        assert row["ok"] is False
        assert row["exit_code"] is None
        assert "FileNotFoundError" in row["error"]
        assert "not applicable" not in json.dumps(receipt).lower()

    def test_unexpected_success_is_also_a_failure(self, script, tmp_path: Path) -> None:
        """An ``rg`` zero-hit invariant that suddenly finds hits exits 0 — the
        opposite of its expected 1 — and must be reported as failed."""
        checks = script.build_checks(REPO_ROOT)
        out = tmp_path / "verify-1111111.json"
        status = script.run_and_write(
            checks,
            out=out,
            runner=_fake_runner(
                {
                    "rg-no-focus-literal-under-session-routes": (
                        0,
                        '_start.py:1:build_canonical_persona("focus"',
                    )
                }
            ),
            tree={"sha": "1111111", "dirty": False},
        )
        assert status == 1
        receipt = json.loads(out.read_text(encoding="utf-8"))
        row = next(
            r for r in receipt["checks"] if r["name"] == "rg-no-focus-literal-under-session-routes"
        )
        assert row["ok"] is False and row["exit_code"] == 0 and row["expected_exit"] == 1


class TestRealPythonChecks:
    """The two in-process checks run for real here: they are cheap and their
    subjects (the golden file, the registry) are in this checkout."""

    def test_golden_sha_check_matches_the_committed_golden(self, script) -> None:
        code, measured = script.check_golden_sha(REPO_ROOT)
        assert code == 0, measured
        assert measured["sha256"] == script.GOLDEN_SHA256

    def test_inventory_check_reports_thirty_two_names_with_the_nine(self, script) -> None:
        code, measured = script.check_inventory_in_process(REPO_ROOT)
        assert code == 0, measured
        assert measured["count"] == 32
        assert len(measured["names"]) == len(set(measured["names"])) == 32
        assert set(script.PLAN_TOOL_NAMES) <= set(measured["names"])
        assert "record_plan_learning" in measured["names"]

    def test_default_receipt_path_is_named_by_the_short_sha(self, script) -> None:
        path = script.default_receipt_path(REPO_ROOT, "abc1234")
        assert path == REPO_ROOT / "docs/architecture/plan-integration/receipts/verify-abc1234.json"
