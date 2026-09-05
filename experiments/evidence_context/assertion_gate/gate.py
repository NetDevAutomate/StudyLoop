"""Typed-claim release against a reviewed ledger. Not automatic semantic extraction."""

import hashlib

STATES = {"planned", "in_progress", "completed", "unknown"}
BASES = {"reported", "observed"}
FIELDS = {"assertion_id", "target", "state", "basis"}


def check(claim, case):
    if not isinstance(claim, dict) or set(claim) != FIELDS:
        return "invalid_claim"
    if any(not isinstance(v, str) for v in claim.values()):
        return "invalid_claim"
    matches = [r for r in case["assertions"] if r["id"] == claim["assertion_id"]]
    if len(matches) != 1:
        return "unknown_or_ambiguous_assertion"
    record = matches[0]
    if record.get("scope") != case["scope"]:
        return "scope_mismatch"
    if record.get("project") != case["project"]:
        return "project_mismatch"
    required = ("state", "basis", "target", "source", "quote", "source_hash", "start", "end")
    if any(record.get(k) is None for k in required):
        return "missing_metadata"
    if any(
        not isinstance(record[k], str)
        for k in ("state", "basis", "target", "source", "quote", "source_hash")
    ):
        return "invalid_metadata"
    if record["state"] not in STATES or record["basis"] not in BASES:
        return "invalid_metadata"
    if (
        hashlib.sha256(record["source"].encode()).hexdigest() != record["source_hash"]
        or not record["quote"]
        or type(record["start"]) is not int
        or type(record["end"]) is not int
        or not 0 <= record["start"] < record["end"] <= len(record["source"])
        or record["source"][record["start"] : record["end"]] != record["quote"]
    ):
        return "source_binding_failed"
    if record.get("superseded_by") is not None:
        successors = [r for r in case["assertions"] if r["id"] == record["superseded_by"]]
        if (
            len(successors) != 1
            or successors[0]["id"] == record["id"]
            or any(successors[0].get(k) != record[k] for k in ("scope", "project", "target"))
        ):
            return "invalid_supersession"
        return "superseded"
    if claim["target"] != record["target"] or record["target"] not in case["targets"]:
        return "target_mismatch"
    if claim["state"] != record["state"]:
        return "state_mismatch"
    if claim["basis"] != record["basis"]:
        return "basis_mismatch"
    return None


def release(draft, case):
    """Advisory prose never enters rendered output; valid claims release independently."""
    if not isinstance(draft, dict) or set(draft) != {"claims", "answer"}:
        raise ValueError("Invalid draft schema")
    if not isinstance(draft["claims"], list) or not isinstance(draft["answer"], str):
        raise ValueError("Invalid draft fields")
    accepted, blocked, seen = [], [], set()
    catalog = {r["id"]: r for r in case["assertions"]}
    for claim in draft["claims"]:
        reason = check(claim, case)
        if reason:
            blocked.append({"claim": claim, "reason": reason})
            continue
        rid = claim["assertion_id"]
        if rid in seen:
            continue
        seen.add(rid)
        r = catalog[rid]
        basis = (
            "A conversation report records"
            if r["basis"] == "reported"
            else "A tool observation records"
        )
        if r["state"] == "unknown":
            sentence = f"{basis} an unknown execution state for {r['target']}."
        else:
            sentence = f"{basis} {r['target']} as {r['state'].replace('_', ' ')}."
        accepted.append(
            {
                "assertion_id": rid,
                "text": sentence,
                "quote": r["quote"],
                "state": r["state"],
                "basis": r["basis"],
                "target": r["target"],
            }
        )
    return {
        "accepted": accepted,
        "blocked": blocked,
        "text": "\n".join(r["text"] for r in accepted)
        or "No supported claim was selected for this target.",
        "qualification": (
            "State and evidence labels come from the reviewed ledger. This gate checks "
            "conformance to those labels; it does not verify their meaning or authenticity."
        ),
    }
