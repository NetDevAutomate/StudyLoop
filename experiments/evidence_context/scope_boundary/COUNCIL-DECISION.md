# Stage19 council arbitration

The same contract and `visibility_sql` implementation were sent through the local
gateway to Fable, Grok, Qwen and Mistral. Fable, Qwen and Mistral returned usable
structured reviews; Grok returned no text. This is three-provider coverage of a
focused predicate review, not full implementation or production approval.

Original requests and replies remain in the ignored local archive:
`.private/stage-19/scope-brief.md` and `.private/stage-19/scope-council/`.
No transcript bodies were needed in this review.

| Review point | Decision and evidence |
|---|---|
| Fable: legacy unclassified inspection contract disagrees with code when projects are configured | Accepted. Kept the stricter code and documented apply-first in that case. Added a legacy-database regression. |
| Fable: classified request on old DB silently returns no rows | Accepted. It now raises an actionable migration/classification error. |
| Fable: root matching, prefix ordering and transactions cannot be verified from the shown predicate | Accepted limitation. Separate implementation tests cover component-based roots, prefix resolution, actual CLI calls and MCP stdio. This review alone did not prove them. |
| Fable: explicitly configured unclassified default conflicts with wording | Clarified. Production default is null; an owner can explicitly choose unclassified. No automatic inference is permitted. |
| Qwen: clarify tombstone scope and assignment conflicts | Global tombstones suppress a session in every scope. Explicit session assignments outrank root defaults. Policy digest attests project definitions, not all session assignments. Tests cover these rules. Sync conflict handling remains unfinished. |
| Mistral: a supplied `scope` argument could override policy | Relevant boundary check. The helper is internal; current MCP arguments do not expose it. Owner process environment is explicitly trusted. This is not multi-user authorization. |
| Mistral: atomic audit/application is not shown | Added a forced audit failure test proving rollback of project assignments and policy head. The concern was not proof that a race already existed. |

Review assumptions about the fingerprint covering every session assignment were
incorrect. The implementation intentionally fingerprints local project definitions
only; per-session provenance remains separate. Removed explicit/synced project
assignments are retained but withheld until that stable project ID is explicitly
configured again. This behavior is now documented and tested.

The final decision is to retain this bounded increment and continue the production
audit. No council wording overrides failed tests, grants release approval, or proves
that unreviewed StudyLoop and sync paths are safe.
