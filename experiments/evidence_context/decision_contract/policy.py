"""Deterministic policy for authored synthetic facts, not transcript extraction."""

SCOPE = ("revision", "workload", "environment", "metric")


def validate(case):
    if case["decision_mode"] not in {"measured", "requirement_fit"}:
        raise ValueError("Unknown decision mode")
    if any(not isinstance(case["target"].get(k), str) or not case["target"][k] for k in SCOPE):
        raise ValueError("Complete target scope required")
    ids = set()
    for source in case["sources"]:
        if not isinstance(source["id"], str) or not source["id"] or source["id"] in ids:
            raise ValueError("Unique source IDs required")
        ids.add(source["id"])
        if source["provenance"] not in {"report", "artifact"}:
            raise ValueError("Unknown source kind")
        if source["conclusion"] not in {"A", "B"}:
            raise ValueError("Unknown conclusion")
        if not isinstance(source["requirement_match"], bool) or not isinstance(
            source["scope"], dict
        ):
            raise ValueError("Invalid source metadata")
        if any(
            v is not None and (not isinstance(v, str) or not v) for v in source["scope"].values()
        ):
            raise ValueError("Invalid scope value")


def applicability(source, target):
    if source["provenance"] == "report":
        return "not_validation", "An agent report is a claim, not an observed check."
    mismatch = [
        k for k in SCOPE if source["scope"].get(k) is not None and source["scope"][k] != target[k]
    ]
    if mismatch:
        details = "; ".join(
            f"{k}: tested {source['scope'][k]}, needed {target[k]}" for k in mismatch
        )
        return "inapplicable", details
    missing = [k for k in SCOPE if source["scope"].get(k) is None]
    if missing:
        return "unknown", "Missing scope: " + ", ".join(missing) + "; do not assume a match."
    return "applicable", "Revision, workload, environment and metric match the target."


def derive(case):
    validate(case)
    assessments = []
    applicable = []
    for source in case["sources"]:
        state, reason = applicability(source, case["target"])
        assessments.append(
            {
                "id": source["id"],
                "provenance": source["provenance"],
                "applicability": state,
                "reason": reason,
            }
        )
        if state == "applicable":
            applicable.append(source)
    options = {s["conclusion"] for s in applicable}
    fit = [s for s in case["sources"] if s["provenance"] == "report" and s["requirement_match"]]
    fit_options = {s["conclusion"] for s in fit}
    if len(options) == 1:
        sufficiency, recommendation = "supported", next(iter(options))
        basis = applicable
        reason_code = "applicable_observation"
        explanation = f"Applicable fixture checks support {recommendation} for the stated target."
        check = "Reproduce independently before applying this synthetic finding to a real system."
    elif len(options) > 1:
        sufficiency, recommendation = "insufficient", "none"
        basis = applicable
        reason_code = "conflicting_observations"
        explanation = "Applicable checks disagree; matching scope does not reconcile their results."
        check = "Reproduce both checks under the target conditions and investigate the discrepancy."
    elif case["decision_mode"] == "requirement_fit" and len(fit_options) == 1:
        sufficiency, recommendation = "conditional", next(iter(fit_options))
        basis = fit
        reason_code = "requirement_fit_only"
        explanation = (
            f"Reports describe {recommendation} as fitting the requirement, "
            "without measuring success."
        )
        check = "Run a check of the proposed option against the complete target scope."
    else:
        sufficiency, recommendation = "insufficient", "none"
        basis = case["sources"]
        reason_code = "no_applicable_observation"
        explanation = "No applicable check establishes a choice under this decision's requirements."
        check = (
            "Obtain a comparative check with recorded revision, workload, environment and metric."
        )
    target = ", ".join(f"{k}={case['target'][k]}" for k in SCOPE)
    return {
        "source_assessments": assessments,
        "decision": {
            "sufficiency": sufficiency,
            "recommendation": recommendation,
            "reason_code": reason_code,
            "basis_ids": [s["id"] for s in basis],
            "explanation": explanation,
            "limitation": "Synthetic scenario only; source authenticity is not verified. Target: "
            + target,
            "next_check": check,
        },
    }


def assess(answer, case, expected):
    """Separate mechanical integrity and fixture labels from unmeasured entailment."""
    if not isinstance(answer, dict) or set(answer) != {"source_assessments", "decision"}:
        raise ValueError("Wrong contract schema")
    rows, decision = answer["source_assessments"], answer["decision"]
    if not isinstance(rows, list) or not isinstance(decision, dict):
        raise ValueError("Wrong contract types")
    seen = {}
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"id", "provenance", "applicability", "reason"}:
            raise ValueError("Wrong source assessment")
        if not isinstance(row["id"], str) or row["id"] in seen:
            raise ValueError("Duplicate or invalid source ID")
        if (
            row["provenance"] not in {"report", "artifact"}
            or row["applicability"]
            not in {"not_validation", "applicable", "inapplicable", "unknown"}
            or not isinstance(row["reason"], str)
            or not row["reason"].strip()
        ):
            raise ValueError("Invalid assessment category or explanation")
        seen[row["id"]] = row
    if set(decision) != {
        "sufficiency",
        "recommendation",
        "reason_code",
        "basis_ids",
        "explanation",
        "limitation",
        "next_check",
    }:
        raise ValueError("Wrong decision fields")
    if decision["sufficiency"] not in {"supported", "conditional", "insufficient"} or decision[
        "recommendation"
    ] not in {"A", "B", "none"}:
        raise ValueError("Wrong decision categories")
    if any(
        not isinstance(decision[k], str) or not decision[k].strip()
        for k in ("explanation", "limitation", "next_check")
    ):
        raise ValueError("Decision explanations required")
    if decision["reason_code"] not in {
        "applicable_observation",
        "conflicting_observations",
        "requirement_fit_only",
        "no_applicable_observation",
    }:
        raise ValueError("Unknown decision reason")
    basis = decision["basis_ids"]
    if not isinstance(basis, list) or any(not isinstance(i, str) for i in basis):
        raise ValueError("Invalid basis IDs")
    sources = {s["id"]: s for s in case["sources"]}
    integrity = (
        set(seen) == set(sources)
        and len(basis) == len(set(basis))
        and set(basis) <= set(sources)
        and (bool(basis) or not sources)
    )
    pairing = (
        decision["sufficiency"] == "insufficient" and decision["recommendation"] == "none"
    ) or (
        decision["sufficiency"] in {"supported", "conditional"}
        and decision["recommendation"] in {"A", "B"}
    )
    integrity = (
        integrity
        and pairing
        and (decision["sufficiency"] != "conditional" or case["decision_mode"] == "requirement_fit")
    )
    provenance = set(seen) == set(sources) and all(
        seen[i]["provenance"] == s["provenance"] for i, s in sources.items()
    )
    applicability_ok = {i: r["applicability"] for i, r in seen.items()} == expected["applicability"]
    decision_ok = all(
        decision[k] == expected[k] for k in ("sufficiency", "recommendation", "reason_code")
    )
    reference_basis = set(derive(case)["decision"]["basis_ids"])
    basis_ok = reference_basis <= set(basis)
    return {
        "integrity": integrity,
        "provenance": provenance,
        "applicability": applicability_ok,
        "decision": decision_ok,
        "basis_coverage": basis_ok,
        "all_mechanical_checks": all(
            (integrity, provenance, applicability_ok, decision_ok, basis_ok)
        ),
        "explanation_entailment": "separate_review_required",
        "learner_value": "not_measured",
    }
