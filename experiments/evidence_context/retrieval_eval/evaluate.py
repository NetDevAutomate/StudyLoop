"""Frozen-input comparison using the stage-1 retriever and exact evidence spans."""

from __future__ import annotations

import hashlib
import random
import time
from pathlib import Path
from typing import Any

from ..store import (
    Citation,
    EvidencePack,
    EvidenceRecord,
    EvidenceStore,
    Relationship,
    _time,
    canonical_json,
)


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def known_time(value: str) -> str:
    result = _time(value)
    if result is None:
        raise ValueError("Explicit timestamp required")
    return result


def validate(data: dict) -> None:
    if data["kind"] not in {"synthetic", "development", "holdout_candidate"}:
        raise ValueError("Unknown dataset kind")
    if not data["records"] or not data["cases"]:
        raise ValueError("Records and cases required")
    records = {r["key"]: r for r in data["records"]}
    if len(records) != len(data["records"]):
        raise ValueError("Duplicate record key")
    if len({c["id"] for c in data["cases"]}) != len(data["cases"]):
        raise ValueError("Duplicate case ID")
    if data["kind"] == "holdout_candidate":
        if not data.get("label_reviewer") or not data.get("split_note"):
            raise ValueError("Holdout candidates require reviewer and split note")
        if {c["lineage"] for c in data["cases"]} & set(data.get("development_lineages", [])):
            raise ValueError("Development lineage overlaps candidate holdout")
    if len({digest(r["record"]) for r in data["records"]}) != len(records):
        raise ValueError("Duplicate source record under different keys")
    for case in data["cases"]:
        known_time(case["as_of"])
        if not isinstance(case["answerable"], bool) or not isinstance(
            case["labels_complete"], bool
        ):
            raise ValueError("Boolean case labels required")
        if len({(r["key"], r["text"]) for r in case["required"]}) != len(case["required"]):
            raise ValueError("Duplicate required span")
        relevant = case["relevant"]
        if len(relevant) != len(set(relevant)):
            raise ValueError("Duplicate relevance label")
        for key in relevant:
            record = records[key]["record"]
            if (record["project"], record["scope"]) != (case["project"], case["scope"]):
                raise ValueError("Relevant label outside scope")
            for field in ("timestamp", "available_at"):
                if not record[field] or known_time(record[field]) > known_time(case["as_of"]):
                    raise ValueError("Relevant label outside historical cutoff")
        if case["answerable"] != bool(case["required"]):
            raise ValueError("Answerable cases require evidence spans")
        for span in case["required"]:
            if span["key"] not in relevant:
                raise ValueError("Required source must be labelled relevant")
            text = records[span["key"]]["record"]["content"]
            if not span["text"] or text.count(span["text"]) != 1:
                raise ValueError("Required span must occur exactly once")
    for edge in data["edges"]:
        left, right = (records[edge[k]]["record"] for k in ("source", "target"))
        if (left["project"], left["scope"]) != (right["project"], right["scope"]):
            raise ValueError("Labelled edge crosses scope")


