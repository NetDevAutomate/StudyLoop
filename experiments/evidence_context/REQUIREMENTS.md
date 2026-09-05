# Bounded evaluation requirements: StudyLoop and SessionWeave

Status: acceptance plan for the existing isolated experiment. This is not a
SessionWeave implementation, a production migration or an engine recommendation.
StudyLoop is the first intended consumer; the contracts must also work for a
coding-only consumer with no learning state or teaching dependencies.

## Decision and scope

Compare the simplest design that passes the integrity gates before comparing
retrieval usefulness and cost. Keep SQLite keyword retrieval as the baseline.
Use synthetic fixtures for lifecycle and installation scenarios; reserve unseen,
lineage-separated StudyLoop and coding questions for decision-quality evaluation.
Do not relabel existing development examples as held-out evidence.

| ID | Requirement and acceptance scenario | Current evidence |
|---|---|---|
| B1 | Explicit personal, work and unclassified scopes. A single harness can contain all three; unknown scope never silently defaults to personal. Cross-scope seeds, neighbours, relationships and citations must not appear in returned packs or explanation text. | Retrieval scope tests exist; added whole-pack boundary regression. Configuration assignment and sync policy are NOT RUN. |
| B2 | Each configured sync target has an explicit allowed scope set. A personal-only target must never receive work payloads, including staged transfer files. Reclassification must remove obsolete derived entries and obey the destination policy. | PARTIAL: serialized sender filtering and receiver rejection tested in lifecycle lab. Production transport and reclassification NOT RUN. |
| E1 | Explain each included passage with source/version, exact citation and actual retrieval route. Relationship inclusion exposes reviewed edge and supporting citations. A retrieval reason does not assert truth or independent validation. | Added keyword/relationship explanation regressions. Human usefulness and multi-hop path explanations remain NOT RUN. |
| C1 | Correction preserves the prior source version and records a dated, supported correction/supersession. Current retrieval surfaces the correction; an earlier as-of query cannot see it. Re-import of the old source cannot silently make it current. | PARTIAL: parent-based current heads, historical availability, stale replay and concurrent correction tested in lifecycle lab. Exact supporting-citation integration and conflict resolution NOT RUN. |
| F1 | Forget a logical source across its versions, excerpts, edges, summaries, FTS, vectors and managed context caches. Retain only minimal deletion metadata needed to prevent resurrection, not deleted text. Ordinary historical retrieval must also respect forgetting. | PARTIAL: lifecycle lab purges versions, FTS and declared dependent artifacts; historical lookup cannot resurrect them. Real vectors, earlier evidence-store integration, transitive derivations and backups NOT RUN. |
| F2 | Two disposable replicas: A forgets while B is offline; both push/pull orders, duplicate delivery, stale re-import and index rebuild must not restore the source. Interrupted deletion must recover idempotently. Unrelated evidence must remain. | TESTED in disposable lifecycle adapter: both exchange orders, duplicate/stale replay, re-import, rebuild, real process interruption and retry. Production session-sync, backup restore and network faults NOT RUN. |
| H1 | Capture health distinguishes detected source, installed skill, registered hook, last attempted capture, last successful import, lag, parse failures and repair gaps. An empty search cannot claim complete history when capture is failing. | PARTIAL: stage 4 tests actual synthetic file imports and persisted outcomes, stale/failing/unknown health. Live configuration detection, capture watermarks and attaching health to retrieval NOT RUN. |
| I1 | StudyLoop installation delegates to a separately installable memory component. Installing that component alone imports no StudyLoop runtime. Repeat setup preserves unrelated harness config and registers one capture integration. | NOT RUN; package/install contract test required before extraction. |
| I2 | Harness selection supports arrows, Space and Enter plus noninteractive flags. Test none/one/multiple selections, cancel without writes, missing harnesses and capability-specific CLI/desktop status. Skill presence alone never means automatic export works. | NOT RUN; no new installer in this experiment. |
| I3 | One owner for DB migrations, hooks and sync configuration. StudyLoop and coding-only consumers use the same versioned CLI/MCP contract and explicit DB/config location. Upgrade or uninstall of StudyLoop must preserve shared data and integrations needed by other consumers. | NOT RUN; use temporary HOME/config directories and installed wheels, never real harness settings. |

## Minimal next fixtures and pass criteria

1. Boundary/explanation fixture: same topic across three explicit scopes and two
   projects, including a reviewed cross-scope link. Check the entire output,
   including explanation metadata. Run against each retrieval arm.
2. Lifecycle fixture: one decision, its correction and its deletion on two
   temporary replicas; inject offline state, crash/retry, stale replay and rebuild.
   Check direct lookup and every enabled derived store, not just search results.
3. Health fixture: successful import, malformed source, disabled hook and delayed
   import. Report the affected source and last known coverage without exposing
   transcript bodies. Age threshold is configurable; unknown is not healthy.
4. Install fixture: standalone consumer then StudyLoop, reverse install order,
   reinstall, upgrade and uninstall. Assert shared ownership and no duplicate
   exports; verify a real synthetic end-to-end capture. No network/provider needed.

Zero forbidden-scope disclosures, zero deleted-source resurrection, valid exact
citations, correct health state and idempotent install/merge behaviour are hard
gates. NOT RUN is not a pass. A candidate with a failing integrity gate cannot win
on answer quality. Local filters are not a claim of multi-user authorization.

For passing candidates measure held-out citation precision, evidence recall,
correction/counterevidence recall, unsupported-claim rate, useful abstention and
blinded decision usefulness at the same answering model and actual token budget.
Compare keyword, semantic (if implemented), reviewed relationships, combined and
shuffled-link control. Report per-case paired differences, sample counts and
uncertainty; do not declare a winner from a tiny curated sample. Also record p50/
p95 retrieval latency, pack tokens, import/rebuild time, disk/RAM, provider calls
and cost. No fabricated measurements for absent arms.

## Integration boundary to evaluate

The memory component owns capture, source identity, policy, storage migrations,
sync, retrieval and lifecycle operations. StudyLoop owns teaching, learning state,
review scheduling and its presentation of context. StudyLoop's installer invokes
the component's versioned setup/doctor interface rather than copying its hooks or
migrations. Existing session-* commands remain compatibility entry points during
any later extraction. A shared SKILL.md describes evidence use; harness adapters
supply supported registration and capture mechanisms.

Forgetting covers managed replicas and derived stores. Backups need an explicit
retention/restore policy that reapplies deletions before serving restored data;
external transcript originals or exported copies cannot be claimed erased by a
DB-only operation. Re-import suppression must be tested. Shared work/personal
scope must never be inferred from harness brand or machine name.

## Scope ceiling and stopping rule

Add contracts and the smallest disposable adapters needed to test them. Do not
create/publish SessionWeave, move live data, alter installed hooks, build a new
UI, add team hosting, implement general ACLs, add automatic knowledge extraction,
or introduce graph/vector services in this increment. Desktop support is a
capability to verify per source, not a blanket compatibility claim.

Stop and record a design gap when a requirement needs production integration;
do not silently implement that subsystem or replace it with a passing mock.
Once lifecycle and installation contracts are exercised, use held-out quality
results to decide whether richer retrieval merits engine experiments. Extraction
and release remain separate work. New requirements need an existing scenario or
an explicit user decision to enter this evaluation.
