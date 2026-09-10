# learning-memory

The ADR-0011 PoC store: **capture is lossless and dumb; usefulness is derived at
capture time and bound to provenance the database itself can prove.**

Own SQLite file, stdlib only. The live `~/.config/studyloop/sessions.db` is never
opened by this package.

## What is in here

| Module | What it owns |
| --- | --- |
| `model.py` | `Session`, `Event`, `ParsedSession`, `SourceRef`, the `HarnessAdapter` protocol, and the event content hash |
| `schema.py` | the whole DDL, including the two triggers that make the invariants non-negotiable |
| `store.py` | `Store.connect` / `install` / `ingest` / `add_claim` / `visible_evidence` |

```python
from learning_memory import Event, ParsedSession, Session, Store

store = Store.connect("poc.db")          # foreign_keys=ON, WAL
store.install()

store.ingest(
    ParsedSession(
        session=Session(id="kiro-2026-09-10-1", harness="kiro", project="studyloop"),
        events=[Event(turn_id=0, seq=0, kind="user", text="why did the gate fail?")],
        native_source=raw_transcript_bytes,   # OBSERVED: we still hold the original
    )
)

claim = store.add_claim(
    "kiro-2026-09-10-1",
    "Finding",
    "Recall was the failing layer",
    "The keyword path scored 0.107 macro recall@5 on gold v2.",
    ("retrieval", "gold-v2"),
    0.9,
    "distiller/model-pass",
    citations=[{"evidence_id": ..., "quote": "0.107 macro recall@5"}],
)
```

## The four invariants (all property-tested)

1. **Re-import is a no-op.** Events are content-addressed over
   `(kind, actor, tool_name, text)` with `UNIQUE(session_id, content_hash)`, so
   running the export sweep twice — or twice over overlapping windows — adds no
   rows, and a message repeated inside one transcript collapses to one row.
   `IngestResult` reports what was skipped.
2. **No session row without at least one evidence row.** `OBSERVED` needs the
   harness's native bytes; `REPORTED` (the archive path, where the original has
   been rotated away) synthesises evidence from the prose already held, labelled
   `origin='archive'`. If neither exists the whole transaction rolls back, so a
   refused ingest leaves nothing behind.
3. **A claim cannot exist with a citation that does not bind.** `add_claim`
   resolves each quote to **code-point** offsets with `str.find`, refusing quotes
   that are missing, empty, or ambiguous (more than one occurrence, so the offsets
   would be a guess) — and then `claim_citation_bound_proof` re-proves it in SQL:
   `substr(evidence.body, start+1, end-start) = quote`. Byte or UTF-16 offset
   arithmetic desynchronises on any astral character and is refused. Claim plus
   citations are one transaction: a good citation never survives a bad sibling.
4. **Claims never change.** `claims_immutable` aborts every `UPDATE`. A correction
   is a new claim whose `supersedes` names the old one. Claim ids are content
   addresses, so a re-run cannot fork the same assertion.

Plus: **`prose_fts` indexes prose only.** It is an FTS5 external-content index over
`events` whose only writers are triggers gated on `kind IN ('user',
'assistant_prose')`, so tool output is stored but never searchable. The tokenizer is
a constructor parameter (`porter unicode61` default, `unicode61` the alternative)
because ADR-0011 leaves that choice to measurement; a store records which one built
it and refuses to be reopened under the other.

## Running the gates

From this directory:

```bash
uv sync
uv run --group dev pytest -q
uv run ruff check
uv run ruff format --check
uv run --group dev pyright src
```

## Not implemented here (deliberately)

The derivation pass — exchanges, concept tags, recurrence, review items — has its
tables and constraints in `schema.py` but no writer yet: ADR-0011 puts it in the
export sweep, which is a later stage. Same for the adapters: `HarnessAdapter` is
the contract they will satisfy, and the shared base owning dedupe, evidence and
lineage is `Store.ingest`.
