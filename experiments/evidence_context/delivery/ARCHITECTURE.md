# Production architecture decision: canonical evidence, explicit authority

Status: implementation in progress; not a release approval. The complete shipping
contract is [GOAL.md](GOAL.md). This document states the direction and why, while
STATUS.json records what has actually been proven.

## Storage choice

Keep sessions.db and its existing independent agent-session-tools package as the
canonical store. Add relational tables for provenance, source versions, explicit
project classification, assertions, citations, relationships, corrections, deletion
metadata and capture health. FTS and optional semantic indexes are replaceable
projections of permitted, current source records.

Why: the measured engine trial returned equivalent information across SQLite,
Ladybug and a mixed approach. Query-plan changes removed the demonstrated SQLite
bottleneck. Later failures came from missing source context and overinterpretation,
which a graph engine cannot repair. Typed relationship rows can support bounded
traversal in SQLite; a future engine decision needs a measured workload it cannot
serve adequately. A separate canonical evidence DB would complicate atomic source,
correction and deletion changes without a demonstrated benefit.

## Ownership and authority

The importer owns native event type, native locator, parser version, content binding,
call linkage and any genuinely captured invocation result. Configuration owns project
identity and work/personal/unclassified scope. Harness and hostname never classify
scope. The model proposes interpretations and relationship edges, retaining exact
source/version/quote offsets and its generator identity. It cannot submit trusted
capture fields or silently approve its own proposal.

A source fact and its proposed meaning remain separate. `process_exit` establishes
command lifecycle completion and records its exit code; it does not establish that
application behavior was validated. Generic native tool output is observed output,
with unknown execution state unless a structured native result establishes more.
Legacy prose remains reported or unknown according to what its importer can prove.

A decision consumes a scoped evidence bundle and a requested target/validation
contract. It reports useful context, conflicts, missing metadata and the evidence
needed next. Validation applicability is code checked. Any semantic review retains
reviewer identity and authority; an agent review is not transformed into human approval
or an observed event. No recency or vote-count rule establishes truth. Related older
reports remain useful as historical context, explicitly distinguished from current
validation.

## Canonical record boundaries

Source versions are immutable and content bound. A native source identity is distinct
from a version of its captured bytes/metadata. Assertions cite exact immutable versions
and offsets, so a correction cannot silently move a citation to different words.
A correction is a new record with explicit lineage, not a rewrite of old evidence.
Concurrent corrections remain inspectable rather than winning by arrival order.

Retrieval must explain lexical matches, explicit relationships, source provenance,
project/scope applicability and capture gaps. A bounded evidence bundle must retain
contrary evidence and expose truncation; a short answer is not proof of sufficiency.
Raw native text and model proposals remain untrusted prompt content.

Stage24 separates bounded discovery from response packing. It preserves the
strongest lexical source, then considers complete proposed contrary/correction
groups before filling with other matches. All group dependencies fit together or
the group is explicitly omitted. Exact endpoint/label duplicates are represented
once; producer count is not authority. This is inspection priority, not semantic
approval. The measured fixture trade-off was more
complete groups with fewer lexical matches, not verified answer-quality improvement.

Stage25 adds typed review targets and attributed source-bound assessment history,
reusing immutable observation storage and retirement machinery. Reviews cannot
upgrade native facts or claim human authority. Current disagreements remain
inspectable; one adapter cannot supersede another adapter's review, while clients
sharing an adapter label are not separate authenticated reviewers. Every source
underlying the target or review remains a scope/forgetting dependency. All review
dependencies travel together or coverage is explicitly incomplete.

An assessment describes the available support, dispute and proposed conflicts;
it retains semantic validation, reviewer independence and validation of change as
not established. The tiny frozen pilot accepted only one of three plain-JSON
batches; post-hoc wrapper removal exposed reasonable labels in all three, without
changing acceptance. This separates transport reliability from interpretation and
does not prove general semantic arbitration. Harder usefulness evaluation and the
full production lifecycle/integration remain required.

