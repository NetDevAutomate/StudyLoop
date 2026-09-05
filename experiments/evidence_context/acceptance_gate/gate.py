"""Application-owned snapshot checks; no model prose is released as verified text."""

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from ..decision_contract import policy
from ..decision_contract.policy import assess, derive, validate

POLICY_VERSION = "stage8-f7f6796"
POLICY_DIGEST = hashlib.sha256(Path(policy.__file__).read_bytes()).hexdigest()


@dataclass(frozen=True)
class Snapshot:
    payload: str

    @classmethod
    def freeze(cls, case):
        # Serialization copies mutable caller data and rejects non-JSON numeric values.
        payload = json.dumps(
            {"case": case, "policy_version": POLICY_VERSION, "policy_digest": POLICY_DIGEST},
            sort_keys=True,
            allow_nan=False,
        )
        validate(json.loads(payload)["case"])
        return cls(payload)

    @property
    def identity(self):
        return hashlib.sha256(self.payload.encode()).hexdigest()

    def case(self):
        data = json.loads(self.payload)
        if data["policy_version"] != POLICY_VERSION or data.get("policy_digest") != POLICY_DIGEST:
            raise ValueError("Unsupported policy version")
        return data["case"]


def accept(snapshot, envelope):
    """Check a draft against this trusted snapshot, never model-supplied metadata."""
    case = snapshot.case()
    reference = derive(case)
    checks = {}
    reasons = []
    if not isinstance(envelope, dict) or set(envelope) != {"snapshot_id", "answer"}:
        reasons = ["invalid_envelope"]
    elif envelope["snapshot_id"] != snapshot.identity:
        reasons = ["stale_or_wrong_snapshot"]
    else:
        expected = {
            k: reference["decision"][k] for k in ("sufficiency", "recommendation", "reason_code")
        }
        expected["applicability"] = {
            s["id"]: s["applicability"] for s in reference["source_assessments"]
        }
        try:
            checks = assess(envelope["answer"], case, expected)
            reasons = [
                key + "_mismatch"
                for key in (
                    "integrity",
                    "provenance",
                    "applicability",
                    "decision",
                    "basis_coverage",
                )
                if not checks[key]
            ]
        except (ValueError, TypeError, KeyError):
            reasons = ["invalid_answer_schema"]
    return {
        "status": "draft_diverges" if reasons else "draft_agrees",
        "reasons": reasons,
        "checks": checks,
        "snapshot_id": snapshot.identity,
        "policy_version": POLICY_VERSION,
        "release_kind": "policy_rendered",
        "draft_prose": "not_released_or_semantically_validated",
        "release_notice": (
            "Draft withheld; independent policy fallback follows."
            if reasons
            else "Draft fields agree; policy rendering follows, not model prose."
        ),
        "released_answer": reference,
    }
