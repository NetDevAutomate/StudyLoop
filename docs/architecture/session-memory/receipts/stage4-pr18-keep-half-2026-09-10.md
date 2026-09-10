# Stage 4 receipt — PR #18 keep-half integrated onto `main` (pre-merge, council pending)

**Date:** 2026-09-10 · **Branch:** `integrate/pr18-keep-half` (11 commits on `main` @ `9235ab79`, tip
`4ab13499`) · **Source:** `feat/sessionweaver-phase2-retrofit` @ `031dbab9` = PR #18 (OPEN, 31 commits
incl. 4 merges) · **Method:** `git cherry-pick -x` of named SHAs in branch order, `git grep` for
`okf|ontolog|check_ontology|user_version = 4[89]|memory_winddown|concept_cli` over `packages/` after
every pick.

## Commit manifest (all 31 classified)

| PR commit | subject | class | on integration branch |
|---|---|---|---|
| `d6831511` | docs(openspec): propose phase 2 retrofit | **skip** (plan council: openspec retired in Stage 8) | — |
| `b01dc8d5` | docs(openspec): design-review minors | **skip** (same) | — |
| `348dd6dc` | feat(ontology): tier-1 ontology, migration v48 | drop | — |
| `40da8e5f` | fix(memory): fail closed on unconfigured scope | **keep** | `e71f3537` (conflicts: `.secrets.baseline` regenerated whole-repo; PR-only `openspec/…/tasks.md` dropped) |
| `f9c23367` | docs(ontology) | drop | — |
| `92a56254` | docs(openspec): check off B2 | drop | — |
| `8f347b23` | merge B1 | merge | — |
| `a326c317` | test(memory): virgin-HOME test independent of agents | **keep** | `d2ba1041` |
| `5f4871c2` | fix(ontology): review round 1 | drop | — |
| `6938f4b6` | test(sync): backup failure deterministic | **keep** | `0e8c0685` |
| `a6e78d3c` | test(sync): remote backup failure | **keep** | `2360ec99` |
| `98b58f7b` | merge B2 | merge | — |
| `d383f3f7` | feat(context): concept sidecar, migration v49 | drop | — |
| `e3560892` | feat(context): concept lifecycle, OKF import | drop | — |
| `30d6bce4` | feat(context): replicate concept events | drop | — |
| `cf2abf81` | feat(memory): winddown/concept CLI + `memory_winddown` | drop | — |
| `74e5db44` | docs(context): concept memory + OKF evidence | drop | — |
| `08adfbb1` | docs(openspec): check off B3 | drop | — |
| `e1560f2d` | test(context): deselect live markers | **skip** — plan said "edit"; its entire content is `live_ontology`/`live_concepts` marker hygiene for `test_okf_import_live.py` etc., none of which exist on `main`; nothing remains after removing OKF references | — |
| `790eff34` | test(context): pin v49 receipt | drop | — |
| `f7818a9e` | merge B3 | merge | — |
| `36002102` | test(mcp): pin pre-planner session_search output | **keep** | `742e291f` |
| `fb33e2ce` | feat(mcp): shared AND-to-OR query planner | **keep** | `51aef6d6` (conflict in `mcp_server.py`: planner loop + `main`'s `include_retired_sources=bool(source) and not is_supported(source)`) |
| `d5731339` | feat(mcp): contract-frozen `memory_recall` | drop | — |
| `48ce4393` | feat(install): register StudyLoop MCP servers | **keep** | `fe98eea5` — the plan's feared `check_ontology_freshness` reference was a *context* line absent on `main`; applied clean, `check_mcp_registration` registered, 4 tests pass |
| `99eb9159` | fix(install): preserve unrelated MCP entry bytes | **keep** | `1bbfbc63` |
| `7f73c111` | test(memory): record B4 recall acceptance | drop | — |
| `4fe2e4cd` | fix(mcp): preserve legacy session search syntax | **keep** | `e0553ecf` (conflict: body re-shaped to this commit's post-image exactly + `main`'s predicate; whole-file diff vs its image shows only `main`'s six-harness docstring and the absent `memory_winddown`/`memory_recall`) |
| `7068ac44` | fix(install): repair arbitrary MCP config shapes | **keep** | `76115d3e` |
| `77f9ab1e` | fix(install): preserve TOML multiline strings | **keep** | `4ab13499` |
| `031dbab9` | merge B4 | merge | — |

11 kept, 3 skipped (2 openspec + `e1560f2d`), 13 dropped, 4 merges. Inventory said 14 keep; the delta
is the 3 skips, each with its reason above.

## OKF residue proof

`git grep -ilE 'okf|ontolog|check_ontology|user_version *= *4[89]|memory_winddown|concept_cli' 4ab13499 -- 'packages/*'`
→ two files, **both pre-existing on `main` and benign**: `web/static/vendor/dev/js/ghostty-web-0.4.0.js`
(minified identifier `oKf`) and `tests/e2e/test_journey_new_user_first_plan.py` ("ontology services" as a
learner's study topic in a fixture). `migrations.py` `VERSION = 47`, unchanged. No `memory_winddown`,
no `concept_cli`, no v48/v49 DDL.

## Gates on the integration branch

ruff check clean · ruff format clean (705 files) · pyright 0/0/0 · parity guard 6/6 · full unit
suite both packages: **17 failed, 5,668 passed, 4 skipped, 14 errors** (10 m 39 s). Red node-id set
vs the Stage 3 post-fix pin (30): **+1, −0**.

The +1: `test_fresh_install_scope.py::test_studyloop_study_exits_2_with_the_diagnostic_on_a_virgin_home`
(brought by `a326c317`). Mechanism from the artefact: the CLI exits 1 with "Terminal multiplexer is
required" before reaching the scope diagnostic (exit 2). `tmux` on this machine is a **mise shim**
(`~/.local/share/mise/shims/tmux`) that fails under the test's virgin `HOME` (`mise ERROR error parsing
config file`); the real binary (`~/.local/share/mise/installs/tmux/3.7b/tmux`) works under any HOME.
With the real tmux directory first on PATH the test passes and its whole file passes (11/11).
**Environment-dependent, same class as the pinned 30; not a product regression.** It joins the
accounted set for Stage 10 with this mechanism.

## DEV re-score — and a correction to the plan's premise

The plan gate was "re-score the shipped arm on gold DEV; expect ≥ +0.14 over pinned B0", on the
inventory's statement that `fb33e2ce` is "the +0.142 established win". **That attribution is wrong**,
read against the ADR and the look-2 arm:

- ADR-0011:311: "Look 2 attributed most of that to the shipped AND-first planner (**F-B0-1**: +0.142 of
  it). Fixing the planner in agent-session-tools is the actionable outcome."
- `council-stage-d-looks.md`: "The shipped AND-first query form is too strict independent of crashing
  … F-B0-1 is thereby a *measured defect* in the shipped path worth +0.142."
- `proof_arms.py::B1_planner`: "the SHIPPED index with only the planner replaced … swaps *only* the
  query text for `plan_prose_query(question)`" — the **learning-memory** phrase-token OR planner on
  `feat/knowledge-proof`, not `fb33e2ce`.

So the +0.142 is what you gain by *replacing* `fb33e2ce`'s planner, not by shipping it. The plan
council's Q1/F1 passed the misattribution through; this stage caught it by running the harness.

**Measurement** (`stage4-keep-half-dev-rescore.json`; harness `score.py` via `score_stage4.py`, a
shape-adapter so both arms are scored by exactly the code they ship; same read-only `sessions.db`,
same visibility rules for both arms — the plan council's F1 re-pin, satisfied by pinning B0 at today's
scoped `main` `9235ab79` rather than at `031dbab9`):

| arm | code | macro recall@5 | K / P / R | errors |
|---|---|---|---|---|
| B0 | `main` @ `9235ab79` (scoped, pre-planner `escape_fts_query`) | **0.000** | 0 / 0 / 0 | 42 / 91 |
| B1 | `integrate/pr18-keep-half` @ `4ab13499` | **0.1066** | .182 / .034 / .103 | 42 / 91 |

B1 equals the pinned PR receipt (`baseline-dev-031dbab9.json` B1 = 0.10658307…, identical to 17
digits) — the cherry-pick reproduces PR #18's shipped retrieval path exactly.

`B1_vs_B0`: **+0.107, CI95 [+0.043, +0.182]**, 10,000 cluster-bootstrap draws, 57 clusters.
Non-inferior on macro, K, P, R. **Not "established"** by the ruler (lower bound +0.043 < +0.05).
The plan's ≥ +0.14 was never achievable by this code.

Both arms error on the same 42 questions: `fts5: syntax error near "\`"` ×31, `near "?"` ×8, `no such
column: 9` ×1 — natural-language questions containing backticks, question marks or bare digits crash
the shipped FTS path. **This is F-B0-1's crash half, live on `main` today, and the keep-half does not
fix it.** Provenance note: the harness stamps `candidate_commit` from its own checkout
(`d19e1e21`, the knowledge-proof worktree); the code under test was `4ab13499` as the recorded import
path shows.

Gold scope: 2 of 60 gold sessions are `litellm-proxy` (now hidden); items `A1-13`, `A1-70`, `A1-71`
have no visible gold session and are unwinnable for every arm. Denominator unchanged (91) so numbers
stay comparable with prior receipts; this caps macro recall below 1.0 on the scoped corpus.

## What this means for the merge (question for the council)

The keep-half is OKF-clean, gate-green, and strictly better than `main` on DEV (+0.107, non-inferior
everywhere, B0 is literally zero). It does **not** meet the plan's stated gate, because that gate was
mis-specified. Recommendation: **merge**, with the receipt stating the correct attribution; carry two
new items to the hand-off — (1) the 42/91 FTS-syntax crash on `main`'s shipped search (F-B0-1 crash
half), (2) the learning-memory phrase-token OR planner as the *actual* +0.142 lever, which lives on
`feat/knowledge-proof` and is part of the semantic-layer work, not this plan.