## Scope, forgetting and compatibility

All current registered reads, including legacy CLI/MCP, direct ID lookup, semantic
search, relationship expansion and explanations, must apply configured scope before
returning text. New protected tools alone would leave the old tools as bypasses.
Unclassified material is capturable for later explicit classification but is not
implicitly personal or work. This is a local application boundary, not protection
against the OS account directly reading SQLite or running an obsolete binary.

Each sync destination declares allowed scopes. Filtering occurs before a staging
bundle is written or transferred; destination filtering alone is insufficient.
Legacy global learning tables need explicit ownership or withholding. A peer without
the scoped/deletion protocol must be refused, with a useful upgrade diagnostic.
The old unscoped SQL transport cannot be the fallback for protected data.

Stage26 adds a memory-owned registry for study sessions, teach-back scores and
knowledge bridges. Exactly one native session, configured project or explicit
scope owns a record. Business writes, ownership and progress observations commit
together. Shared SQL predicates filter before bodies, aggregates and limits;
source/project owners follow current classification. Ownership remains distinct
from semantic authority. The registry preserves business IDs and centralizes the
contract, at the cost of a lookup and trigger-maintained business mappings rather
than ordinary foreign keys to all business tables. Per-table typed owner columns
remain a reasonable alternative, not yet comparatively benchmarked.

The real installed StudyLoop MCP journey passed eight checks. A 50,000-row
project-only fixture measured approximately 15 ms for a scoped count and 20 ms for
the latest twenty rows. This proves neither schema superiority nor general scale.
An installed schema35-to36 copy upgrade preserved all preexisting table rows.
Remaining learner state, combined-request policy races, full managed source cleanup,
scoped transfers and restore still require integration. This is a tested increment,
not completion of the work/personal or lifecycle requirements.

Stage27 extends this registry to notes, parked questions and practice attempts.
Typed study-parent links require both the primary owner and the study parent to
remain visible. Exact owner/parent identity controls pending-question deduplication;
permitted frequencies are aggregated at read time. Board names have explicit scope.
Application-only study placeholders can be owned before capture; native history is
never fabricated. Practice attempts and derived reported progress commit together,
retain application dependencies and follow project reclassification or deletion.
This does not validate mastery. Canonical migrations replace ad hoc notes/parking
schema repair; a failed migration stays a diagnosable error. The installed HTTP/MCP
lesson passes ten checks with the web extra. Mixed-dependency performance, remaining
learner files/tables and response-wide policy consistency remain open.

Durable content-free deletion metadata takes precedence over capture, corrections,
sync, FTS/vector rebuild and managed restore. Reimport of original archives must be
suppressed. Managed derived copies are purged. Original external transcripts and
unmanaged backups have a separate retention boundary, stated plainly. Managed restore
must merge active deletion metadata before restored content is served.

## Installation and StudyLoop integration

agent-session-tools remains the independently installable memory owner and imports
no StudyLoop runtime. It owns setup/doctor, skills and harness registration. StudyLoop
calls a versioned integration interface. Existing session-* entry points remain.
No new public SessionWeave repository is required to prove that separation.

Harness selection supports arrows, Space and Enter, plus noninteractive flags.
Cancellation writes nothing; updates preserve unrelated settings and are idempotent.
Installed files, active registration, recent capture success and repair gaps are
reported separately. A SKILL.md file on disk is not proof of a working hook.

## Migration and acceptance

The existing migration framework is forward-only and holds a write transaction over
pending schema changes. New schema must be additive, preserve legacy rows, fail
atomically and be retryable. Rollback acceptance uses a consistent backup/restore
rehearsal with current deletion metadata; do not invent a destructive down-migration.

Implementation order is source/provenance contracts, canonical storage and lifecycle,
legacy-path policy enforcement, native capture and scoped sync, then shared setup and
StudyLoop consumption. These components need production-path tests and installed-wheel
journeys. Synthetic adapter success, unit counts and council recommendations are
insufficient substitutes for the full requirement-by-requirement release audit.