def score(
    store: EvidenceStore,
    pack: EvidencePack,
    case: dict,
    versions: dict[str, str],
    texts: dict[str, str],
) -> dict:
    returned = {item.version_id for item in pack.evidence}
    relevant = {versions[key] for key in case["relevant"]}
    valid = 0
    invalid = 0
    forbidden = 0
    coverage = 0
    grounded = []
    for item in pack.evidence:
        citation_valid = False
        try:
            if (
                item.version_id == item.citation.version_id
                and store.resolve_citation(item.citation) == item.citation.text
            ):
                valid += 1
                citation_valid = True
            else:
                invalid += 1
        except (ValueError, KeyError):
            invalid += 1
        if (item.project, item.scope) != (case["project"], case["scope"]) or any(
            value is None or known_time(value) > known_time(case["as_of"])
            for value in (item.timestamp, item.available_at)
        ):
            forbidden += 1
        elif citation_valid:
            grounded.append(item)
    for required in case["required"]:
        start = texts[required["key"]].index(required["text"])
        end = start + len(required["text"])
        if any(
            item.version_id == versions[required["key"]]
            and item.citation.start <= start
            and item.citation.end >= end
            and item.citation.text[start - item.citation.start : end - item.citation.start]
            == required["text"]
            for item in grounded
        ):
            coverage += 1
    edge_violations = 0
    edge_citation_errors = 0
    for edge in pack.relationships:
        if any(
            edge.get(field) is None or known_time(edge[field]) > known_time(case["as_of"])
            for field in ("asserted_at", "available_at")
        ):
            edge_violations += 1
        if not {edge["source_id"], edge["target_id"]} <= returned:
            edge_violations += 1
        for reference in edge["supporting_citations"]:
            try:
                store.resolve_citation(Citation(**reference))
            except (ValueError, KeyError, TypeError):
                edge_citation_errors += 1
    count = len(case["required"])
    labelled = case["labels_complete"]
    return {
        "returned_passages": len(returned),
        "relevant_returned": len(returned & relevant),
        "passage_precision": len(returned & relevant) / len(returned)
        if returned and labelled
        else None,
        "passage_recall": len(returned & relevant) / len(relevant) if relevant else None,
        "required_spans_found": coverage,
        "required_spans_total": count,
        "required_span_recall": coverage / count if count else None,
        "all_required_evidence_present": coverage == count if count else None,
        "valid_citations": valid,
        "invalid_citations": invalid,
        "scope_or_time_violations": forbidden,
        "edge_violations": edge_violations,
        "edge_citation_errors": edge_citation_errors,
        "integrity_pass": invalid == 0
        and forbidden == 0
        and edge_violations == 0
        and edge_citation_errors == 0,
        "unanswerable_retrieval_outcome": (
            None
            if case["answerable"]
            else "empty_context"
            if not returned
            else "unjudged_context"
            if not labelled
            else "contains_labelled_irrelevant_evidence"
            if returned - relevant
            else "related_but_insufficient_context"
        ),
        "empty_result": not returned,
        "retriever_status": pack.status,
        "bytes": pack.byte_size,
        "warnings": list(pack.warnings),
        "answer_quality": "not_measured",
        "explanation_quality": "not_measured",
        "validation_claim_accuracy": "not_measured",
        "abstention_quality": "not_measured",
    }


def build(path: Path, data: dict, shuffled: bool, seed: int):
    store = EvidenceStore.create(path)
    versions = {
        r["key"]: store.add_evidence(EvidenceRecord(**r["record"])) for r in data["records"]
    }
    records = {r["key"]: r["record"] for r in data["records"]}
    rng = random.Random(seed)  # nosec B311 - reproducible sampling, not security.
    remapped = []
    for edge in data["edges"]:
        source, target = edge["source"], edge["target"]
        if shuffled:
            candidates = sorted(
                k
                for k, r in records.items()
                if k not in {source, target}
                and (r["project"], r["scope"])
                == (records[source]["project"], records[source]["scope"])
                and r["timestamp"]
                and r["available_at"]
                and known_time(r["timestamp"]) <= known_time(edge["at"])
                and known_time(r["available_at"]) <= known_time(edge["at"])
            )
            if not candidates:
                store.close()
                raise ValueError("No eligible alternative for shuffled-edge control")
            target = rng.choice(candidates)
        store.add_relationship(
            Relationship(
                source_id=versions[source],
                target_id=versions[target],
                kind=edge["kind"],
                supporting_citations=(store.cite(versions[source]), store.cite(versions[target])),
                asserted_at=edge["at"],
                available_at=edge["at"],
                origin="asserted",
                review_state="reviewed",
                reviewer="synthetic-negative-control" if shuffled else "dataset-curator",
                extractor_version="evaluation-fixture-v1",
            )
        )
        remapped.append({"source": source, "target": target, "kind": edge["kind"]})
    return store, versions, remapped


