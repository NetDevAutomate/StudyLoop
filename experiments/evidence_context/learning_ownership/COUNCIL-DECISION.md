# Stage26 council arbitration

Decision: keep the ownership registry for this three-table increment, preserve the
measured and installed evidence, and continue the full production goal. This is
not release approval or proof that a registry outperforms ownership columns.

Both rounds used the same neutral brief for three independent provider buckets:
Meta (`llama4-maverick`), Qwen (`qwen3-coder`) and Mistral (`mistral-large-3`). All
three returned valid council responses in each round. Gateway preflight was healthy.
Only code, synthetic fixtures and aggregate measurements were sent. The result
brief included the implementation, actual tests, upgrade/benchmark observations
and known remaining scope. The final small MCP status refinement and two targeted
regressions followed the brief; no repeat council call was made to seek approval.

`comparison.md`, `comparison.json` and the dissenting raw responses were read in
both rounds. Comparisons group model wording, not independent proof. Private
artifacts are under `studyloop-private/reviews/2026-09-06-stage26-learning-ownership/`.

## Design alternatives

| Advice | Decision and evidence |
|---|---|
| Meta: simplify scope configuration and use a common SQL predicate | Use the common predicate, which is implemented in `records.visible_sql`. Retain explicit configuration: the user requires work/personal boundaries independent of harness/machine and forbids guessing legacy ownership. A predicate needs an authoritative owner to filter on. |
| Qwen: accept the increment conditionally, prove deletion and atomicity | Accepted. Three-table tests cover ownership deletion in both directions, native reclassification, logical tombstone purge, invalid source rollback, policy-change rollback and failed progress rollback. The full replica lifecycle is still open. |
| Mistral: put `owner_type`/`owner_id` on each table instead | Reasonable alternative, not established as superior. It removes a registry lookup but duplicates ownership structure and loses typed owner foreign keys unless expanded to constrained typed columns. The registry preserves business IDs and centralizes the memory-owned boundary. A comparative benchmark has not been run. |
| Mistral: local SQLite row IDs are sufficient for sync identity | Rejected. Separate machines can allocate the same local integer. A stable cross-replica identity and validated import mapping remain required; the registry UUID alone does not implement sync. |
| Mistral: direct columns improve the 90% of reads already filtering scope | The 90% figure was supplied by the model, not measured. No performance conclusion uses it. The actual 50,000-row measurements establish only this implementation's local workload behaviour. |

## Result review

Meta proposed release approval with conditions; Qwen rejected the increment because
of whole-product gaps; Mistral correctly refused release approval. The coordinator
decision is neither a vote nor an average: the increment has useful evidence, and
the whole product remains incomplete under P01–P15.

Accepted concerns:

- Remaining learner tables and their readers/writers are required work. Temporary
  classified bridge/dependency conversion refusal is not the final product design.
- The project-only benchmark does not cover mixed native/project owners,
  concurrent writers, million-row data or a competing schema.
- Logical tombstone cleanup of these three tables does not prove all foreign-key
  cleanup, scoped transfer, stale replay, exporter suppression or managed restore.
- A source-linked assessment before capture needs explicit integration behaviour.
  The added test proves current refusal is an exception with atomic rollback,
  rather than a silently successful partial write. Installed startup still needs
  to coordinate source availability.
- File-policy reload is not a database transaction over the external file. Applied
  policy writes serialize via SQLite; the before-commit recheck detects the tested
  change during a write. Full concurrent consumer/transfer scenarios remain needed.

Findings checked against code and not accepted as demonstrated defects:

- Mistral said a native-linked row copies the active scope permanently. `bind`
  sets `project_id` and `scope` to null when `session_id` is supplied. `visible_sql`
  follows current session visibility. The three native-assignment tests and the
  actual running MCP reclassification journey contradict that claim.
- Mistral said exactly one owner conflicts with explicit-scope ownership. The
  CHECK constraint includes scope as the third mutually exclusive owner choice.
- Qwen said the implementation assumes registry performance superiority. The
  review brief explicitly said no comparison had been made; no such superiority
  claim is used in the decision.
- Qwen alleged a race between the initial policy check and writes. The initial
  check alone would be insufficient, but `policy_guard` checks again after the
  write and before commit. The injected-change test exercises rollback. This does
  not dismiss the broader concurrent policy-file lifecycle limitation above.
- Mistral inferred orphaned rows when another foreign key blocks raw parent
  deletion. With foreign keys enabled, that delete fails rather than committing
  an orphan. Logical tombstones intentionally persist while these dependent
  bodies are purged. Full managed parent cleanup remains required.

## Next discriminating work

Complete the learner-state ownership inventory and integration, including derived
paths; then exercise actual scoped transfers and forgetting in both replica orders,
with reimport and restore. Test the installed StudyLoop startup path with capture
not yet available. These tasks address known missing behaviour before additional
prompt optimisation or database-engine experiments. Harder interpretation/usefulness
evaluation remains separate from a record being permitted and attributable.
