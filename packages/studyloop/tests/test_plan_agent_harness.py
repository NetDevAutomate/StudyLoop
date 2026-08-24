"""Safety contracts for the paid plan-agent maintainer harness."""

from __future__ import annotations

import runpy
from pathlib import Path


def test_harness_allocates_a_unique_subroot_without_deleting_user_plans(
    tmp_path: Path,
) -> None:
    existing = tmp_path / "user-plan.md"
    existing.write_text("# Keep me\n", encoding="utf-8")
    script = Path(__file__).parents[3] / "scripts" / "plan_agent_harness.py"
    namespace = runpy.run_path(str(script), run_name="plan_agent_harness_test")

    first = namespace["fresh_plans_dir"](tmp_path)
    second = namespace["fresh_plans_dir"](tmp_path)

    assert first != second
    assert first.name == second.name == "study-plans"
    assert first.parent.parent == second.parent.parent == tmp_path
    assert existing.read_text(encoding="utf-8") == "# Keep me\n"
