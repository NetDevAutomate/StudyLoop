"""Snapshot-bound source adapter; policy-rendered results never contain model prose."""

import hashlib
import json
from dataclasses import dataclass

from ..acceptance_gate.gate import Snapshot
from ..decision_contract.policy import SCOPE, derive
from ..metadata_value.verify import FIELDS, declarations, verify


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


@dataclass(frozen=True)
class EvidenceSnapshot:
    payload: str

    @classmethod
    def freeze(cls, source, target, proposal):
        if set(target) != set(SCOPE) or any(
            not isinstance(v, str) or not v.strip() for v in target.values()
        ):
            raise ValueError("Complete target required")
        if (
            not isinstance(source, dict)
            or set(source) != {"id", "kind", "text"}
            or any(not isinstance(v, str) or not v.strip() for v in source.values())
        ):
            raise ValueError("Invalid source envelope")
        return cls(
            json.dumps(
                {"source": source, "target": target, "proposal": proposal},
                sort_keys=True,
                allow_nan=False,
            )
        )

    @property
    def identity(self):
        return digest(json.loads(self.payload))

    def read(self):
        return json.loads(self.payload)


def source_span(source, start, end):
    return {
        "origin": "source_text",
        "version": digest(source),
        "source_id": source["id"],
        "start": start,
        "end": end,
        "quote": source["text"][start:end],
    }


def declarations_with_spans(source):
    found = declarations(source["text"])
    # Follow the same explicit block boundaries, while preserving actual offsets.
    inside, offset = False, 0
    spans = {field: [] for field in FIELDS}
    for raw in source["text"].splitlines(keepends=True):
        line = raw.splitlines()[0]
        if line == "[/observed]":
            inside = False
        elif inside:
            for field in FIELDS:
                if any(entry["quote"] == line for entry in found[field]):
                    spans[field].append(source_span(source, offset, offset + len(line)))
        elif line == "[observed]":
            inside = True
        offset += len(raw)
    return found, spans


def pointer(origin, container, field):
    return {
        "origin": origin,
        "version": digest(container),
        "field": field,
        "value": container[field],
    }


def resolve(snapshot, locator):
    """Verify origin, version and exact span; not natural-language entailment."""
    data = snapshot.read()
    origin = locator.get("origin")
    if origin == "source_text":
        source = data["source"]
        start, end = locator.get("start"), locator.get("end")
        return (
            locator.get("version") == digest(source)
            and locator.get("source_id") == source["id"]
            and type(start) is int
            and type(end) is int
            and 0 <= start < end <= len(source["text"])
            and source["text"][start:end] == locator.get("quote")
        )
    if origin in {"source_metadata", "target"}:
        container = data["source"] if origin == "source_metadata" else data["target"]
        field = locator.get("field")
        return (
            isinstance(field, str)
            and field in container
            and locator.get("version") == digest(container)
            and locator.get("value") == container[field]
        )
    return False


def release(snapshot, mode="source_adapter"):
    if mode not in {"checked_only", "source_adapter"}:
        raise ValueError("Unknown boundary mode")
    data = snapshot.read()
    source, target, proposal = data["source"], data["target"], data["proposal"]
    checked = verify(source["text"], proposal)
    issues, facts = [], []
    source_kind = pointer("source_metadata", source, "kind")
    facts.append({"field": "source_kind", "value": source["kind"], "basis": [source_kind]})
    if source["kind"] != "artifact":
        issues.append(
            {
                "code": "not_observed_artifact",
                "basis": [source_kind],
                "next_check": "Obtain an observed artifact; a report is not a test result.",
            }
        )
    values = dict.fromkeys(FIELDS)
    try:
        found, spans = declarations_with_spans(source)
    except ValueError:
        found = None
        basis = [source_span(source, 0, len(source["text"]))]
        issues.append(
            {
                "code": "invalid_observed_block",
                "basis": basis,
                "next_check": "Obtain one unambiguous observed block for this test.",
            }
        )
    if found is not None:
        whole = source_span(source, 0, len(source["text"]))
        for field in FIELDS:
            entries = found[field]
            basis = spans[field] or [whole]
            if field in SCOPE:
                basis = [*basis, pointer("target", target, field)]
            code = None
            if len(entries) != 1:
                code = "missing_" + field if not entries else "ambiguous_" + field
                action = (
                    f"Record {field} in a new observed artifact; do not infer it."
                    if not entries
                    else f"Resolve duplicate {field} declarations with a new check."
                )
            elif mode == "checked_only" and checked[field]["status"] != "matched":
                code = "unaccepted_candidate_" + field
                action = f"Re-extract {field} from the original source and verify its exact span."
            else:
                values[field] = entries[0]["value"]
                if field in SCOPE and values[field] != target[field]:
                    code = "mismatching_" + field
                    action = (
                        f"Run the check with {field}={target[field]}; "
                        "retain the old result separately."
                    )
                elif field == "winner" and values[field] not in {"A", "B"}:
                    code = "invalid_winner"
                    action = "Obtain one observed winner A or B under the complete target scope."
            facts.append({"field": field, "value": values[field], "basis": basis})
            if code:
                issues.append({"code": code, "basis": basis, "next_check": action})
    # Unknown winner cannot be encoded as an invented valid conclusion for Stage 8.
    # Unknown/unsupported source kinds likewise cannot be silently promoted to artifact.
    normalized_sources = []
    if values["winner"] in {"A", "B"} and source["kind"] in {"artifact", "report"}:
        normalized_sources.append(
            {
                "id": source["id"],
                "provenance": source["kind"],
                "conclusion": values["winner"],
                "requirement_match": False,
                "scope": {field: values[field] for field in SCOPE},
            }
        )
    normalized = {"decision_mode": "measured", "target": target, "sources": normalized_sources}
    policy_snapshot = Snapshot.freeze(normalized)
    answer = derive(policy_snapshot.case())
    decision = answer["decision"]
    # Issues may describe an inapplicable/missing field; the existing policy determines choice.
    if issues:
        decision["next_check"] = " ".join(issue["next_check"] for issue in issues)
    return {
        "snapshot_id": snapshot.identity,
        "policy_snapshot_id": policy_snapshot.identity,
        "mode": mode,
        "release_kind": "policy_rendered",
        "decision": decision,
        "source_assessments": answer["source_assessments"],
        "facts": facts,
        "issues": issues,
        "candidate_checks": checked,
        "derivation": (
            "original_source_reparsed_explicitly"
            if mode == "source_adapter"
            else "matched_candidate_fields_only"
        ),
        "source_authenticity": "not_verified",
        "model_prose": "never_released",
    }


def compare_draft(snapshot, envelope, mode="source_adapter"):
    """Draft agreement is telemetry; released content comes entirely from policy."""
    result = release(snapshot, mode)
    valid_binding = isinstance(envelope, dict) and envelope.get("snapshot_id") == snapshot.identity
    draft = envelope.get("answer") if valid_binding else None
    valid_choice = isinstance(draft, dict) and draft.get("recommendation") in {"A", "B", "none"}
    result["draft_status"] = (
        "wrong_snapshot_or_envelope"
        if not valid_binding
        else "choice_agrees"
        if valid_choice and draft["recommendation"] == result["decision"]["recommendation"]
        else "choice_diverges_or_invalid"
    )
    return result
