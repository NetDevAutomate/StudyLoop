# Council record — Stage 5 (OKF removal part 2: code, docs, registrations)

**Date:** 2026-09-10 · **Cadence:** single seat (`openai.gpt-6-astra`, 797 words, 31 s, 5,453 tokens)
per the plan council's ruling; no BLOCKING/MAJOR raised, so no escalation. **Verdict:**
**ACCEPT-WITH-CORRECTIONS** — four MINOR, all evidence gaps rather than defects, all closed below by
measurement.

## What landed

| tree | commit | content |
|---|---|---|
| `main` | `f30af0b1` | ADR-0011 *Retire the OKF import, the tier-1 ontology and the concept sidecar* (Accepted); session-memory README relabelled (new label RETIRED on every ontology/OKF/sidecar claim + dated retirement section); GLOSSARY section RETIRED with note; archify spec −3 components/−4 connections/−2 cards/−1 empty boundary (validate showcase 9/9); `.gitignore` comment; `docs/session-memory.md` pointer; ADR index row. `main` never had OKF code. |
| `feat/knowledge-proof` | `50008ef1` | 57 files, +88/−19,300: 12 modules + 18 test files deleted in agent-session-tools (incl. the sidecar-only authorization/projection/safe_fs/winddown seams and `recall.py`); migrations v48/v49 removed, `CURRENT_VERSION` 49→47; `memory_winddown`/`memory_recall` MCP tools removed (tool set = `main`'s); `check_ontology_freshness` + doctor registration removed; `test_doctor_ontology.py`, `scripts/b4_recall_acceptance.py` deleted; live markers removed from both pyprojects. |
| `feat/knowledge-proof` | `ffdaeffc` | Branch ADR 0011 (claim-centric learning memory) opens with a "Superseded sections" note, OKF sections marked RETIRED, decision itself stands; frozen validation ruler gains an amendment (G3a/G3b scored layers that no longer exist); user docs no longer describe the layers; CHANGELOG `### Removed`; four OKF evidence JSONs `git mv`'d unchanged to `receipts/retired-okf-evidence/`. |

Pre-edit tip preserved: local tag `archive/feat-knowledge-proof-pre-okf-removal-2026-09-10` → `27842b79`
(tag push is the owner's; the platform blocks agent pushes of tags as of branches).

Method notes worth keeping: the lane restoring "whole-diff-was-OKF" files first used `main`'s current
version and caught itself — `main` had advanced past the merge base, so that imported `main`'s newer
work; it redid three files from the **merge base** `fb606468`. `recall.py` was first retargeted by the
lane, then deleted by the coordinator: it is PR #18's `memory_recall` engine (`d5731339`, inventory
drop-half), and a concept-free copy would have been a second `session_search`.

## Dispositions

| id | severity | finding | disposition | measurement |
|---|---|---|---|---|
| F1 | MINOR | "gates green" overstates; studyloop has 30 non-passing outcomes not shown baseline-equivalent | **CLOSED.** Node-id set comparison: worktree studyloop reds = **30**, **0 unexpected** vs the Stage 3 pinned set (the two branch-expected extras — mise-tmux, pre-Stage-3 R-10 — were not red this run). agent-session-tools 1,691 passed / 0 failed. Wording corrected to "static gates green; studyloop reds ⊆ pinned environment set". | `comm` over sorted node-id files |
| F2 | MINOR | grep not reproducible from filenames; excluded paths may hide present-tense text; evidence moves unverified | **CLOSED.** Exact command with patterns and exit status recorded below; `packages/` grep exits 1 (no match) on `ffdaeffc`; whole-tree grep hits only `CHANGELOG.md` lines 12–27 (the Removed entry). All four moved evidence blobs are byte-identical (`git rev-parse` old vs new). Allow-list with reasons below. | this record |
| F3 | MINOR | "entire branch diff was OKF" asserted, not demonstrated for the ten restored files | **CLOSED by blame attribution.** Every line the restore discarded was blamed at the pre-edit tip: **1,638 lines**, of which 631 `348dd6dc` (ontology v48), 364 `d383f3f7` (sidecar v49), 213 `30d6bce4`, 192 `cf2abf81` (winddown), 98 `5f4871c2`, 98 `790eff34`, 25 `d5731339` (memory_recall), 9 `e1560f2d`, 7 `e3560892` — all OKF commits — and **1 line from `40da8e5f`**: the `@tool(annotations=…)` decorator of the removed `memory_winddown` tool. Nothing non-OKF was discarded. | `git blame --line-porcelain 27842b79 -L …` over every removed hunk |
| F4 | MINOR | `memory_recall` ≡ `session_search` is unproven; justify deletion as drop-half retirement | **ACCEPT wording.** Deletion is justified as retirement of the inventoried drop-half (`d5731339`) under the owner's no-remnants directive, not as capability equivalence. What `memory_recall` reported beyond `session_search` — plan/k/project echo — is metadata about a query, not a retrieval capability; if wanted, it is a `session_search` option, not a second tool. Recorded as a hand-off note, not restored. | inventory §4(a) drop table |
| Q4 | — | v47 code opening the live DB (user_version 47, v48/v49 objects present) — startup hazard? | **CLOSED by run.** `VACUUM INTO` clone of the live DB (1.0 GB, read-only source): branch `migrate()` returns `[]`, `user_version` 47 → 47, the 31 orphaned `ontology_*`/`context_concept*` objects untouched, `integrity_check` ok, planner search returns rows. No hazard; the objects wait for Stage 6. | transcript |
| Q5 | — | keep or delete the RETIRED README section and GLOSSARY terms? | Seat agrees: **keep** — historical technical detail under an unambiguous RETIRED heading is not a product promise. | — |

## The finish-line grep, exactly

```
P='okf|ontolog|concept_sidecar|context_concept|memory_winddown|memory_recall|check_ontology|live_concepts|live_ontology'
git grep -ilE "$P" ffdaeffc -- 'packages/*' ':!**/vendor/**' ':!packages/studyloop/tests/e2e/test_journey_new_user_first_plan.py'
→ exit 1 (no matches)
git grep -inE "$P" ffdaeffc -- . ':!docs/architecture/session-memory/receipts' ':!docs/adr/0011*' ':!openspec' \
   ':!scripts/plan_agent_harness.py' ':!**/vendor/**' ':!packages/studyloop/tests/e2e/test_journey_new_user_first_plan.py' ':!.secrets.baseline'
→ CHANGELOG.md:12-27 only (the Removed entry)
```

Allow-list, with reasons:

| excluded path | why it may mention OKF | class |
|---|---|---|
| `docs/architecture/session-memory/receipts/**` | the receipts that document the experiment and this removal; immutable | historical record |
| `docs/adr/0011*` (both trees) | `main`: the retirement ADR; branch: RETIRED-marked sections of the claim-centric ADR | decision record |
| `openspec/**` | 59 files describing the retired proposal — **deleted in Stage 8**, not hidden | Stage 8 work |
| `scripts/plan_agent_harness.py`, `tests/e2e/test_journey_new_user_first_plan.py` | "ontology services" as a *learner's study topic* in fixtures | unrelated fixture |
| `**/vendor/dev/js/ghostty-web-0.4.0.js` | minified identifier `oKf` | unrelated |
| `.secrets.baseline` | file paths of receipts | tooling |
| `CHANGELOG.md` (branch) | the `### Removed` entry naming what was removed | changelog |

## Stage 5 finish line — met

- `main`: no doc describes OKF/ontology/sidecar in the present tense; every claim RETIRED; ADR-0011 exists.
- `feat/knowledge-proof`: zero OKF code, tests, migrations, registrations or markers; MCP tool set = `main`'s;
  static gates green on both packages; agent-session-tools 1,691/0; studyloop reds ⊆ pinned set.
- Not in Stage 5 by design: the live DB's 31 orphaned v48/v49 objects (Stage 6, owner-gated); openspec
  (Stage 8); tag/branch pushes (owner).

## Hand-off notes added

6. `memory_recall`'s plan/k/project echo, if ever wanted, belongs as a `session_search` option, not a tool.
7. Tag `archive/feat-knowledge-proof-pre-okf-removal-2026-09-10` needs `git push origin refs/tags/…` (owner).
