"""Run a synthetic retrieval demonstration into a new, disposable directory."""

import argparse
from pathlib import Path

from .store import EvidenceRecord, EvidenceStore, Relationship, canonical_json


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="New output directory")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    store = EvidenceStore.create(args.output / "evidence.db")
    when = "2026-01-01T12:00:00+00:00"
    try:
        first = store.add_evidence(
            EvidenceRecord(
                message_id="demo-1",
                session_id="demo-session-1",
                harness="codex",
                project="demo",
                scope="personal",
                content="The release candidate is ready. The SQLite repair passed.",
                timestamp=when,
                available_at=when,
                source_locator="synthetic:demo-1",
            )
        )
        second = store.add_evidence(
            EvidenceRecord(
                message_id="demo-2",
                session_id="demo-session-2",
                harness="grok",
                project="demo",
                scope="personal",
                content="Graph validation still reports stale derived records.",
                timestamp=when,
                available_at=when,
                source_locator="synthetic:demo-2",
            )
        )
        store.add_relationship(
            Relationship(
                source_id=first,
                target_id=second,
                kind="contradicts",
                supporting_citations=(store.cite(first), store.cite(second)),
                asserted_at=when,
                available_at=when,
                origin="asserted",
                review_state="reviewed",
                reviewer="synthetic-fixture",
                extractor_version="synthetic-v1",
            )
        )
        output = {
            "purpose": "Synthetic behavior demonstration; not answer-quality evidence",
            "semantic_retrieval": "not_run",
            "arms": {},
        }
        for name, links in (("keyword", False), ("relationships", True)):
            pack = store.retrieve(
                "release candidate",
                project="demo",
                scope="personal",
                as_of=when,
                max_bytes=8000,
                neighbor_turns=0,
                use_relationships=links,
            )
            (args.output / f"{name}.json").write_text(pack.to_json() + "\n")
            output["arms"][name] = {
                "evidence": len(pack.evidence),
                "relationships": len(pack.relationships),
                "bytes": pack.byte_size,
                "status": pack.status,
            }
        rendered = canonical_json(output)
        (args.output / "summary.json").write_text(rendered + "\n")
        print(rendered)
    finally:
        store.close()


if __name__ == "__main__":
    main()
