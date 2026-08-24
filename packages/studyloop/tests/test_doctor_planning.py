"""Doctor reporting for deterministic and live planning readiness."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
import yaml

if TYPE_CHECKING:
    from pathlib import Path


def _write_config(path: Path, planning: object) -> None:
    path.write_text(yaml.safe_dump({"planning": planning}, sort_keys=False))


def test_doctor_reports_prompt_schema_exact_catalogue_and_scripted_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from studyloop.doctor.planning import check_planning_readiness

    config = tmp_path / "config.yaml"
    config.write_text("{}\n")
    monkeypatch.setenv("STUDYLOOP_CONFIG", str(config))

    results = check_planning_readiness()
    by_name = {item.name: item for item in results}

    assert by_name["planning_prompt"].status == "pass"
    assert "architect-v1" in by_name["planning_prompt"].message
    assert by_name["planning_capabilities"].status == "pass"
    assert (
        "prepare_plan, submit_plan_proposal, get_plan_proposal"
        in by_name["planning_capabilities"].message
    )
    assert by_name["planning_scripted_preflight"].status == "pass"
    assert by_name["planning_model"].status == "info"
    assert "not configured" in by_name["planning_model"].message.casefold()
    assert "scripted only" in by_name["planning_readiness"].message.casefold()


@pytest.mark.parametrize(
    ("reachable", "expected"),
    [(False, "unreachable"), (True, "live certified")],
)
def test_doctor_distinguishes_unreachable_from_live_certified(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    reachable: bool,
    expected: str,
) -> None:
    from studyloop.doctor.planning import check_planning_readiness

    config = tmp_path / "config.yaml"
    _write_config(
        config,
        {
            "model": {
                "base_url": "http://127.0.0.1:4000/v1",
                "model": "planner-model",
                "api_key_ref": "env:VERY_PRIVATE_PLANNING_KEY",  # pragma: allowlist secret
            }
        },
    )
    monkeypatch.setenv("STUDYLOOP_CONFIG", str(config))
    monkeypatch.setattr("studyloop.doctor.planning.probe_model_profile", lambda _profile: reachable)

    results = check_planning_readiness()
    rendered = "\n".join(item.message for item in results)

    assert expected in rendered.casefold()
    assert "VERY_PRIVATE_PLANNING_KEY" not in rendered


def test_doctor_registry_includes_planning_without_using_harness_status() -> None:
    from studyloop.cli._doctor import _get_registry

    registry = _get_registry()
    names = {item.name for item in registry.run_category("config")}

    assert "planning_prompt" in names
    assert "planning_capabilities" in names
    assert "planning_scripted_preflight" in names
    assert "planning_readiness" in names
