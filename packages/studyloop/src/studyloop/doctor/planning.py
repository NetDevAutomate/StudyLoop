"""Agentic-planning checks independent of coding-harness installation."""

from __future__ import annotations

from studyloop.doctor.models import CheckResult
from studyloop.planning.capabilities import PLANNING_CAPABILITY_SCHEMAS
from studyloop.planning.model_config import probe_model_profile, profile_from_config
from studyloop.planning.model_port import MODEL_WIRE_VERSION, load_architect_prompt
from studyloop.planning.scripted_model import run_scripted_preflight


def check_planning_readiness() -> list[CheckResult]:
    """Report deterministic protocol health separately from live endpoint health."""
    results: list[CheckResult] = []
    try:
        prompt = load_architect_prompt()
        results.append(
            CheckResult(
                "config",
                "planning_prompt",
                "pass",
                f"Planning prompt packaged: {prompt.version}",
                "",
                False,
            )
        )
    except RuntimeError as exc:
        results.append(
            CheckResult(
                "config",
                "planning_prompt",
                "fail",
                f"Planning prompt invalid: {exc}",
                "Reinstall StudyLoop from a complete wheel",
                False,
            )
        )

    names = tuple(item.name.value for item in PLANNING_CAPABILITY_SCHEMAS)
    expected = ("prepare_plan", "submit_plan_proposal", "get_plan_proposal")
    catalogue_ok = names == expected
    results.append(
        CheckResult(
            "config",
            "planning_capabilities",
            "pass" if catalogue_ok else "fail",
            f"Planning capability schema v{MODEL_WIRE_VERSION}: {', '.join(names)}",
            "Reinstall StudyLoop; the release-one catalogue must contain "
            "exactly three capabilities",
            False,
        )
    )

    scripted = run_scripted_preflight()
    results.append(
        CheckResult(
            "config",
            "planning_scripted_preflight",
            "pass" if scripted.ok else "fail",
            "Planning scripted preflight passed"
            if scripted.ok
            else "Planning scripted preflight failed",
            "Reinstall StudyLoop before enabling live planning" if not scripted.ok else "",
            False,
        )
    )

    try:
        from studyloop.settings import load_raw_config

        raw = load_raw_config()
    except Exception:
        raw = {}
    planning = raw.get("planning") if isinstance(raw, dict) else None
    model_value = planning.get("model") if isinstance(planning, dict) else None
    profile = profile_from_config(model_value)
    live = False
    if model_value and profile is None:
        results.append(
            CheckResult(
                "config",
                "planning_model",
                "fail",
                "Planning model configuration is invalid",
                "Run studyloop setup with a base URL, model, and secret reference",
                False,
            )
        )
    elif profile is None:
        results.append(
            CheckResult(
                "config",
                "planning_model",
                "info",
                "Planning model not configured",
                "Run studyloop setup while LiteLLM is available or pass explicit planning options",
                False,
            )
        )
    else:
        live = probe_model_profile(profile)
        results.append(
            CheckResult(
                "config",
                "planning_model",
                "pass" if live else "warn",
                f"Planning model {profile.model}: {'reachable' if live else 'unreachable'}",
                "Start the configured gateway or update the planning profile" if not live else "",
                False,
            )
        )

    deterministic_ok = (
        catalogue_ok
        and scripted.ok
        and any(item.name == "planning_prompt" and item.status == "pass" for item in results)
    )
    if live and deterministic_ok:
        readiness = "live certified"
        status = "pass"
    elif deterministic_ok:
        readiness = "scripted only"
        status = "info"
    else:
        readiness = "not ready"
        status = "fail"
    results.append(
        CheckResult(
            "config",
            "planning_readiness",
            status,
            f"Planning readiness: {readiness}",
            "Resolve the failed planning checks above" if status == "fail" else "",
            False,
        )
    )
    return results
