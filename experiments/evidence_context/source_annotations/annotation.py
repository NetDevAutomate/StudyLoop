"""Source checks before the unchanged Stage 15 release boundary."""

from ..assertion_gate.fixtures import assertion
from ..assertion_gate.gate import release
from .capture import canonical, digest, resolve

FIELDS = {"state", "basis", "target", "scope", "quote", "rationale"}


def validate(annotation):
    if not isinstance(annotation, dict) or set(annotation) != FIELDS:
        raise ValueError("Annotation schema mismatch")
    if not isinstance(annotation["state"], str) or annotation["state"] not in {
        "planned",
        "in_progress",
        "completed",
        "unknown",
    }:
        raise ValueError("Invalid state")
    if not isinstance(annotation["basis"], str) or annotation["basis"] not in {
        "reported",
        "observed",
        "unknown",
    }:
        raise ValueError("Invalid basis")
    if any(
        annotation[k] is not None and not isinstance(annotation[k], str)
        for k in ("target", "scope")
    ):
        raise ValueError("Invalid target or scope")
    if any(not isinstance(annotation[k], str) or not annotation[k] for k in ("quote", "rationale")):
        raise ValueError("Quote and rationale required")


def accept(annotation, case, receipts, manifest):
    validate(annotation)
    source = case["record"]
    receipt, error = resolve(source, receipts, manifest)
    reason = error
    if not reason and annotation["quote"] not in source["text"]:
        reason = "quote_not_in_source"
    if not reason:
        expected_basis = "observed" if receipt["origin"] == "process_exit" else "reported"
        if annotation["basis"] != expected_basis:
            reason = "origin_mismatch"
        elif annotation["scope"] != receipt["context"]["scope"]:
            reason = "scope_mismatch"
        elif receipt["context"]["scope"] != case["scope"]:
            reason = "scope_inapplicable"
        elif receipt["context"]["project"] != case["project"]:
            reason = "project_inapplicable"
        elif receipt["origin"] == "process_exit":
            if annotation["state"] != "completed":
                reason = "exit_state_mismatch"
            elif annotation["target"] != receipt["context"]["target"]:
                reason = "invocation_target_mismatch"
    if not reason and (annotation["target"] is None or annotation["target"] not in case["targets"]):
        reason = "target_unresolved_or_inapplicable"
    if reason:
        return {"released": False, "reason": reason, "text": "No source-backed claim released."}
    text = source["text"]
    start = text.index(annotation["quote"])
    row = assertion(
        "E1",
        text,
        annotation["target"],
        annotation["state"],
        annotation["basis"],
        scope=annotation["scope"],
        project=case["project"],
        quote=annotation["quote"],
        start=start,
        end=start + len(annotation["quote"]),
    )
    gate = release(
        {
            "claims": [
                {"assertion_id": "E1", **{k: annotation[k] for k in ("state", "basis", "target")}}
            ],
            "answer": annotation["rationale"],
        },
        {**case, "assertions": [row]},
    )
    return {"released": bool(gate["accepted"]), "reason": None, "text": gate["text"], "gate": gate}


def score(annotation, case, arm):
    # Raw origin/scope are absent. Never score that arm against hidden provenance truth.
    expected = dict(case["expected"])
    if arm == "text":
        expected.update(basis="unknown", scope=None)
    matches = {k: annotation[k] == v for k, v in expected.items()}
    unsupported_basis = (
        annotation["basis"] != "unknown"
        if expected["basis"] == "unknown"
        else annotation["basis"] == "observed" and expected["basis"] != "observed"
    )
    return {
        "field_matches": matches,
        "all_fields_match": all(matches.values()),
        "quote_bound": annotation["quote"] in case["record"]["text"],
        "unsupported_basis": unsupported_basis,
        "state_promotion": expected["state"] != "completed" and annotation["state"] == "completed",
        "target_invention": expected["target"] is None and annotation["target"] is not None,
    }


def sealed(annotation):
    return {"annotation": annotation, "digest": digest(canonical(annotation))}


def integrity_ok(envelope):
    return envelope["digest"] == digest(canonical(envelope["annotation"]))
