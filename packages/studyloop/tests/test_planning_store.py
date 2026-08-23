"""File-first persistence contract for study plans."""

from __future__ import annotations

import pytest

from studyloop.planning import models, store
from studyloop.planning.store import (
    InvalidPlanIdError,
    PlanExistsError,
    PlanNotFoundError,
    list_plan_ids,
    list_plans,
    load_plan,
    plan_path,
    plans_dir,
    unique_plan_id,
    validate_plan_id,
)
from studyloop.planning.store import (
    _create_plan as create_plan,
)
from studyloop.planning.store import (
    _delete_plan as delete_plan,
)
from studyloop.planning.store import (
    _save_plan as save_plan,
)


@pytest.fixture(autouse=True)
def isolated_plans_dir(tmp_path, monkeypatch):
    """Point every test at a throwaway plans directory."""
    target = tmp_path / "study-plans"
    monkeypatch.setenv(store.PLANS_DIR_ENV, str(target))
    return target


def _plan(plan_id: str = "demo", title: str = "Demo Plan") -> models.StudyPlan:
    return models.StudyPlan(
        plan_id=plan_id,
        title=title,
        mission=models.Mission(why="Because", success=["Do a thing"]),
        milestones=[models.Milestone(title="Step one", concepts=["thing"])],
        topics=["python"],
    )


def test_plans_dir_honours_the_env_override(isolated_plans_dir) -> None:
    assert plans_dir() == isolated_plans_dir
    assert isolated_plans_dir.is_dir(), "plans dir should be created lazily"


def test_create_then_load_round_trip() -> None:
    create_plan(_plan())
    loaded = load_plan("demo")
    assert loaded.title == "Demo Plan"
    assert loaded.mission.why == "Because"
    assert [m.title for m in loaded.milestones] == ["Step one"]


def test_create_refuses_duplicate_unless_overwrite() -> None:
    create_plan(_plan())
    with pytest.raises(PlanExistsError):
        create_plan(_plan())
    create_plan(_plan(title="Replaced"), overwrite=True)
    assert load_plan("demo").title == "Replaced"


def test_load_missing_plan_raises() -> None:
    with pytest.raises(PlanNotFoundError):
        load_plan("nothing-here")


@pytest.mark.parametrize(
    "bad_id",
    ["../etc/passwd", "a/b", "/absolute", "..", "with space", "UPPER/case", ""],
)
def test_path_traversal_and_malformed_ids_are_rejected(bad_id: str) -> None:
    """The filesystem boundary rejects rather than sanitises."""
    with pytest.raises(InvalidPlanIdError):
        validate_plan_id(bad_id)
    with pytest.raises(InvalidPlanIdError):
        plan_path(bad_id)


def test_validate_accepts_normal_ids_and_normalises_case() -> None:
    assert validate_plan_id("Glue-ETL_01.v2") == "glue-etl_01.v2"


def test_unique_plan_id_suffixes_on_collision() -> None:
    create_plan(_plan(plan_id="glue-etl", title="Glue ETL"))
    assert unique_plan_id("Glue ETL") == "glue-etl-2"
    create_plan(_plan(plan_id="glue-etl-2", title="Glue ETL"))
    assert unique_plan_id("Glue ETL") == "glue-etl-3"


def test_save_is_atomic_and_leaves_no_temp_file(isolated_plans_dir) -> None:
    plan = _plan()
    create_plan(plan)
    save_plan(plan)
    leftovers = list(isolated_plans_dir.glob("*.tmp"))
    assert leftovers == [], f"temp files left behind: {leftovers}"
    assert (isolated_plans_dir / "demo.md").is_file()


def test_save_refreshes_the_updated_timestamp() -> None:
    plan = _plan()
    create_plan(plan)
    original = load_plan("demo").updated
    plan.title = "Changed"
    save_plan(plan)
    assert load_plan("demo").updated >= original


def test_list_plans_skips_an_unparseable_document(isolated_plans_dir) -> None:
    """One malformed file must not hide every other plan."""
    create_plan(_plan(plan_id="good", title="Good Plan"))
    (isolated_plans_dir / "broken.md").write_text(
        "---\nthis: [is not: valid: yaml\n---\n# Broken\n", encoding="utf-8"
    )
    ids = {plan.plan_id for plan in list_plans()}
    assert "good" in ids
    assert "broken" in list_plan_ids(), "the file is still on disk"


def test_list_plans_filters_by_status() -> None:
    create_plan(_plan(plan_id="draft-one", title="Draft One"))
    active = _plan(plan_id="active-one", title="Active One")
    active.status = "active"
    create_plan(active)
    assert [p.plan_id for p in list_plans(status="active")] == ["active-one"]


def test_delete_plan_reports_absence_then_success() -> None:
    assert delete_plan("demo") is False
    create_plan(_plan())
    assert delete_plan("demo") is True
    assert "demo" not in list_plan_ids()


def test_delete_rejects_traversal() -> None:
    with pytest.raises(InvalidPlanIdError):
        delete_plan("../../etc/passwd")


def test_symlink_escaping_the_plans_dir_is_refused(isolated_plans_dir, tmp_path) -> None:
    """A planted symlink must not become an arbitrary-file read.

    ``validate_plan_id`` blocks separators, but a symlink inside the plans
    directory could still point outside it — which would let the web API serve
    any file the process can read.
    """
    isolated_plans_dir.mkdir(parents=True, exist_ok=True)
    outside = tmp_path / "secret.txt"
    outside.write_text("classified", encoding="utf-8")
    (isolated_plans_dir / "sneaky.md").symlink_to(outside)

    with pytest.raises(InvalidPlanIdError):
        load_plan("sneaky")


def test_symlink_within_the_plans_dir_is_still_allowed(isolated_plans_dir) -> None:
    """Containment, not a blanket symlink ban — an in-directory link is fine."""
    create_plan(_plan(plan_id="real", title="Real Plan"))
    (isolated_plans_dir / "alias.md").symlink_to(isolated_plans_dir / "real.md")
    assert load_plan("alias").title == "Real Plan"
