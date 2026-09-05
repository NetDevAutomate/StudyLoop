# Production delivery goal

User objective: continue until a production-ready design and implementation can ship
as part of StudyLoop, preserving independently runnable stages and the educational
reasoning repository. The user is sleeping; continue authorized work without routine
confirmation. This file records the complete objective, not a smaller substitute.

The earlier experiment-only scope ceiling applied to those frozen stages. The new
explicit production request authorizes implementation and integration, while preserving
those checkpoints. It does not require publishing a new SessionWeave repository, deploying
the website, changing the owner's live scope settings, or releasing a package prematurely.

## Shipping contract

| ID | Required outcome | Completion evidence |
|---|---|---|
| P01 | Existing sessions.db remains canonical; additive, transactional, recoverable migrations preserve existing conversations and StudyLoop state. | Old-schema upgrade, interrupted migration/retry, FK/FTS integrity, installed-wheel upgrade tests on disposable copies. |
| P02 | Capture records preserve source identity, native role/type, content binding and source location. Native tool results are not inferred from quoted prose. Legacy evidence remains explicitly unverified. | Native-format parser tests and read-only real-source validation for Codex, Claude Code, Kiro, Grok; capability-specific desktop evidence. |
| P03 | Code owns origin, scope and captured invocation metadata. Models cannot overwrite those fields. Narrative interpretation remains distinct from observed facts. | Stage17 old-draft replay plus fresh adversarial cases, production boundary tests, code review. |
| P04 | Rich context spans configured projects/machines/harnesses with exact citations, retrieval explanations, temporal/revision applicability and explicit uncertainty. | Installed CLI and MCP retrieve scoped cross-harness fixture histories with valid source/version/offsets, bounded output and explain-why details; private real-data evaluation. |
| P05 | Conflicting advice, corrections and contrary evidence are surfaced. A decision states what its evidence supports, what conflicts and what validation is missing. No recency/popularity-only truth rule. | Decision/relationship tests covering changed requirements, contradictory reports, failed checks, unknown metadata and concurrent corrections; decision walkthrough. |
| P06 | Work/personal/unclassified scope is explicitly configured, independent of harness or hostname. Entire outputs and retrieval paths filter before model exposure. | CLI/MCP/direct lookup/search/semantic/relationship/explanation negative tests; config validation and reclassification tests. |
| P07 | Each sync destination has explicit allowed scopes. No excluded body or derived payload enters staged transfer or destination. | Production transport/bundle tests, mismatched/legacy peer refusal, two-replica transfers and negative payload inspection. |
| P08 | Correction retains history and supporting sources; forgetting purges managed content/derivations and cannot resurrect via exporter, sync, as-of lookup, rebuild or restore. | Real production storage/sync/export tests in both orders, stale replay, concurrent correction, crash/retry, derived-index and backup-restore tests. |
| P09 | Capture health distinguishes installation, registration, attempt/success, lag, parse errors, unknown and repair gaps, and accompanies context results. | Persistent import telemetry, doctor tests, broken/empty/native sources, repaired capture and user-visible diagnostics. |
| P10 | Independently installable memory component owns schema, capture/hooks, sync and CLI/MCP; imports no StudyLoop runtime. Existing session-* commands remain entry points. | Wheel-only standalone install, module dependency check, versioned contract tests. |
| P11 | StudyLoop delegates setup/doctor to that owner. Harness selection uses arrows/Space/Enter plus noninteractive flags; cancellation writes nothing and repeats preserve unrelated config. | Real temporary-home installer interaction, none/one/multiple/cancel/idempotence/upgrade/uninstall tests and one full synthetic native capture journey. |
| P12 | SKILL.md teaches source use, scope, conflicts, correction/forgetting, attribution and limits; selected harnesses get compatible registrations. | Installed artifact inspection plus invoked CLI/MCP evidence, not skill presence alone. |
| P13 | StudyLoop agent/session startup can request grounded historical context with clear ownership and configuration. | Installed StudyLoop end-to-end session integration using real package paths and isolated harness process; relevant UI/CLI acceptance. |
| P14 | Prior experimental stages remain runnable; each implementation stage explains why, alternatives, measurements and remaining limits. | Git checkpoints, runnable demos, stage index and decision guides. Saved exercises unchanged. |
| P15 | Release-ready implementation is packaged, documented and independently reviewed with risks resolved and reproducible validation. | Full relevant unit/type/lint/security/build/installed smoke/functional acceptance, council arbitration, reviewable commits and requirement-by-requirement completion audit. |

## Boundaries of claims

This is local shared memory, not multi-user authorization or universal semantic truth.
Observed command completion is not successful task validation. Native archive provenance
is trusted only within the local importer threat model. Human/agent interpretations and
review decisions retain their authority and source lineage; they do not become captured
facts. Independent human usefulness grading is not available overnight and cannot be
fabricated. No general retrieval superiority or semantic-certification claim may depend
on model-only fixture labels. Production usefulness must be exercised on actual interfaces
and real-source samples, not only toy adapters.

Backups/original external transcripts are not claimed erased by DB forgetting. Managed
restore must reapply deletion metadata before serving restored content; documented external
retention boundaries must be precise. Optional vector indexes must honor the same policy
or be excluded from the protected retrieval path until they do.

## Work sequence and evidence

1. Stage17: code-owned provenance replay, fresh cases and a production trust-boundary design.
2. Production core: typed evidence contracts, additive schema, scope policy, provenance,
   retrieval/decision explanations, correction/forgetting and capture health.
3. Native capture and scoped sync: integrate real exporter/transport paths, compatibility,
   deletion propagation, backup/restore and derived indexes.
4. Shared setup and StudyLoop: packaged skill/CLI/MCP ownership, selectable harness setup,
   doctor and actual consumer integration.
5. Release acceptance: fresh installed packages, adversarial journeys, real-source read-only
   evaluation, regression suite, council review and audit against P01–P15.

No stage-only success marks the overall goal complete. Current authoritative implementation
worktree is the evidence-context-evaluation worktree; the main checkout has unrelated
uncommitted exporter work and must be left intact. Public release artifacts and private
learning/council/transcript material must remain distinguishable.
