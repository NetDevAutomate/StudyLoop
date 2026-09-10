# OKF / ontology removal inventory and work order

**Date:** 2026-09-10 · **Repo:** `studyloop` · **Base:** `main` @ `5712e2d7` · **Mode:** read-only verification
**Question (Andy):** *"verify if OKF is being used; I don't believe it is; if the data says it serves no purpose, remove OKF functionality totally in preparation for a semantic layer."*

**Verdict up front: OKF/ontology is not used by any shipped path, on any branch. It is excluded from
recall by design, its own value gate was never reached, and every one of its 66,324 live rows is
deterministically rebuildable at $0. Removal is safe. Andy's belief is correct.**

---

## 0. Corrections to the brief's stated facts

Four of the facts handed to this lane are wrong about *where* the evidence lives. The numbers are
real; the paths are not. Recorded so the work order cites something that exists.

| Brief said | Actual |
|---|---|
| `reviews/evidence/173-okf-ontology-value.md` records the numbers | **No `reviews/` directory exists on any branch.** The numbers live in `main:docs/architecture/session-memory/verified-architecture.architecture.json:285-295` |
| `reviews/programme/FINAL-REPORT.md` on `feat/knowledge-proof` | **Does not exist.** The equivalent is `feat/knowledge-proof:docs/adr/0011-claim-centric-learning-memory.md` §Outcome (L294-340) |
| "ontology +0.00 to fusion recall" is a measured result | It is a **recorded diagnostic note**, not a gate result. The ontology value gate **G3b was never reached** (`ADR-0011:302`). Nothing measured ontology value either way |
| "8 files each" on the three branches | **7 source modules (5,302 lines) + 12 test files (5,484 lines)**; 17 files match a bare `okf` grep |

Two further findings the brief did not anticipate:

- **PR #18's tree is byte-identical to `origin/feat/b4-recall-surfaces`** — both `2bed96b9514f1a6f7bd32b56865e8a5d4896c111`. Different commit ids (`031dbab9` vs `77f9ab1e`), same content. b4 is not a separate surface to inventory.
- **The live DB is at `PRAGMA user_version = 47` yet carries the v48/v49 schema objects.** Both `main` and PR #18 cap the numbered chain at migration 47 in the code path that stamps the version. The ontology/sidecar objects were installed out-of-band without the version bump. Flagged in §2.

---

## 1. Is it used?

### 1.1 Per-branch verdict

