"""Measure integrity, source-origin checks and surviving semantic failures separately."""

import copy

from .annotation import accept, integrity_ok, sealed
from .capture import resolve


def reference(case):
    return {
        **case["expected"],
        "quote": case["record"]["text"],
        "rationale": "Offline reference labels, not model output.",
    }


def run(data):
    cases = {c["id"]: c for c in data["cases"]}
    rows = []

    def probe(name, cid, changes=None, mutate=None, expected=False, gap=False, postseal=False):
        case = copy.deepcopy(cases[cid])
        receipts = copy.deepcopy(data["receipts"])
        manifest = copy.deepcopy(data["manifest"])
        annotation = reference(case)
        if mutate:
            mutate(case, receipts, manifest)
        envelope = sealed(annotation)
        annotation.update(changes or {})
        if not postseal:
            envelope = sealed(annotation)
        annotation_intact = integrity_ok(envelope)
        _, source_error = resolve(case["record"], receipts, manifest)
        intact = annotation_intact and source_error is None
        decision = accept(annotation, case, receipts, manifest)
        released = intact and decision["released"]
        rows.append(
            {
                "name": name,
                "integrity_only_accepts": intact,
                "annotation_integrity_ok": annotation_intact,
                "source_integrity_error": source_error,
                "source_gate_accepts": released,
                "expected_semantic_release": expected,
                "matches": released == expected,
                "known_gap": gap,
                "reason": "annotation_changed" if not annotation_intact else decision["reason"],
                "release": decision["text"] if released else "Withheld",
            }
        )

    for cid in ("real_exit", "quoted_report", "failed_exit", "progress_report"):
        probe("honest_" + cid, cid, expected=True)
    probe("body_changed_after_capture", "altered_body")
    probe(
        "receipt_changed_after_capture",
        "real_exit",
        mutate=lambda c, r, m: r["R01"].update(origin="conversation_message"),
    )
    probe(
        "swapped_receipt_same_text",
        "real_exit",
        mutate=lambda c, r, m: c["record"].update(receipt_id="R02"),
    )
    probe("annotation_changed_after_seal", "quoted_report", {"basis": "observed"}, postseal=True)
    probe("wrong_basis_before_seal", "quoted_report", {"basis": "observed"})
    probe("wrong_exit_state_before_seal", "real_exit", {"state": "in_progress"})
    probe("wrong_invocation_target_before_seal", "real_exit", {"target": "parser.smoke@r8"})
    probe("wrong_scope_before_seal", "real_exit", {"scope": "work"})
    probe("wrong_narrative_state_before_seal", "progress_report", {"state": "completed"}, gap=True)
    probe(
        "wrong_narrative_target_before_seal",
        "quoted_report",
        {"target": "parser.smoke@r8"},
        mutate=lambda c, r, m: c.update(targets=["parser.smoke@r8"]),
        gap=True,
    )
    return rows
