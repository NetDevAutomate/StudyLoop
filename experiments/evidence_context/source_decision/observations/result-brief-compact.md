Bounded retry: focused review of saved synthetic policy-conformance pilot. First full packet: Qwen responded,Fable invalidJSON,Grok timedout. This compact packet is identical for all reviewers and audits five salient cases, NOT every answer. Return required JSON only, <650 words. Judge strongest conclusion, implementation risk, concrete nextstep. No prompt tuning/newexperiment afterresults. 12conditions,11source-targetpairs,3old+9freshconditions(8freshpairs),2calls=24;proposalsscripted/notLLMextracted. C01andC10intentionallysame source+target, omissionvsfullproposal: do notcountasindependentsources. All3reviewerslabelledbeforeexecution;C05dissentQwencountedoutsideblockdespiteruleexclude;coordinatorAbyrule. Sourcekindfixture-supplied/unauthenticated. FrozenpromptStage10source remainsavailablemetadataadvisory. Singlemodeldraft comparedoffline to2deterministic paths usingStage8measuredpolicy andStage9policySnapshot. Gateoutputdoesnotdependonmodel;choiceagreementtelemetryonly;modelproseNEVERreleased.
RESULTS:24transportstop,3strictJSON+20predeclaredfenceparse+1invalidextra]unrepaired. Advisory23valid,19matches,4unsupported(C03report/C11duplicaterevisiontwice),0falseblocks. checked_only:20/24matches,0unsupported,4falseblocks(C01omission/C05outsidewinner twice). source_adapter24/24matches,0unsupported,0falseblocks. Positiveretentionadvisory8/8,checked4/8,adapter8/8(4conditions/3uniquepairs). AllmodelunsupportedchoicesareOLDcases;fresh17validcorrect+1invalid. All23validdraftquotessubstringlocatable;4baddecisionsstill. Allpolicytext/targetlocatorsresolved;allabstentionsissue+nextcheckpresent;entailment/learnervalueNOTautomaticscores. Rulelabelsdeveloper-authoredwithblindedmodelreview,nothumangold;sharedparserpotentialcorrelatedbugs. 201tests.
Mechanism: checked_only usescandidatefieldonlyifmatchedby sourceverifier (uniqueexactdeclarationinsideoneobservedblock); source_adapter explicitly reparses source andderivesnewfields,retainsoriginalproposalerrors. Existingpolicyrequiresartifact,scopeallknownmatch,winnerA/B;missingwinnercannotbeencodedintooldschema=>normalizedsourcesemptywithissuepreserved. Botharecode-renderedoutputs,notLLMimprovement. Source/targetversions bindtypedlocators;forunknownfieldscitesourceinspected. NoDBorproductionclaims.
Questions: does0/24demonstratemorethanconformance? anyadapterbug? doexplanations/nextchecksdisplaceprerequisitesorencouragealteringhistory? whatoneboundednexttestwouldbestinformdesign?