def run(data: dict, output: Path, budget: int = 8000, seed: int = 42) -> dict:
    validate(data)
    if budget < 1000:
        raise ValueError("Evaluation byte budget too small")
    output.mkdir(parents=True, exist_ok=False, mode=0o700)
    # Freeze inputs and settings before any query, not after observing results.
    manifest = {
        "dataset_sha256": digest(data),
        "kind": data["kind"],
        "budget": budget,
        "budget_unit": "utf8_bytes",
        "seed": seed,
        "records": len(data["records"]),
        "cases": len(data["cases"]),
        "evaluator_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "retriever_sha256": hashlib.sha256(
            Path(__file__).parents[1].joinpath("store.py").read_bytes()
        ).hexdigest(),
        "retrieval_settings": {
            "limit": 8,
            "max_hops": 1,
            "neighbor_turns": 0,
            "excerpt_chars": 1200,
        },
        "holdout_independence": "not_verified_by_tool",
        "semantic": "not_run",
    }
    (output / "frozen-input.json").write_text(canonical_json(data) + "\n", encoding="utf-8")
    (output / "manifest.json").write_text(canonical_json(manifest) + "\n", encoding="utf-8")
    rows = []
    stores = []
    try:
        controls = {}
        for name, shuffled in (("keyword", False), ("relationships", False), ("shuffled", True)):
            store, versions, mapping = build(output / f"{name}.db", data, shuffled, seed)
            stores.append((name, store, versions))
            controls[name] = mapping
        texts = {r["key"]: r["record"]["content"] for r in data["records"]}
        order = random.Random(seed)  # nosec B311 - reproducible arm order, not security.
        for case in data["cases"]:
            arms = list(stores)
            order.shuffle(arms)
            for name, store, versions in arms:
                started = time.perf_counter()
                pack = store.retrieve(
                    case["query"],
                    project=case["project"],
                    scope=case["scope"],
                    as_of=case["as_of"],
                    max_bytes=budget,
                    neighbor_turns=0,
                    limit=8,
                    max_hops=1,
                    excerpt_chars=1200,
                    use_relationships=name != "keyword",
                )
                elapsed = (time.perf_counter() - started) * 1000
                result = score(store, pack, case, versions, texts)
                result.update(
                    case_id=case["id"], arm=name, elapsed_ms=elapsed, answerable=case["answerable"]
                )
                if pack.byte_size > budget:
                    raise AssertionError("Context budget violated")
                rows.append(result)
        pairs = []
        for case in data["cases"]:
            values = {r["arm"]: r for r in rows if r["case_id"] == case["id"]}
            a, c = values["keyword"], values["relationships"]
            control = values["shuffled"]
            pairs.append(
                {
                    "case_id": case["id"],
                    "span_recall_delta": c["required_span_recall"] - a["required_span_recall"]
                    if case["required"]
                    else None,
                    "byte_delta": c["bytes"] - a["bytes"],
                    "shuffled_vs_keyword_span_recall_delta": control["required_span_recall"]
                    - a["required_span_recall"]
                    if case["required"]
                    else None,
                    "relationships_vs_shuffled_span_recall_delta": c["required_span_recall"]
                    - control["required_span_recall"]
                    if case["required"]
                    else None,
                    "shuffled_vs_keyword_byte_delta": control["bytes"] - a["bytes"],
                }
            )
        report = {
            "manifest": manifest,
            "results": rows,
            "paired_differences": pairs,
            "control_edges": controls["shuffled"],
            "conclusion": "Scoring demonstration only"
            if data["kind"] == "synthetic"
            else "Requires independent label and split review",
            "limits": [
                "No answer generation",
                "Single timing observation per case/arm",
                "One rewired control seed; not degree-preserving",
                "No statistical efficacy claim",
            ],
        }
        (output / "report.json").write_text(canonical_json(report) + "\n", encoding="utf-8")
        lines = [
            "# Retrieval evaluation",
            "",
            report["conclusion"],
            "",
            "This run does not measure answer quality, validated explanations or learning value.",
            "",
            "| Case | Arm | Passage precision | Required-span recall | Bytes | Retrieval ms |",
            "|---|---|---:|---:|---:|---:|",
        ]
        for row in sorted(rows, key=lambda r: (r["case_id"], r["arm"])):
            precision = (
                "N/A" if row["passage_precision"] is None else f"{row['passage_precision']:.2f}"
            )
            recall = (
                "N/A"
                if row["required_span_recall"] is None
                else f"{row['required_span_recall']:.2f}"
            )
            label = str(row["case_id"]).replace("|", "/").replace("\n", " ")
            lines.append(
                f"| {label} | {row['arm']} | {precision} | {recall} | "
                f"{row['bytes']} | {row['elapsed_ms']:.3f} |"
            )
        lines.extend(
            [
                "",
                "Timing is one local observation per arm/case, not a performance ranking.",
                "See report.json for integrity counts, warnings and control edges.",
            ]
        )
        (output / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
        return report
    finally:
        for _, store, _ in stores:
            store.close()
