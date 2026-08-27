"""Contract tests for the e2e coverage-collector plugin.

Why these live in the DEFAULT suite and not under ``e2e/``: the plugin's job is
to tell the coverage gate which tests can *actually run*, and the gate itself
runs in the default suite on every CI build. A guard that only fired under
``-m e2e`` would not fire in CI at all -- the same blind spot the plugin exists
to close.

Why a subprocess rather than the ``pytester`` fixture: ``pytest_plugins`` is
only honoured in the ROOT conftest, so enabling ``pytester`` would change
collection for every default-suite test in order to exercise one module. Driving
a subprocess instead exercises the exact invocation the gate uses --
``-p e2e.coverage_collector`` plus ``STUDYLOOP_COVERAGE_MANIFEST`` -- and
asserts the manifest's flags rather than the plugin's internals, so the tests
stay honest if the implementation is refactored.

Each subprocess is anchored with a generated ``pytest.ini`` and run from inside
its own temp directory. Without that anchor pytest resolves its rootdir by
searching *upward* from the target path; because the temp directory lives
outside the repository that search reaches ``$HOME`` and dies on the first
unreadable dotfile it stats. An explicit ``-c`` stops the search dead and keeps
the subprocess hermetic.

The eligibility policy under test: an item is covering evidence only if it can
run AND can fail. Active ``skip``/``skipif`` and any ``xfail`` are non-covering;
an inactive ``skipif`` is covering; parametrized items are judged individually.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

TESTS_ROOT = Path(__file__).resolve().parent

PYTEST_INI = "[pytest]\n"

MARKER_CASES = """\
import pytest


def test_plain_is_eligible() -> None:
    pass


@pytest.mark.skip(reason="unconditional skip")
def test_active_skip() -> None:
    pass


@pytest.mark.skipif(True, reason="condition is true")
def test_active_skipif() -> None:
    pass


@pytest.mark.skipif(False, reason="condition is false")
def test_inactive_skipif() -> None:
    pass


@pytest.mark.xfail(run=True, reason="runs but cannot fail the build")
def test_xfail_run_true() -> None:
    pass


@pytest.mark.xfail(strict=True, reason="strict xfail")
def test_xfail_strict() -> None:
    pass


@pytest.mark.parametrize(
    "route",
    [
        "/api/alpha",
        pytest.param("/api/beta", marks=pytest.mark.skip(reason="param skipped")),
    ],
)
def test_parametrized_routes(route: str) -> None:
    pass
"""

MODULE_LEVEL_SKIP = """\
import pytest

pytestmark = pytest.mark.skip(reason="module-level pytestmark")


def test_hidden_by_module_pytestmark() -> None:
    pass
