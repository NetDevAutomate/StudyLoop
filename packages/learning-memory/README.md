# learning-memory

The ADR-0011 **v1.1** PoC store: **capture is lossless and dumb; usefulness is
derived at capture time and bound to provenance the database itself can prove.**

Own SQLite file, stdlib only. The live `~/.config/studyloop/sessions.db` is never
opened by this package.

Schema **v2** (Stage B.1, after the two-family council review). There is no
migration from v1: `install()` refuses an older file by version, because nothing
real has been ingested and a rebuild from the adapters is honest where an untested
upgrade path is not.

## What is in here

| Module | What it owns |
| --- | --- |
| `model.py` | `Session`, `Event`, `ParsedSession`, `SourceRef`, the `HarnessAdapter` protocol, the position-bearing event hash, and `collapse_adjacent_duplicates` |
| `schema.py` | the whole DDL, including the six triggers that make the invariants non-negotiable |
| `store.py` | `Store.connect` / `install` / `ingest` / `add_claim` / `visible_evidence` / `search_prose` |

```python
from learning_memory import Event, ParsedSession, Session, Store, collapse_adjacent_duplicates

store = Store.connect("poc.db")          # foreign_keys=ON, WAL
store.install()

events, folded = collapse_adjacent_duplicates(parsed_events)   # adapter's job
store.ingest(
    ParsedSession(
        session=Session(id="kiro-2026-09-10-1", harness="kiro", project="studyloop"),
        events=events,
        native_source=raw_transcript_bytes,    # retained as an OBSERVED capture row
        adapter_version="kiro@1",
        exporter_dupes_collapsed=folded,
    )
)

# One citable row per prose event, in reading order.
fragment = store.visible_evidence("kiro-2026-09-10-1")[0]

claim = store.add_claim(
    "kiro-2026-09-10-1",
    "Finding",
    "Recall was the failing layer",
    "The keyword path scored 0.107 macro recall@5 on gold v2.",
    ("retrieval", "gold-v2"),
    0.9,
    "distiller/model-pass",
    citations=[{"evidence_id": fragment["id"], "quote": "0.107 macro recall@5"}],
)

store.search_prose("Which ADR path did the DoD and WP-9 require?")   # planned, never raises
store.search_prose_raw('"gold" AND "v2"')                            # explicit FTS5
```

## The invariants (all property-tested)

1. **Re-parse of the same source is a no-op.** Events are content-addressed over
   `(turn_id, seq, kind, actor, tool_name, text)` with
   `UNIQUE(session_id, content_hash)`, so running the export sweep twice — or twice
   over overlapping windows — adds no rows. `IngestResult` reports what was skipped.
2. **Every observed event occurrence is a row.** The hash is position-bearing: two
   identical messages in different turns are two rows. A position-free hash folded
   54.7 % of the archive's user/assistant rows, including every repeated tool call
   in a session, which made `retried = same tool call twice` underivable. Adjacent
   *exporter* duplicates are the adapter's to fold with
   `collapse_adjacent_duplicates`, and the count is stored on `sessions`.
3. **No session row without at least one *citable* evidence row.** The citation
   surface is one `REPORTED` row per non-empty prose event. Native bytes are
   retained as a separate `OBSERVED` capture row (`raw` BLOB), which is retention,
   not a citation target — so a prose-less session is still refused even when its
   transcript is held in full. Refusal rolls the whole transaction back.
4. **Evidence never changes.** `BEFORE UPDATE` and `BEFORE DELETE` both abort,
   unconditionally, cited or not. A re-capture is a new row with a new id. Evidence
   ids are content-addressed and position-free, so re-derivation, reclassification
   and reordering cannot strand a citation.
5. **A claim cannot exist without a binding citation.** `add_claim` refuses an empty
   citation set; independently, `claim_citations.claim_id` is `DEFERRABLE INITIALLY
   DEFERRED`, the store writes citations **first**, and `claims_need_citation`
   (AFTER INSERT on `claims`) aborts a citation-less claim however it was written.
   An orphan citation whose claim never arrives is refused at COMMIT.
6. **A citation's quote is the text at the offsets it names.**
   `claim_citation_bound_proof` re-proves it in SQL —
   `substr(evidence.body, start+1, end-start) = quote` — on INSERT and on UPDATE.
   Offsets are **code points**; byte or UTF-16 arithmetic desynchronises on any
   astral character and is refused. Quotes that are missing, empty, or ambiguous
   *within that one message* are refused before the write.
7. **Claims never change.** `claims_immutable` aborts every `UPDATE`. A correction is
   a new claim whose `supersedes` names the old one.
8. **An FTS rebuild indexes no tool text.** `prose_fts` is external-content over the
   `prose_events` VIEW, so `'rebuild'` and `'integrity-check'` obey the prose filter
   too, not just the triggers that feed the index.
9. **A child ingested before its parent acquires its edge when the parent lands.**
   The edge is parked in `lineage_pending` in the child's transaction and reconciled
   in the parent's; `IngestResult.lineage_deferred` reports what is still waiting.
   Circular pairs resolve because each side reconciles the other on arrival.
   `lineage` is authoritative for edges; `sessions.parent_id` is a convenience
   column filled only when the parent was already present.

Plus: **natural language never reaches FTS5 as syntax.** `search_prose` routes input
through `plan_prose_query`, which phrase-quotes every token (doubling embedded `"`,
stripping control characters and lone surrogates that would truncate FTS5's parse)
and OR-joins them, so `AND`, `NOT`, `(`, `*` and bare numbers are words. Deliberate
FTS5 syntax goes through `search_prose_raw`, which is allowed to raise. The tokenizer
is a constructor parameter (`porter unicode61` default, `unicode61` the alternative)
because ADR-0011 leaves that choice to measurement; a store records which one built
it and refuses to be reopened under the other.

## Running the gates

From this directory:

```bash
uv run --group dev pytest -q
uv run ruff check
uv run ruff format --check
uv run --group dev pyright
```

Do **not** run `uv sync` in this directory — it narrows the shared worktree
environment to this package. From the worktree root: `uv sync --all-packages --group dev`.

## Not implemented here (deliberately)

The derivation pass — exchanges, concept tags, concept occurrences, review items —
has its tables, versions and constraints in `schema.py` but no writer yet: ADR-0011
puts it in the export sweep under a `derivation_version` (Stage D), with a
hand-labelled cross-harness fixture set. Same for the adapters: `HarnessAdapter` is
the contract they will satisfy (Stage C), and the shared base owning dedupe,
evidence and lineage is `Store.ingest`. `claim_id` widens to cover the citation-set
fingerprint and `supersedes` in Stage E, when claims are first written by a model.
