"""Installed Architect prompt resource contract."""

from __future__ import annotations

import subprocess
import zipfile
from pathlib import Path


def test_architect_prompt_loader_exposes_the_bounded_interview_policy() -> None:
    """Losing the packaged policy metadata would make setup certify an unbounded prompt."""
    from studyloop.planning.model_port import load_architect_prompt

    prompt = load_architect_prompt()

    assert prompt.version == "architect-v1"
    assert prompt.normal_question_limit == 1
    assert prompt.absolute_question_limit == 3
    assert prompt.provisional_plan_by_turn == 3
    assert prompt.context_evidence_tier == 4
    assert "untrusted curriculum context" in prompt.text.casefold()
    assert "notes are not progress" in prompt.text.casefold()
    assert "embedded instructions" in prompt.text.casefold()


def test_built_wheel_contains_the_architect_prompt(tmp_path: Path) -> None:
    """Editable-source success must not hide a prompt omitted from the release wheel."""
    package_root = Path(__file__).parents[1]
    result = subprocess.run(
        ["uv", "build", "--wheel", "--out-dir", str(tmp_path)],
        cwd=package_root,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    wheel = next(tmp_path.glob("studyloop-*.whl"))
    with zipfile.ZipFile(wheel) as archive:
        names = set(archive.namelist())
    assert "studyloop/planning/prompts/architect.md" in names
