"""`just spec-check` is a gate: strict, pinned, run in CI, honest when it cannot run.

Plan 7 (reviews/2026-10-21-full-repo-review/REMEDIATION-PLAN-7.md §A3/A4; council pass 9,
ARBITRATION-pass9.md §4 Q4/Q6 and §8.2 R4). Before this, the recipe ran `openspec validate`
non-strict, printed 85 warnings nobody read, used whichever `openspec` happened to be on PATH,
and CI never ran it. These tests pin the shape that closes each of those gaps; they read the
Justfile, the workflow and the release-consistency script as text, the way
`test_ci_workflow_contract.py` does.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
JUSTFILE = REPO_ROOT / "Justfile"
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"
RELEASE_SCRIPT = REPO_ROOT / "scripts" / "check-release-consistency.py"
RESOLVER = REPO_ROOT / "scripts" / "openspec-cli.sh"
CONVENTIONS = REPO_ROOT / "docs" / "contributor-conventions.md"

_VERSION_LINE = re.compile(r'^export OPENSPEC_VERSION := "(\d+\.\d+\.\d+)"$', re.M)


def _justfile() -> str:
    return JUSTFILE.read_text(encoding="utf-8")


def _recipe(name: str) -> str:
    text = _justfile()
    match = re.search(rf"^{re.escape(name)}:\n((?:[ \t]+.*\n?)+)", text, re.M)
    assert match, f"recipe {name} not found"
    return match.group(1)


def _workflow() -> dict[str, Any]:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------------------------
# The pin: one version literal, used everywhere the CLI is invoked
# --------------------------------------------------------------------------------------------


def test_openspec_version_is_pinned_exactly_once_in_the_justfile() -> None:
    matches = _VERSION_LINE.findall(_justfile())
    assert len(matches) == 1, f"expected one OPENSPEC_VERSION pin, found {matches}"


def test_the_resolver_is_the_only_place_that_names_the_openspec_binary() -> None:
    """One resolver (`scripts/openspec-cli.sh`) decides which CLI runs: a local `openspec` whose
    version equals the pin, else `npx` at the pin. Recipes and the release script call it; nothing
    else may spawn `openspec` or `npx @fission-ai/openspec` directly, or two copies drift."""
    assert RESOLVER.is_file()
    resolver = RESOLVER.read_text(encoding="utf-8")
    assert "npx --yes @fission-ai/openspec@" in resolver
    assert "OPENSPEC_VERSION" in resolver
    assert "OPENSPEC_TELEMETRY" in resolver
    for path in (JUSTFILE, RELEASE_SCRIPT):
        text = path.read_text(encoding="utf-8")
        assert "@fission-ai/openspec" not in text, f"{path.name} spawns the package directly"
        assert not re.search(r"(?m)^\s*openspec validate", text), (
            f"{path.name} calls openspec directly"
        )


def test_spec_check_is_strict_and_goes_through_the_resolver() -> None:
    recipe = _recipe("spec-check")
    assert "scripts/openspec-cli.sh" in recipe
    assert "--strict" in recipe
    assert "--specs --all" in recipe


def test_spec_check_skips_only_locally_and_fails_under_ci() -> None:
    """A skip is not a pass: without the CLI the recipe may skip on a contributor's machine, but
    under `CI` it must fail, otherwise a broken npx resolution turns the gate green."""
    resolver = RESOLVER.read_text(encoding="utf-8")
    assert "SKIPPED" in resolver
    assert "CI" in resolver
    assert "docs/contributor-conventions.md" in resolver  # the pointer that replaced a dead one


def test_a_mismatched_local_openspec_is_refused_not_used(tmp_path: Path) -> None:
    """A local binary at another version must not print a pass for the pinned contract."""
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake = fake_bin / "openspec"
    fake.write_text(
        '#!/bin/sh\nif [ "$1" = --version ]; then echo 9.9.9; exit 0; fi\necho ran; exit 0\n'
    )
    fake.chmod(0o755)
    env = {
        "PATH": f"{fake_bin}:/usr/bin:/bin",
        "OPENSPEC_VERSION": "1.14.1",
        "OPENSPEC_NO_NPX": "1",  # keep the test offline: the resolver must not fall through to npx
        "HOME": str(tmp_path),
    }
    proc = subprocess.run(
        ["bash", str(RESOLVER), "--version"],
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
        check=False,
    )
    assert proc.returncode != 0
    assert "9.9.9" in proc.stdout + proc.stderr and "1.14.1" in proc.stdout + proc.stderr


def test_absent_cli_skips_locally_and_fails_when_ci_is_set(tmp_path: Path) -> None:
    env = {
        "PATH": "/usr/bin:/bin",
        "OPENSPEC_VERSION": "1.14.1",
        "OPENSPEC_NO_NPX": "1",
        "HOME": str(tmp_path),
    }
    local = subprocess.run(
        ["bash", str(RESOLVER), "validate", "--specs", "--all", "--strict"],
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
        check=False,
    )
    assert local.returncode == 0
    assert "SKIPPED" in local.stdout + local.stderr
    under_ci = subprocess.run(
        ["bash", str(RESOLVER), "validate", "--specs", "--all", "--strict"],
        capture_output=True,
        text=True,
        env={**env, "CI": "true"},
        timeout=60,
        check=False,
    )
    assert under_ci.returncode != 0


# --------------------------------------------------------------------------------------------
# CI runs the recipe
# --------------------------------------------------------------------------------------------


def test_ci_has_a_spec_check_job_that_runs_the_recipe() -> None:
    jobs = _workflow()["jobs"]
    assert "spec-check" in jobs, sorted(jobs)
    job = jobs["spec-check"]
    runs = [s.get("run", "") for s in job["steps"]]
    assert any(r.strip() == "just spec-check" for r in runs), runs
    uses = [s.get("uses", "") for s in job["steps"]]
    assert any(u.startswith("extractions/setup-just@") for u in uses)
    assert any(u.startswith("actions/setup-node@") for u in uses)
    assert "timeout-minutes" in job


# --------------------------------------------------------------------------------------------
# The release gate shares the resolver and reads JSON, not glyphs
# --------------------------------------------------------------------------------------------


def test_release_consistency_reads_openspec_json_through_the_resolver() -> None:
    text = RELEASE_SCRIPT.read_text(encoding="utf-8")
    assert "openspec-cli.sh" in text
    assert "--json" in text
    assert "✓ change/" not in text, "the release gate still parses the human-readable glyph line"


# --------------------------------------------------------------------------------------------
# The contributor page says what the gate is
# --------------------------------------------------------------------------------------------


def test_contributor_conventions_describe_the_strict_gate_and_the_length_rule() -> None:
    text = re.sub(r"\s+", " ", CONVENTIONS.read_text(encoding="utf-8"))
    assert "--strict" in text
    assert "500" in text
    assert "one behaviour" in text or "one behavior" in text
    assert "openspec validate --specs --all`" not in text, (
        "the non-strict recipe is still documented"
    )


@pytest.mark.skipif(sys.platform == "win32", reason="bash resolver")
def test_resolver_is_executable_bash() -> None:
    assert RESOLVER.read_text(encoding="utf-8").startswith("#!/usr/bin/env bash")
    assert RESOLVER.stat().st_mode & 0o111