"""


def _run_collector(workdir: Path, manifest: Path | None) -> subprocess.CompletedProcess[str]:
    """Collect ``workdir`` in a hermetic subprocess with the collector loaded.

    ``manifest`` of ``None`` deliberately omits ``STUDYLOOP_COVERAGE_MANIFEST``
    so the plugin's fail-fast guard can be exercised.
    """
    ini = workdir / "pytest.ini"
    ini.write_text(PYTEST_INI, encoding="utf-8")

    env = dict(os.environ)
    env.pop("STUDYLOOP_COVERAGE_MANIFEST", None)
    if manifest is not None:
        env["STUDYLOOP_COVERAGE_MANIFEST"] = str(manifest)
    env["PYTHONPATH"] = str(TESTS_ROOT)

    return subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-c",
            str(ini),
            ".",
            "--collect-only",
            "-q",
            "-p",
            "e2e.coverage_collector",
        ],
        cwd=str(workdir),
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )


@pytest.fixture(scope="module")
def manifest_records(
    tmp_path_factory: pytest.TempPathFactory,
) -> dict[str, dict[str, Any]]:
    """Collect the generated marker cases once; return records keyed by nodeid.

    One subprocess for every case keeps the whole file to a few seconds. The
    module-level-``pytestmark`` case needs its own file because that marker
    applies to the entire module, so two files are generated and collected
    together.
    """
    workdir = tmp_path_factory.mktemp("collector_contract")
    (workdir / "test_marker_cases.py").write_text(MARKER_CASES, encoding="utf-8")
    (workdir / "test_module_level_skip.py").write_text(MODULE_LEVEL_SKIP, encoding="utf-8")
    manifest = workdir / "manifest.json"

    result = _run_collector(workdir, manifest)
    assert result.returncode == 0, (
        "collector subprocess failed\n"
        f"stdout:\n{result.stdout[-3000:]}\n"
        f"stderr:\n{result.stderr[-3000:]}"
    )
    assert manifest.exists(), "collector did not write a manifest"

    payload = json.loads(manifest.read_text(encoding="utf-8"))
    return {record["nodeid"]: record for record in payload["items"]}


def _find(records: dict[str, dict[str, Any]], needle: str) -> dict[str, Any]:
    """The single record whose nodeid ends in exactly ``needle``.

    Matched on the nodeid's final ``::`` segment rather than as a substring:
    ``test_active_skip`` is a prefix of ``test_active_skipif``, so a substring
    match silently returns two records and the assertion it feeds stops meaning
    anything. Parametrized names include their ``[param]`` suffix.
    """
    matches = [rec for nodeid, rec in records.items() if nodeid.rsplit("::", 1)[-1] == needle]
    assert len(matches) == 1, f"expected exactly one item named {needle!r}, got {len(matches)}"
    return matches[0]


def test_an_unmarked_test_is_covering(
    manifest_records: dict[str, dict[str, Any]],
) -> None:
    record = _find(manifest_records, "test_plain_is_eligible")
    assert record["eligible"] is True
    assert record["exclusion_kind"] == ""


def test_an_unconditional_skip_is_not_covering(
    manifest_records: dict[str, dict[str, Any]],
) -> None:
    record = _find(manifest_records, "test_active_skip")
    assert record["eligible"] is False
    assert record["exclusion_kind"] == "skip"
    assert "unconditional skip" in record["exclusion_reason"]


def test_an_active_skipif_is_not_covering(
    manifest_records: dict[str, dict[str, Any]],
) -> None:
    record = _find(manifest_records, "test_active_skipif")
    assert record["eligible"] is False
    assert record["exclusion_kind"] == "skip"


def test_an_inactive_skipif_is_still_covering(
    manifest_records: dict[str, dict[str, Any]],
) -> None:
    """A condition that is false in this environment does not remove evidence.

    This is the case that keeps the platform-gated tests counting: a
    ``skipif(sys.platform == "win32")`` test is real coverage on macOS and Linux.
    """
    record = _find(manifest_records, "test_inactive_skipif")
    assert record["eligible"] is True
    assert record["exclusion_kind"] == ""


def test_xfail_with_run_true_is_not_covering(
    manifest_records: dict[str, dict[str, Any]],
) -> None:
    """An xfail asserts the surface is expected broken -- not that it works."""
    record = _find(manifest_records, "test_xfail_run_true")
    assert record["eligible"] is False
    assert record["exclusion_kind"] == "xfail"


def test_strict_xfail_is_not_covering(
    manifest_records: dict[str, dict[str, Any]],
) -> None:
    record = _find(manifest_records, "test_xfail_strict")
    assert record["eligible"] is False
    assert record["exclusion_kind"] == "xfail"


def test_a_skipped_param_does_not_disqualify_its_siblings(
    manifest_records: dict[str, dict[str, Any]],
) -> None:
    """Parametrized items are judged individually, not per function."""
    alpha = _find(manifest_records, "test_parametrized_routes[/api/alpha]")
    beta = _find(manifest_records, "test_parametrized_routes[/api/beta]")
    assert alpha["eligible"] is True, "the unmarked param must remain covering"
    assert beta["eligible"] is False, "the skip-marked param must not count"
    assert beta["exclusion_kind"] == "skip"


def test_param_values_reach_the_manifest_as_searchable_text(
    manifest_records: dict[str, dict[str, Any]],
) -> None:
    """The gate substring-searches params, so a route passed via a param counts."""
    alpha = _find(manifest_records, "test_parametrized_routes[/api/alpha]")
    assert "/api/alpha" in alpha["params"]["route"]


def test_a_module_level_pytestmark_skip_is_not_covering(
    manifest_records: dict[str, dict[str, Any]],
) -> None:
    """``pytestmark`` is why static marker detection was rejected."""
    record = _find(manifest_records, "test_hidden_by_module_pytestmark")
    assert record["eligible"] is False
    assert record["exclusion_kind"] == "skip"


def test_the_pytest_skipping_helpers_are_still_importable() -> None:
    """Collection-independent twin of the plugin's load-time guard.

    The plugin's own ``pytest_configure`` check only runs when something loads
    the plugin. This test runs on every default-suite build, so a pytest upgrade
    that moves these private helpers fails loudly here even while the plugin is
    loaded by nothing.
    """
    from _pytest.skipping import evaluate_skip_marks, evaluate_xfail_marks

    assert callable(evaluate_skip_marks)
    assert callable(evaluate_xfail_marks)


def test_the_plugin_refuses_to_load_without_a_manifest_path(tmp_path: Path) -> None:
    """No silent degradation: a missing manifest path is a hard UsageError."""
    (tmp_path / "test_nothing.py").write_text(
        "def test_ok() -> None:\n    pass\n", encoding="utf-8"
    )

    result = _run_collector(tmp_path, None)

    assert result.returncode != 0, "the plugin must refuse to run without a manifest path"
    assert "STUDYLOOP_COVERAGE_MANIFEST" in result.stdout + result.stderr


def test_the_fake_agent_entry_point_is_installed() -> None:
    """Assert the precondition the collector's blind spot depends on.

    Much of the e2e suite gates itself with imperative ``pytest.skip()`` behind
    ``shutil.which(...)`` -- which a collection-time manifest cannot see. Those
    skips do not fire while the fake-agent console script is installed, so this
    turns a silent environmental assumption into a checked one.
    """
    assert shutil.which("studyloop-fake-agent") is not None, (
        "studyloop-fake-agent is not on PATH, so parts of the e2e suite will "
        "skip themselves at runtime in a way the coverage manifest cannot see. "
        "Run `uv sync --all-packages` to install the console scripts."
    )