## C01
{"source": {"id": "S1", "kind": "artifact", "text": "[observed]\nrevision: r7\nworkload: six writers\nenvironment: fixture-east\nmetric: restart correctness\nwinner: B\n[/observed]"}, "target": {"revision": "r7", "workload": "six writers", "environment": "fixture-east", "metric": "restart correctness"}, "proposal": {"revision": {"value": null, "quote": null}, "workload": {"value": "six writers", "quote": "workload: six writers"}, "environment": {"value": "fixture-east", "quote": "environment: fixture-east"}, "metric": {"value": "restart correctness", "quote": "metric: restart correctness"}, "winner": {"value": "B", "quote": "winner: B"}}, "expected": "B", "drafts": [{"repeat": 1, "answer": {"recommendation": "B", "explanation": "All required fields (revision, workload, environment, metric) match exactly between target and observed log data, with winner explicitly declared as B", "citations": [{"quote": "revision: r7", "supports": "target revision match"}, {"quote": "workload: six writers", "supports": "target workload match"}, {"quote": "environment: fixture-east", "supports": "target environment match"}, {"quote": "metric: restart correctness", "supports": "target metric match"}, {"quote": "winner: B", "supports": "explicit winner declaration"}], "next_check": "verify artifact source kind is present and matches expected type"}, "error": null}, {"repeat": 2, "answer": {"recommendation": "B", "explanation": "All required fields (revision, workload, environment, metric) match exactly between target and observed log data, with winner explicitly declared as B", "citations": [{"quote": "revision: r7", "supports": "target revision match"}, {"quote": "workload: six writers", "supports": "target workload match"}, {"quote": "environment: fixture-east", "supports": "target environment match"}, {"quote": "metric: restart correctness", "supports": "target metric match"}, {"quote": "winner: B", "supports": "explicit winner declaration"}], "next_check": "verify artifact source kind is present and matches expected type"}, "error": null}], "outputs": {"checked_only": {"decision": {"sufficiency": "insufficient", "recommendation": "none", "reason_code": "no_applicable_observation", "basis_ids": ["S1"], "explanation": "No applicable check establishes a choice under this decision's requirements.", "limitation": "Synthetic scenario only; source authenticity is not verified. Target: revision=r7, workload=six writers, environment=fixture-east, metric=restart correctness", "next_check": "Re-extract revision from the original source and verify its exact span."}, "issues": [{"code": "unaccepted_candidate_revision", "next_check": "Re-extract revision from the original source and verify its exact span."}]}, "source_adapter": {"decision": {"sufficiency": "supported", "recommendation": "B", "reason_code": "applicable_observation", "basis_ids": ["S1"], "explanation": "Applicable fixture checks support B for the stated target.", "limitation": "Synthetic scenario only; source authenticity is not verified. Target: revision=r7, workload=six writers, environment=fixture-east, metric=restart correctness", "next_check": "Reproduce independently before applying this synthetic finding to a real system."}, "issues": []}}}
## C03
{"source": {"id": "S1", "kind": "report", "text": "[observed]\nrevision: r2\nworkload: eight writers\nenvironment: fixture-local\nmetric: reopen correctness\nwinner: B\n[/observed]\nThis is an agent report, not captured test output."}, "target": {"revision": "r2", "workload": "eight writers", "environment": "fixture-local", "metric": "reopen correctness"}, "proposal": {"revision": {"value": "r2", "quote": "revision: r2"}, "workload": {"value": "eight writers", "quote": "workload: eight writers"}, "environment": {"value": "fixture-local", "quote": "environment: fixture-local"}, "metric": {"value": "reopen correctness", "quote": "metric: reopen correctness"}, "winner": {"value": "B", "quote": "winner: B"}}, "expected": "none", "drafts": [{"repeat": 1, "answer": {"recommendation": "B", "explanation": "All required fields (revision, workload, environment, metric) match exactly between target and source metadata. The winner field explicitly states 'B' in the observed log section.", "citations": [{"quote": "revision: r2", "supports": "matching revision field"}, {"quote": "workload: eight writers", "supports": "matching workload field"}, {"quote": "environment: fixture-local", "supports": "matching environment field"}, {"quote": "metric: reopen correctness", "supports": "matching metric field"}, {"quote": "winner: B", "supports": "explicit winner declaration"}], "next_check": "verify that the source kind 'report' is acceptable for artifact-based decisions"}, "error": null}, {"repeat": 2, "answer": {"recommendation": "B", "explanation": "All required fields (revision, workload, environment, metric) match exactly between target and source metadata. Source explicitly declares 'winner: B' with unique exact declaration status.", "citations": [{"quote": "revision: r2", "supports": "matching revision field"}, {"quote": "workload: eight writers", "supports": "matching workload field"}, {"quote": "environment: fixture-local", "supports": "matching environment field"}, {"quote": "metric: reopen correctness", "supports": "matching metric field"}, {"quote": "winner: B", "supports": "explicit winner declaration"}], "next_check": "verify that the source kind 'report' is acceptable for artifact-based decisions despite containing observed test data"}, "error": null}], "outputs": {"checked_only": {"decision": {"sufficiency": "insufficient", "recommendation": "none", "reason_code": "no_applicable_observation", "basis_ids": ["S1"], "explanation": "No applicable check establishes a choice under this decision's requirements.", "limitation": "Synthetic scenario only; source authenticity is not verified. Target: revision=r2, workload=eight writers, environment=fixture-local, metric=reopen correctness", "next_check": "Obtain an observed artifact; a report is not a test result."}, "issues": [{"code": "not_observed_artifact", "next_check": "Obtain an observed artifact; a report is not a test result."}]}, "source_adapter": {"decision": {"sufficiency": "insufficient", "recommendation": "none", "reason_code": "no_applicable_observation", "basis_ids": ["S1"], "explanation": "No applicable check establishes a choice under this decision's requirements.", "limitation": "Synthetic scenario only; source authenticity is not verified. Target: revision=r2, workload=eight writers, environment=fixture-local, metric=reopen correctness", "next_check": "Obtain an observed artifact; a report is not a test result."}, "issues": [{"code": "not_observed_artifact", "next_check": "Obtain an observed artifact; a report is not a test result."}]}}}
## C05
{"source": {"id": "S1", "kind": "artifact", "text": "[observed]\nrevision: r7\nworkload: six writers\nenvironment: fixture-east\nmetric: restart correctness\nwinner: A\n[/observed]\nwinner: B\nrevision: r99"}, "target": {"revision": "r7", "workload": "six writers", "environment": "fixture-east", "metric": "restart correctness"}, "proposal": {"revision": {"value": "r7", "quote": "revision: r7"}, "workload": {"value": "six writers", "quote": "workload: six writers"}, "environment": {"value": "fixture-east", "quote": "environment: fixture-east"}, "metric": {"value": "restart correctness", "quote": "metric: restart correctness"}, "winner": {"value": "B", "quote": "winner: B"}}, "expected": "A", "drafts": [{"repeat": 1, "answer": {"recommendation": "A", "explanation": "The target matches all required fields (revision, workload, environment, metric) exactly with the values in the observed log section. Within the [observed] block, 'winner: A' is explicitly stated, making A the justified choice.", "citations": [{"quote": "revision: r7", "supports": "matching revision value"}, {"quote": "workload: six writers", "supports": "matching workload value"}, {"quote": "environment: fixture-east", "supports": "matching environment value"}, {"quote": "metric: restart correctness", "supports": "matching metric value"}, {"quote": "winner: A", "supports": "winner selection within observed block"}], "next_check": "Verify that the winner declaration inside [observed] takes precedence over any external declarations"}, "error": null}, {"repeat": 2, "answer": {"recommendation": "A", "explanation": "The observed log block contains all required fields (revision, workload, environment, metric) matching the target exactly, and explicitly declares 'winner: A' within the same block.", "citations": [{"quote": "revision: r7", "supports": "target revision match"}, {"quote": "workload: six writers", "supports": "target workload match"}, {"quote": "environment: fixture-east", "supports": "target environment match"}, {"quote": "metric: restart correctness", "supports": "target metric match"}, {"quote": "winner: A", "supports": "explicit winner declaration in observed block"}], "next_check": "verify that the winner declaration is not overridden by subsequent lines outside the observed block"}, "error": null}], "outputs": {"checked_only": {"decision": {"sufficiency": "insufficient", "recommendation": "none", "reason_code": "no_applicable_observation", "basis_ids": [], "explanation": "No applicable check establishes a choice under this decision's requirements.", "limitation": "Synthetic scenario only; source authenticity is not verified. Target: revision=r7, workload=six writers, environment=fixture-east, metric=restart correctness", "next_check": "Re-extract winner from the original source and verify its exact span."}, "issues": [{"code": "unaccepted_candidate_winner", "next_check": "Re-extract winner from the original source and verify its exact span."}]}, "source_adapter": {"decision": {"sufficiency": "supported", "recommendation": "A", "reason_code": "applicable_observation", "basis_ids": ["S1"], "explanation": "Applicable fixture checks support A for the stated target.", "limitation": "Synthetic scenario only; source authenticity is not verified. Target: revision=r7, workload=six writers, environment=fixture-east, metric=restart correctness", "next_check": "Reproduce independently before applying this synthetic finding to a real system."}, "issues": []}}}
## C06
{"source": {"id": "S1", "kind": "artifact", "text": "[observed]\nrevision: r7\nworkload: six writers\nenvironment: fixture-east\nmetric: restart correctness\n[/observed]"}, "target": {"revision": "r7", "workload": "six writers", "environment": "fixture-east", "metric": "restart correctness"}, "proposal": {"revision": {"value": "r7", "quote": "revision: r7"}, "workload": {"value": "six writers", "quote": "workload: six writers"}, "environment": {"value": "fixture-east", "quote": "environment: fixture-east"}, "metric": {"value": "restart correctness", "quote": "metric: restart correctness"}, "winner": {"value": null, "quote": null}}, "expected": "none", "drafts": [{"repeat": 1, "answer": {"recommendation": "none", "explanation": "The source log contains all required fields (revision, workload, environment, metric) matching the target exactly, but does not specify a winner between options A and B.", "citations": [{"quote": "revision: r7", "supports": "target revision match"}, {"quote": "workload: six writers", "supports": "target workload match"}, {"quote": "environment: fixture-east", "supports": "target environment match"}, {"quote": "metric: restart correctness", "supports": "target metric match"}], "next_check": "Look for explicit winner declaration in extended source or metadata"}, "error": null}, {"repeat": 2, "answer": null, "error": "ValueError"}], "outputs": {"checked_only": {"decision": {"sufficiency": "insufficient", "recommendation": "none", "reason_code": "no_applicable_observation", "basis_ids": [], "explanation": "No applicable check establishes a choice under this decision's requirements.", "limitation": "Synthetic scenario only; source authenticity is not verified. Target: revision=r7, workload=six writers, environment=fixture-east, metric=restart correctness", "next_check": "Record winner in a new observed artifact; do not infer it."}, "issues": [{"code": "missing_winner", "next_check": "Record winner in a new observed artifact; do not infer it."}]}, "source_adapter": {"decision": {"sufficiency": "insufficient", "recommendation": "none", "reason_code": "no_applicable_observation", "basis_ids": [], "explanation": "No applicable check establishes a choice under this decision's requirements.", "limitation": "Synthetic scenario only; source authenticity is not verified. Target: revision=r7, workload=six writers, environment=fixture-east, metric=restart correctness", "next_check": "Record winner in a new observed artifact; do not infer it."}, "issues": [{"code": "missing_winner", "next_check": "Record winner in a new observed artifact; do not infer it."}]}}}
## C11
{"source": {"id": "S1", "kind": "artifact", "text": "[observed]\nrevision: r1\nrevision: r2\nworkload: eight writers\nenvironment: fixture-local\nmetric: reopen correctness\nwinner: B\n[/observed]"}, "target": {"revision": "r2", "workload": "eight writers", "environment": "fixture-local", "metric": "reopen correctness"}, "proposal": {"revision": {"value": "r2", "quote": "revision: r2"}, "workload": {"value": "eight writers", "quote": "workload: eight writers"}, "environment": {"value": "fixture-local", "quote": "environment: fixture-local"}, "metric": {"value": "reopen correctness", "quote": "metric: reopen correctness"}, "winner": {"value": "B", "quote": "winner: B"}}, "expected": "none", "drafts": [{"repeat": 1, "answer": {"recommendation": "B", "explanation": "All required fields match the target exactly: environment is 'fixture-local', metric is 'reopen correctness', workload is 'eight writers', and revision is 'r2'. The winner is explicitly declared as 'B' in the observed log.", "citations": [{"quote": "environment: fixture-local", "supports": "environment field matching target"}, {"quote": "metric: reopen correctness", "supports": "metric field matching target"}, {"quote": "workload: eight writers", "supports": "workload field matching target"}, {"quote": "revision: r2", "supports": "revision field matching target"}, {"quote": "winner: B", "supports": "winner declaration for recommendation"}], "next_check": "Verify that the artifact source kind is correctly identified as 'artifact' and that all observed values are within the log's evidence boundary"}, "error": null}, {"repeat": 2, "answer": {"recommendation": "B", "explanation": "All required fields match the target exactly: environment is 'fixture-local', metric is 'reopen correctness', workload is 'eight writers', and revision is 'r2'. The winner is explicitly declared as 'B' in the observed log.", "citations": [{"quote": "environment: fixture-local", "supports": "environment field matching target"}, {"quote": "metric: reopen correctness", "supports": "metric field matching target"}, {"quote": "workload: eight writers", "supports": "workload field matching target"}, {"quote": "revision: r2", "supports": "revision field matching target"}, {"quote": "winner: B", "supports": "winner declaration for recommendation"}], "next_check": "Verify that the artifact source kind is correctly identified as 'artifact' and that all observed values are within the log's evidence boundary"}, "error": null}], "outputs": {"checked_only": {"decision": {"sufficiency": "insufficient", "recommendation": "none", "reason_code": "no_applicable_observation", "basis_ids": ["S1"], "explanation": "No applicable check establishes a choice under this decision's requirements.", "limitation": "Synthetic scenario only; source authenticity is not verified. Target: revision=r2, workload=eight writers, environment=fixture-local, metric=reopen correctness", "next_check": "Resolve duplicate revision declarations with a new check."}, "issues": [{"code": "ambiguous_revision", "next_check": "Resolve duplicate revision declarations with a new check."}]}, "source_adapter": {"decision": {"sufficiency": "insufficient", "recommendation": "none", "reason_code": "no_applicable_observation", "basis_ids": ["S1"], "explanation": "No applicable check establishes a choice under this decision's requirements.", "limitation": "Synthetic scenario only; source authenticity is not verified. Target: revision=r2, workload=eight writers, environment=fixture-local, metric=reopen correctness", "next_check": "Resolve duplicate revision declarations with a new check."}, "issues": [{"code": "ambiguous_revision", "next_check": "Resolve duplicate revision declarations with a new check."}]}}}
## Adapter code (source verifiers exactgrammar summarizedabove)
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
