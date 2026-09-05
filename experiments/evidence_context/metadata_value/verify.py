"""Verify proposed fields against a narrow observed-log grammar, not natural language."""

import re

FIELDS = ("revision", "workload", "environment", "metric", "winner")
DECLARATION = re.compile(r"(revision|workload|environment|metric|winner): (\S.*)")


def declarations(text):
    lines = text.splitlines()
    if lines.count("[observed]") != 1 or lines.count("[/observed]") != 1:
        raise ValueError("Exactly one observed block required")
    start, end = lines.index("[observed]"), lines.index("[/observed]")
    if start >= end:
        raise ValueError("Invalid block order")
    found = {field: [] for field in FIELDS}
    for line in lines[start + 1 : end]:
        match = DECLARATION.fullmatch(line)
        if match:
            found[match[1]].append({"value": match[2], "quote": line})
    return found


def proposal_valid(proposal):
    return (
        isinstance(proposal, dict)
        and set(proposal) == set(FIELDS)
        and all(
            isinstance(v, dict)
            and set(v) == {"value", "quote"}
            and (
                (v["value"] is None and v["quote"] is None)
                or (
                    isinstance(v["value"], str)
                    and bool(v["value"])
                    and isinstance(v["quote"], str)
                    and bool(v["quote"])
                )
            )
            for v in proposal.values()
        )
    )


def verify(text, proposal):
    try:
        found = declarations(text)
    except ValueError:
        found = None
    valid = proposal_valid(proposal)
    result = {}
    for field in FIELDS:
        value, quote, status = None, None, "rejected"
        if found is None:
            reason = "invalid_source_block"
        elif not valid:
            reason = "invalid_proposal_schema"
        elif len(found[field]) > 1:
            reason = "ambiguous_source_field"
            if proposal[field]["value"] is None:
                status = "unknown"
        elif not found[field]:
            reason = "field_absent_from_observed_block"
            if proposal[field]["value"] is None:
                status = "unknown"
        elif proposal[field]["value"] is None:
            status, reason = "unknown", "extractor_omitted_present_field"
        elif proposal[field] != found[field][0]:
            reason = "quote_or_value_not_supported_by_field"
        else:
            value, quote = proposal[field]["value"], proposal[field]["quote"]
            status, reason = "matched", "unique_exact_declaration"
        result[field] = {"value": value, "quote": quote, "status": status, "reason": reason}
    return result


def reference_extraction(text):
    """Offline demonstration only; this is not substituted for live extraction."""
    found = declarations(text)
    return {
        field: entries[0] if len(entries) == 1 else {"value": None, "quote": None}
        for field, entries in found.items()
    }


def assess_answer(answer, case):
    if not isinstance(answer, dict) or set(answer) != {
        "recommendation",
        "explanation",
        "citations",
        "next_check",
    }:
        raise ValueError("Invalid answer schema")
    if answer["recommendation"] not in {"A", "B", "none"}:
        raise ValueError("Invalid recommendation")
    if any(
        not isinstance(answer[k], str) or not answer[k].strip()
        for k in ("explanation", "next_check")
    ):
        raise ValueError("Explanation and next check required")
    citations = answer["citations"]
    if not isinstance(citations, list) or any(
        not isinstance(c, dict)
        or set(c) != {"quote", "supports"}
        or any(not isinstance(c[k], str) or not c[k].strip() for k in ("quote", "supports"))
        for c in citations
    ):
        raise ValueError("Invalid citations")
    actual, expected = answer["recommendation"], case["expected_choice"]
    return {
        "choice_matches": actual == expected,
        "unsupported_endorsement": actual != "none" and actual != expected,
        "missed_supported_choice": actual == "none" and expected != "none",
        "citations_locatable": bool(citations)
        and all(c["quote"] in case["source"]["text"] for c in citations),
        "explanation_entailment": "not_automatically_measured",
        "learner_value": "not_measured",
    }