| Branch | OKF/ontology code | Verdict |
|---|---|---|
| `main` @ `5712e2d7` | none | **ABSENT** |
| `feat/sessionweaver-phase2-retrofit` (= PR #18, = `origin/feat/b4-recall-surfaces`) | 7 modules, 5,302 lines | **BUILT-BUT-UNREAD** |
| `feat/knowledge-proof` | identical blobs to PR #18 | **BUILT-BUT-UNREAD** |
| `feat/b5-real-corpus` | identical except 2 files | **BUILT-BUT-UNREAD** |

No branch is `used-in-shipped-path`.

### 1.2 `main` — absent

- `git grep -il okf main -- 'packages/*'` returns **2 hits, both vendored binaries** (`.../vendor/css/files/inter-latin-ext.woff2`, `.../vendor/dev/js/ghostty-web-0.4.0.js`) — byte coincidence in compressed data, not code.
- `git grep -in -E 'ontology_(class|property|structural|individual|relation|build_state)|context_concept' main -- 'packages/*'` → **zero hits.**
- The only `ontology` string in `main`'s code is course-content prose in `main:packages/studyloop/tests/e2e/test_journey_new_user_first_plan.py:72,86,110,270` ("knowledge graphs, ontology services") — a study topic in a test fixture, unrelated to the OKF graph.

**A separate, live, non-OKF surface exists on `main` and must not be confused with OKF.** The legacy
*learning-tier* concept tables are created by migrations v12/v13 and read by a registered MCP tool:

| Surface | Cite | Live rows |
|---|---|---|
| `CREATE TABLE ... knowledge_bridges` | `main:packages/agent-session-tools/src/agent_session_tools/migrations.py:552` | 0 |
| `CREATE TABLE ... concepts` | `main:.../migrations.py:584` | 0 |
| `CREATE TABLE ... concept_aliases` | `main:.../migrations.py:599` | 0 |
| `CREATE TABLE ... concept_relations` | `main:.../migrations.py:610` | 0 |
| `CREATE TABLE ... message_concepts` | `main:.../migrations.py:642` | 0 |
| MCP tool `get_concept_context` | `main:packages/studyloop/src/studyloop/mcp/tools.py:637` → `agent_concept_context` at `main:packages/studyloop/src/studyloop/learning/mastery.py:670` | reads 0-row tables |
| Registered in a shipped agent | `main:agents/kiro/study-mentor.json:62` (`mcp_studyloop_get_concept_context`) | — |
| Contract-pinned by tests | `main:packages/studyloop/tests/test_install_agent_contracts.py:525,567,576` | — |

This is the **learning tier**, not OKF. It is registered and callable, returns nothing (0 rows), and
is out of scope for OKF removal. Deleting it would break `test_install_agent_contracts.py`. Left
alone by this work order; noted in §5.

### 1.3 The OKF/ontology code (identical on all three branches)

Blob hashes are the same across `feat/sessionweaver-phase2-retrofit`, `feat/knowledge-proof` and
`feat/b5-real-corpus` except two files on b5.

| Module | Lines | Blob (PR18 / kp / b5) |
|---|---|---|
| `packages/agent-session-tools/src/agent_session_tools/ontology.py` | 1,633 | `caa52f38` all three |
| `.../ontology_live.py` | 385 | `bdb820ed` all three |
| `.../context/okf_import.py` | 649 | `babe601c` all three |
| `.../context/concepts.py` | 1,194 | `83496507` all three |
| `.../context/concept_live.py` | 369 / 369 / **376** | `ce028ba6` · `ce028ba6` · **`c251de0d`** |
| `.../context/concept_schema.py` | 628 | `c35b15a5` · `c35b15a5` · **`5113d0c2`** |
| `.../context/concept_cli.py` | 444 | `8534cd0a` all three |
| **Source total** | **5,302** | |

### 1.4 Migrations that CREATE the tables

Both live only on the feature branches. Each carries its own authored downgrade drop list — which is
the authority for §4(d).

| Migration | Cite | Creates | Documented downgrade |
|---|---|---|---|
| **v48** "Derived tier-1 ontology: structural/individual/relation graph, never synced" | `feat/sessionweaver-phase2-retrofit:packages/agent-session-tools/src/agent_session_tools/migrations.py:1577-1598`, calls `ontology.install_schema` | the six `ontology_*` tables | *"drop exactly these six tables and nothing else"* (`migrations.py:1591-1595`) |
| **v49** "Concept sidecar: immutable roots, append-only lifecycle events, read model" | `.../migrations.py:1604-1644`, calls `context.concept_schema.install_schema` | `context_concepts`, `context_concept_events`, `context_concept_clock`, `context_concept_fts`, `context_concept_schema` | *"drop exactly the five objects named above plus the two guard triggers the sidecar installs on `context_citations`"* (`migrations.py:1619-1627`) |

DDL bodies: `ontology.py:703-747` (six `CREATE TABLE`), `concept_schema.py:40-338` (tables, FTS5
virtual table, 11 triggers including `context_concepts_bound_proof` at `:121`).

### 1.5 Every reader / writer of the tables

| Surface | Name | Branch | Cite | Reads or writes |
|---|---|---|---|---|
| CLI | `session-maint ontology-rebuild` | PR18/kp/b5 | `maintenance.py:929-976` | **writes** all six |
| CLI | `session-maint ontology-status` | PR18/kp/b5 | `maintenance.py:978-992` | reads (diagnostics only) |
| CLI | `session-context` OKF import verb | PR18/kp/b5 | `concept_cli.py:360-377` (`run_import_okf` → `import_okf`) | writes `context_concepts` |
| Export hook | `refresh_ontology_after_export` | PR18/kp/b5 | `export_sessions.py:178-200`, invoked `:268-281` | **writes** all six on every export |
| Sync | `_sanitize_ontology_snapshot` | PR18/kp/b5 | `sync.py:456-485` | **strips** all six from seed snapshots |
| Doctor | `check_ontology_freshness` | PR18/kp/b5 | `studyloop/cli/_doctor.py:96`, registered `:145` | reads (health only) |
| Live harness | acceptance-on-backup | PR18/kp/b5 | `ontology_live.py:1-130` | reads on disposable copies |
| MCP | `memory_winddown` | PR18/kp/b5 | `mcp_server.py:204-230` | writes `context_concepts` |
| MCP | `memory_recall` | PR18/kp/b5 | `mcp_server.py:244-253` | **reads concepts; explicitly NOT ontology** |
| Package entry points | `session-maint`, `session-context`, `session-db-mcp` | PR18/kp/b5 | `pyproject.toml:45-53` | — |

**There is no reader of the six `ontology_*` tables anywhere in a serving path.** Every consumer is a
writer, a diagnostic, or a stripper. The design says so in three independent places:

- `mcp_server.py:253` — `memory_recall` docstring: *"No embedding or ontology store."*
- `recall.py:4` — *"queries no embeddings or ontology tables, and returns concepts before…"*
- `docs/mcp.md:41` (knowledge-proof) — *"does not import semantic search, read embedding tables or consult ontology"*

### 1.6 Archived remote branches (list only, no action — §4c)

| Branch | HEAD | Diff vs main | OKF files |
|---|---|---|---|
| `origin/feat/b1-fresh-install-scope` | `40da8e5f` | 28 files, +2,050 | 0 |
| `origin/feat/b2-ontology-migration` | `a6e78d3c` | 35 files, +6,540 | 0 (pre-OKF-import) |
| `origin/feat/b3-concept-lifecycle` | `790eff34` | 80 files, +20,999 | 17 |
| `origin/feat/b4-recall-surfaces` | `77f9ab1e` | 93 files, +24,054 | 17 — **same tree as PR #18** |

---

## 2. Who wrote the live tables

`SELECT * FROM ontology_build_state` (`mode=ro`):

| key | value |
|---|---|
| `singleton` | 1 |
| `extraction_version` | `tier1-v2-canonical-messages` |
| `logical_hash` | `8155471eaa70e9ee…d35a40c` |
| `completed_at` | `2026-09-08T21:27:49.409320Z` |
| `mode` | `full` |
| `source_session_count` | 5,818 |
| `source_message_count` | 140,066 |
| `candidate_session_count` | 5,818 |
| `counts` | classes 7 · properties 6 · structural 23,263 · individuals 13,542 · relations 29,505 |

`SELECT * FROM context_concept_schema`: `id=1`, `schema_version=2`,
`schema_fingerprint=af95685e…fe11011d`.

**Attribution.** `extraction_version = "tier1-v2-canonical-messages"` matches `EXTRACTION_VERSION`
at `ontology.py:34` on all three branches; `schema_version = 2` matches v49's *"`SCHEMA_VERSION = 2`
preserved byte-for-byte from the SessionWeaver reference"* (`migrations.py:1613`). The single
`context_concepts` row carries `producer = session-weaver/winddown` and
`source_uri = sessionweaver://session/ddae6300-…`, written `2026-09-08T21:36:42Z` — nine minutes
after the ontology build. **Both were written by the SessionWeaver phase-2 retrofit code, i.e. the
PR #18 / b4 tree, in one session on the evening of 2026-09-08.**

**Version mismatch to flag:** live `user_version = 47`, but the v48/v49 objects are present. The
schema was installed without the numbered chain stamping the version, so a future migrate run may
try to apply v48/v49 over existing objects. Removal makes this moot; a partial removal must not
leave it.

**Rebuildable at $0 — confirmed from the builder, not from prose.** `ontology.py`'s module docstring
(L11-19):

> *"Every row in `ontology_structural`, `ontology_individual` and `ontology_relation` is derived from
> `sessions`/`messages` and is byte-for-byte reproducible by a full rebuild — nothing here is
> user-authored or carries independent provenance. That is why the ontology is *derived, never
> synced* … and why a rebuild is always safe to re-run."*

Corroborated mechanically: the module's entire import set is `hashlib, json, logging, re, sqlite3,
collections.abc, dataclasses, datetime, typing` (`ontology.py:22-30`) — **no LLM, embedding, HTTP or
API client of any kind.** `logical_hash` is `sha256` over canonical JSON (`ontology.py:321-322`).
`sync.py:456-485` never lists an `ontology_*` table in `SYNC_TABLES`. Rebuild cost is recorded as
3.42 s cold / 1.12 s incremental (`main:docs/architecture/session-memory/verified-architecture.architecture.json:294`).

**All 66,324 ontology rows are derived, deterministic, and free to regenerate. Dropping them
destroys no unique information.** The single `context_concepts` row is *not* derived — it is one
agent-authored wind-down Finding, the only one ever written (see §4d).

---

## 3. What the data says

Sources: `main:docs/architecture/session-memory/README.md`,
`main:docs/architecture/session-memory/verified-architecture.architecture.json`, and
`feat/knowledge-proof:docs/adr/0011-claim-centric-learning-memory.md` (the real "final report").

**On the ontology specifically**

| Claim | Cite |
|---|---|
| *"Ontology is diagnostics: excluded from recall by design"* | `verified-architecture.architecture.json:286` |
| *"Adding the ontology arm to fusion moved recall +0.00"* | `verified-architecture.architecture.json:295` |
| *"memory_recall — no ontology input"* (edge label) | `verified-architecture.architecture.json:262` |
| *"The tier-1 ontology is **not** a recall arm."* — ADR decision clause 5 | `ADR-0011:50-51` |
| Gate **G3b Ontology value**: *"**Not reached.**"* | `ADR-0011:302` |
| G3b was to require typed-query accuracy ≥ 0.90 and an established `OH − H` lift | `validation-ruler.md:84` |
| Ontology rebuild 3.42 s cold / 1.12 s incremental, one logical hash | `verified-architecture.architecture.json:294` |

**On the concept store the ontology was to serve**

| Claim | Cite |
|---|---|
| *"**2,035 scanned · 2,033 parsed · 0 bound · 2,033 legacy_unbound** … The PoC writer paraphrased; nothing was ever citation-bound."* | `main:docs/architecture/session-memory/README.md:73` |
| Receipt confirms: `bound: 0`, `legacy_unbound: 2033`, `no_exact_match: 1559`, `body_description_mismatch: 764`, `no_visible_evidence: 429`, `oversized_evidence: 45` | `feat/knowledge-proof:openspec/changes/sessionweaver-phase2-retrofit/evidence/legacy-okf-import-report.json` |
| *"0 of 2,033 imported OKF concepts citation-bound"* | `verified-architecture.architecture.json:285` |
| n=25 evidence is a **parity** check, not a lift measurement: `ordered_hit_lists_identical: 25`, `mismatches: 0`, `questions: 25` | `docs/data/b4-recall-live-evidence.json` |

**On the wider knowledge layer (context for the removal)**

| Claim | Cite |
|---|---|
| **G1 recall NOT ESTABLISHED** — fused arm macro recall@5 **0.129** vs bar 0.64; significantly *worse* than prose alone (−0.154, CI95 [−0.252, −0.065]), replicating DEV (−0.140) | `ADR-0011:301` |
| **Composite:** *"The knowledge layers improve agent decisions" **may not be written.*** | `ADR-0011:304` |
| ADR status: *"**measured — not established**"*; *"Would have superseded (gates did not pass): the retrieval half of PR #18 (`memory_recall` over legacy concepts, ontology as a recall arm)"* | `ADR-0011:3-5` |
| *"Retains PR #18's capture half (native evidence, hash binding, the bound-proof trigger design)."* | `ADR-0011:5` |
| **The one established win:** prose control `B1_clean` outscored the shipped path by **+0.168** (CI95 lower +0.076); *"Look 2 attributed most of that to the shipped AND-first planner (F-B0-1: +0.142 of it). Fixing the planner in `agent-session-tools` is the actionable outcome of this programme."* | `ADR-0011:307-312` |

### Verdict paragraph

**No measured result supports keeping OKF/ontology as a product component — and none ever
contradicted it either, because the ontology's own value gate was never run.** The honest position is
stronger than "it measured badly": the ontology was *architecturally excluded from recall by design*
(`verified-architecture.architecture.json:286`, `ADR-0011:50`), the one exploratory attempt to add it
to fusion *"moved recall +0.00"* (`:295`), and gate G3b — the only test that could have established
value — is recorded *"Not reached"* (`ADR-0011:302`). Meanwhile the layer it existed to serve failed
decisively (G1 fused arm 0.129 against a 0.64 bar, actively *worse* than prose alone), and the 2,033
concepts it was to reason over are **0-for-2,033 citation-bound**. The single measured win of the
entire programme is a *prose FTS query-planner* fix (+0.142 of +0.168) that needs no ontology, no
concept store and no graph. There is no data-supported case for retention; there is a positive
data-supported case for the semantic layer being built on prose retrieval instead.

---

## 4. Removal work order

### (a) PR #18 — `feat/sessionweaver-phase2-retrofit` (27 commits)

The branch is **two separable halves**. This resolves the earlier open decision
("merge capture half only, hold, or close") in favour of **merge the keep-half, drop the OKF half** —
because the keep-half contains the programme's only established result.

**DROP — OKF / ontology / concept store (13 commits)**

| Commit | Subject |
|---|---|
| `348dd6dc` | feat(ontology): add tier-1 ontology (migration v48), export refresh, and diagnostics |
| `f9c23367` | docs(ontology): document the derived, never-synced tier-1 ontology |
| `5f4871c2` | fix(ontology): address review round 1 |
| `92a56254` | docs(openspec): check off B2 tasks 2.1-2.3, note 2.4's split |
| `d383f3f7` | feat(context): install the concept sidecar as migration v49 |
| `e3560892` | feat(context): lift concept lifecycle, wind-down, OKF import and projection |
| `30d6bce4` | feat(context): replicate concept events under the frozen standing order |
| `cf2abf81` | feat(memory): add winddown/concept CLI verbs and the memory_winddown MCP tool |
| `74e5db44` | docs(context): document concept memory; attach the legacy OKF import evidence |
| `08adfbb1` | docs(openspec): check off B3 tasks 3.1-3.5 and attach the import evidence |
| `790eff34` | test(context): pin the retained v49 receipt to the shipped migration |
| `d5731339` | feat(mcp): add contract-frozen memory recall |
| `7f73c111` | test(memory): record B4 recall acceptance |

**KEEP — capture / install / planner half (14 commits)**

| Commit | Subject | Why keep |
|---|---|---|
| `fb33e2ce` | feat(mcp): add shared AND-to-OR query planner | **the +0.142 established win** (`ADR-0011:311`) |
| `36002102` | test(mcp): pin pre-planner session_search output | guards it |
| `4fe2e4cd` | fix(mcp): preserve legacy session search syntax | guards it |
| `48ce4393` | feat(install): register StudyLoop MCP servers | install plumbing |
| `99eb9159` | fix(install): preserve unrelated MCP entry bytes | install plumbing |
| `7068ac44` | fix(install): repair arbitrary MCP config shapes | install plumbing |
| `77f9ab1e` | fix(install): preserve TOML multiline strings | install plumbing |
| `40da8e5f` | fix(memory): fail closed with one structured diagnostic on unconfigured scope | scope safety |
| `a326c317` | test(memory): make the virgin-HOME study test independent of installed agents | test hygiene |
| `a6e78d3c` | test(sync): cover remote backup command failure | sync safety |
| `6938f4b6` | test(sync): make backup failure deterministic | sync safety |
| `e1560f2d` | test(context): deselect live markers in package-scoped pytest runs | test hygiene |
| `d6831511` | docs(openspec): propose sessionweaver phase 2 retrofit | history |
| `b01dc8d5` | docs(openspec): apply design-review minors | history |

**Finish line:** a rebased branch of exactly the 14 keep-commits; `git grep -il okf <branch> -- 'packages/*'` returns **only the 2 vendor binaries**; `git grep -c ontology_ <branch> -- 'packages/*'` = **0**; full suite green; PR #18 closed or force-updated to the keep-half.

### (b) `feat/knowledge-proof` — OKF import-only adapter files

Identical blobs to PR #18. Delete the 7 modules (5,302 lines) and 12 test files (5,484 lines).
Retain the branch's evidence and ADR-0011 — they are the *justification* for removal and must
outlive the code.

**Finish line:** `git grep -il okf feat/knowledge-proof -- 'packages/*'` returns only the 2 vendor
binaries; `docs/adr/0011-*.md` and `openspec/.../evidence/legacy-okf-import-report.json` still
present.

### (c) Archived remote branches — list only, no action

`origin/feat/b1-fresh-install-scope`, `origin/feat/b2-ontology-migration`,
`origin/feat/b3-concept-lifecycle`, `origin/feat/b4-recall-surfaces` (identical tree to PR #18).
Leave as historical record. **Finish line:** none — explicitly out of scope.

### (d) Live DB — **REQUIRES ANDY'S EXPLICIT CONFIRMATION + `.bak` FIRST**

> ⚠️ **This is a delete against the only surviving copy of 5,879 sessions**
> (`ADR-0011:17-19`: the originals of 5,261 sessions "have been rotated away by the harnesses").
> The *ontology* rows are derived and rebuildable; the DB they live in is not. Take a verified
> `.bak` (size + `sha256` recorded) before any `DROP`, and do not run this without Andy saying so
> per-run.

Drop list, authored by the migrations' own downgrade notes (`migrations.py:1591-1595`, `:1619-1627`):

```sql
-- v48 downgrade: "exactly these six tables and nothing else"
DROP TABLE ontology_relation;        -- 29,505 rows
DROP TABLE ontology_structural;      -- 23,263 rows
DROP TABLE ontology_individual;      -- 13,542 rows
DROP TABLE ontology_class;           --      7 rows
DROP TABLE ontology_property;        --      6 rows
DROP TABLE ontology_build_state;     --      1 row
-- subtotal: 66,324 rows, all deterministically rebuildable at $0

-- v49 downgrade: "exactly the five objects named above plus the two guard triggers"
DROP TRIGGER context_citations_bound_insert;   -- lives on context_citations, survives table drops
DROP TRIGGER context_citations_bound_delete;   -- ditto
DROP TABLE context_concept_fts;      -- FTS5 virtual; takes its 4 shadow tables
DROP TABLE context_concept_schema;   --      1 row
DROP TABLE context_concept_clock;    --      1 row
DROP TABLE context_concept_events;   --      1 row
DROP TABLE context_concepts;         --      1 row  <-- NOT derived; see note
-- also drop the 6 replica_content_context_concept{s,_events}_{insert,update,delete} triggers
-- created at migrations.py:1636-1644
```

**Note on the one non-derived row.** `context_concepts` holds a single agent-authored wind-down
Finding — *"Uniform fixture timestamps hid a lexicographic SQL MAX bug"*
(`producer = session-weaver/winddown`, session `ddae6300-…`, `binding_state = bound`). It is the only
concept ever written and the only row in this drop list that a rebuild cannot regenerate. **Export it
to markdown before dropping** — it is a genuine teaching moment and costs nothing to keep as prose.

**Do NOT drop** (0 rows, but on `main`'s migration chain and contract-pinned by a live MCP tool —
see §1.2): `concepts`, `concept_aliases`, `concept_relations`, `concept_dependencies`,
`message_concepts`, `knowledge_bridges`, and **`context_citations`** (evidence layer — the semantic
layer needs it, §5).

**Also settle the version mismatch:** live `user_version = 47` already, so no downgrade stamp is
needed after the drops — but verify it still reads 47 afterwards and that a subsequent migrate run is
clean.

**Finish line:** `.bak` taken with recorded `sha256`; the single Finding exported; `SELECT COUNT(*)
FROM sqlite_master WHERE name LIKE 'ontology%' OR name LIKE 'context_concept%'` = **0**;
`PRAGMA integrity_check` = `ok`; `PRAGMA foreign_key_check` empty; `SELECT COUNT(*) FROM sessions` =
**5,879** unchanged.

### (e) Docs / ADRs

**On `main`** — no ADR mentions OKF or ontology (`docs/adr/` holds 0001-0010 only; ADR-0011 is
branch-only). Four doc surfaces need edits:

| File:line | Content |
|---|---|
| `main:docs/architecture/session-memory/README.md:54` | Concept-sidecar row: `context_concepts`, `context_concept_fts`, `context_concept_events`; `concept import-okf` |
| `main:docs/architecture/session-memory/README.md:73` | The 2,035/2,033/0-bound import receipt row — **keep as history, mark RETIRED** |
| `main:docs/architecture/session-memory/README.md:104,155` | `context_concepts` type column; `ontology_build_state` arm |
| `main:docs/architecture/session-memory/GLOSSARY.md:34` | Tier-2 definition referencing `context_concepts` |
| `main:docs/architecture/session-memory/verified-architecture.architecture.json:126-128,154-157,183-185,239-252,262,285-295` | `ontology` and `concepts` nodes, their edges, and the five finding strings |
| `main:docs/session-db-tiering.md:85` | `knowledge_bridges` anchoring — learning tier, **leave** |
| `main:docs/adr/0006-bridge-aware-deferred-topics.md:106` | `knowledge_bridges` — learning tier, **leave** |

**On branches:** `feat/knowledge-proof:docs/session-memory.md:109-114`, `docs/context-memory.md:348`,
`docs/mcp.md:41`, `docs/adr/0011-*.md`, `docs/architecture/session-memory/validation-ruler.md:21-22,83-84`,
`docs/data/ontology-migration-v48-receipt.json`, `docs/data/ontology-tier1-baseline-upstream.json`,
`docs/data/concept-sidecar-migration-v49-receipt.json`, `docs/data/b4-recall-live-evidence.json`.

**Write a new ADR-0011 on `main`** ("Retire the tier-1 ontology and concept sidecar") citing §3.
The branch ADR-0011 is a *different* decision under the same number — resolve the collision before
merging anything.

**Finish line:** a new `main` ADR exists; no `main` doc describes OKF/ontology in the present tense;
every retired claim is marked RETIRED rather than deleted.

### (f) Config keys / MCP registrations

| Surface | Cite | Action |
|---|---|---|
| `main:agents/kiro/study-mentor.json:60` — `mcp_session-db_memory_search` | still valid (prose search) | **keep** |
| `main:agents/kiro/study-mentor.json:62` — `mcp_studyloop_get_concept_context` | learning tier, 0 rows, contract-pinned | **keep for now** — see §5 |
| PR18 `memory_winddown`, concept CLI verbs | `mcp_server.py:204-230`, `concept_cli.py:360-377` | **drop with the branch half** |
| PR18 entry points `session-maint` / `session-context` | `pyproject.toml:45-53` | **keep the scripts**, drop only the `ontology-*` and OKF subcommands |
| `agents/claude/mcp.json`, `agents/opencode/mcp.json`, `agents/opencode/opencode.json`, `agents/manifest.json` | no concept/ontology tool names | **no change** |

**Finish line:** `git grep -inE 'ontolog|import-okf|memory_winddown' -- 'agents/*' '*.json' '*.toml'`
returns **0** on the merged result.

### (g) Tests — delete (all on the feature branches only)

| File | Lines | Action |
|---|---|---|
| `tests/test_okf.py` | 1,393 | delete |
| `tests/test_ontology.py` | 1,151 | delete |
| `tests/test_concept_integrity.py` | 688 | delete |
| `tests/test_concept_schema.py` | 475 | delete |
| `tests/test_concept_cli.py` | 439 | delete |
| `tests/test_ontology_live.py` | 326 | delete |
| `tests/test_sync_ontology_sanitization.py` | 242 | delete |
| `tests/test_export_ontology_refresh.py` | 196 | delete |
| `studyloop/tests/test_doctor_ontology.py` | 178 | delete |
| `tests/test_maintenance_ontology_cli.py` | 151 | delete |
| `tests/test_concept_service_api.py` | 126 | delete |
| `tests/test_okf_import_live.py` | 119 | delete |
| **total** | **5,484** | |

**Retarget, do not delete:** `tests/conftest.py`, `tests/test_migrations.py`,
`tests/test_recall.py`, `tests/test_package_pytest_config.py`,
`tests/test_export_verification.py` (b5) — each references ontology/concept fixtures but also covers
non-OKF behaviour. `main:packages/studyloop/tests/test_install_agent_contracts.py` must stay green
untouched (it pins `get_concept_context`, §1.2).

**Finish line:** 12 files deleted, 5 retargeted; full suite green; **and every CI gate** —
`ruff check`, `ruff format --check`, typecheck, `bandit` — green, not pytest alone.

---

## 5. What a semantic layer needs — do NOT remove

Removal must be surgical. These are the load-bearing surfaces the ontology sat *beside*, not on top
of, and the measured win (`ADR-0011:307-312`) runs entirely through them.

| Keep | Why | Cite |
|---|---|---|
| `sessions` (5,879), `messages` (143,908) | the corpus; **only surviving copy** of 5,261 sessions' history | `ADR-0011:17-19`; live DB |
| `messages_fts` + prose FTS path | the **+0.168 established win** is prose-only FTS | `ADR-0011:307-309` |
| **AND-to-OR query planner** (`fb33e2ce`) | **+0.142 of the win**; ADR calls the planner fix *"the actionable outcome of this programme"* | `ADR-0011:311-312` |
| `context_assertions`, `context_citations`, `context_evidence` | claims/evidence + quote-binding; the sidecar FK pointed *to* these, never the reverse | `migrations.py:1624-1627` |
| The bound-proof *design* (`substr(body,start,end)==quote`) | ADR explicitly retains PR #18's capture half incl. hash binding and the trigger design | `ADR-0011:5`; `concept_schema.py:121` |
| `agent_session_tools.recall` prose path | already ontology-free by contract | `recall.py:4` |
| MCP `session_search`, `memory_search`, `session_context`, `session_stats` | shipped, in use, no ontology input | `mcp_server.py:395,148,531,605` |
| Learning tier: `concepts`, `concept_dependencies`, `knowledge_bridges`, `message_concepts` + `get_concept_context` | 0 rows but contract-pinned on `main`; a *separate* retirement decision | §1.2 |
| Six-adapter export registry | unrelated to OKF; governed by its own ruling | `main` @ `5712e2d7` |
| All evidence/receipts/ADR-0011 | the justification for removal must outlive the code | §3 |

**Guidance for the semantic layer:** build on prose FTS + the fixed planner + the claims/evidence
tables. The measured lesson is not "graphs are bad" — it is that a *high-recall, low-precision peer
list displaces rank-1/2 prose hits* (`ADR-0011:314-318`). Any future semantic arm should be
pre-registered as a **re-ranker or a precision-gated candidate source, never an equal-weight peer
list** (`ADR-0011:318-320`).

---

## Appendix — verification commands run

```bash
git grep -il okf main -- 'packages/*'                      # 2 hits, both vendor binaries
git grep -in -E 'ontology_(class|property|structural|individual|relation|build_state)|context_concept' \
        main -- 'packages/*'                               # 0 hits
git rev-parse feat/sessionweaver-phase2-retrofit^{tree} \
              origin/feat/b4-recall-surfaces^{tree}        # identical: 2bed96b9…
sqlite3 'file:~/.config/studyloop/sessions.db?mode=ro' \
        'SELECT * FROM ontology_build_state;'              # §2
```

All DB reads used `mode=ro`. No file in the repo was modified other than this report. No commit, no
`git checkout`/`switch`, no search outside the repo and `~/.config/studyloop`.
