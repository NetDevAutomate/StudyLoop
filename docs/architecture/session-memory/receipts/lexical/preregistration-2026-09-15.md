# §5 lexical OR-fallback — pre-registration (2026-09-15)

**Frozen before any measurement run.** Branch `feat/lexical-or-fallback` off `main` `a0272a52`
(the SEALED-outcome commit); RED tests at `90964e9c`
(`packages/agent-session-tools/tests/test_query_planner_or_fallback.py`). Written under
council decision D-12 (`docs/architecture/plan-integration/council/arbitration-plan-round1-2026-09-15.md`)
and design §7 (`openspec/changes/plan-application-seam/design.md`). Changing anything in this file
after the run is a new pre-registration, not an edit.

## Hypothesis

The archived `feat/knowledge-proof` branch's `plan_prose_query` — every raw whitespace token of the
question quoted (embedded `"` doubled, Unicode `Cc`/`Cs` characters stripped, tokens with no
alphanumeric dropped) and joined with `OR`; **no stop list, no length filter** — produced the
historical +0.142 (DEV) / +0.168 recall@5 lifts against the *Stage 1* shipped planner
(`council-stage4-2026-09-10.md`, F-B0-1). Those numbers were measured against a different store, a
different corpus and a planner that has since been replaced (Stage 2), so they are **prioritisation
evidence, not confirmation** (D-12). The question here is whether the same construction helps the
*current* shipped planner when used in its narrowest possible position.

## Candidate — Grok's narrow form (D-12), stated exactly

The shipped natural-language planner at `a0272a52` is `retrieval.plan_natural_language`
(`packages/agent-session-tools/src/agent_session_tools/retrieval.py`): double-quoted spans are
lifted as phrase terms; the remainder is tokenised by `query_planner._terms` (`[a-zA-Z0-9_./-]+`,
lower-cased, the 62-word `STOP` set and `len(token) <= 2` dropped); every term is quoted; the
`MATCH` strings tried are `AND`-joined first, then — only when the `AND` form returns zero rows —
`OR`-joined (the *widen* step). `retrieval.plan_query` stands in front: the `fts:` prefix or an
uppercase `AND|OR|NOT|NEAR` outside every double-quoted span is explicit FTS5, passed through
verbatim, never planned. (`query_planner.plan` carries the same AND/OR construction as a pure
function without phrase handling; nothing on the serving path calls it today.)

The candidate `and_then_prose_or` changes **one thing**: the widen string. Instead of the OR of the
*filtered* quoted terms, it is `query_planner.prose_or_query(<raw question>)` — the branch
function's output over the whole raw text. Everything else is unchanged and this is binding:

- the `AND` arm, its `STOP` set and its `len(token) > 2` filter stay exactly as shipped;
- the widen still runs **only** when the `AND` arm returned zero rows;
- a question with **no content terms** (e.g. `what is the?`) still returns `plan="none"` and is not
  searched — the widen step is never reached without an `AND` arm in front of it;
- the shipped de-duplication stays: when the widen string equals the `AND` string only one query
  is tried;
- the explicit door stays in front and is **never** reached by the candidate (S.1 tests
  `test_explicit_fts_prefix_is_verbatim`, `test_uppercase_operator_outside_quotes_is_verbatim`,
  `test_quoted_operator_is_not_explicit`);
- `retrieval_status.terms` keeps reporting the `AND` arm's content terms; `queries` lists what was
  actually tried, so a reader can see the widen string.

## Corpus

| item | value |
|---|---|
| Live database | `~/.config/studyloop/sessions.db` — 912,318,464 bytes, mtime 2026-09-15T19:18:50+01:00, sha256 `d164906e560586da72d52fb26ff7748d43fa7e635064d83e334e351423bcf5c7` (main file only; the database is in WAL mode with a live 54,664,192-byte `-wal` still receiving other agents' session exports, so the main file's digest alone does not name the readable corpus) |
| **Measured corpus** | a snapshot clone `~/.local/share/studyloop/eval-clones/lexical-or-fallback-20260915/sessions.db`, taken 2026-09-15 ≈21:25 BST by `VACUUM INTO` from a `file:…?mode=ro` connection (main + WAL, one consistent read), `chmod 0444` — 901,582,848 bytes, sha256 `53b881b040555a45dcf6e83892e7e31f12f52dd839d25b1eda7b5f762bee4db5`, `journal_mode=delete`, `user_version=48` |
| Harness fingerprint (`eval.receipt.db_fingerprint`) | `469824ce96f5877bdc70b2b69a9d5a23f80509bcfb3963a1a4d92a65f910290c` — identical for the clone and the live database at snapshot time |
| Visibility (`eval.receipt.resolved_visibility`) | admitted sources `claude_code, codex, grok, kiro_cli, opencode, pi, study_mentor`; visible 2,205 of 2,205 sessions; 62,267 messages; `message_embeddings` 42,191 rows pinned to `bge-small-en-v1.5` (irrelevant here — every arm runs lexical) |

Why a clone rather than the live path: the live file is being written to during this window
(parallel agents export sessions), and five arms must see one corpus for the paired comparison to
be paired. The clone *is* the live corpus at one instant; both digests are recorded so either can
be checked. Every arm opens it read-only (`?mode=ro`), as the harness always has.

**Ceiling, a property of this corpus and not of any arm.** The live database is the *hot* tier
(`docs/session-db-tiering.md`); sessions have been pruned to the full tier since the gold set was
built (Stage 4 saw 5,880 sessions; the SEALED clone this morning had 2,173). In this snapshot only
**61 of 91** DEV items have at least one `gold_session_id` present in `sessions` — K 22/33,
P 18/29, R 21/29. The other 30 (`A1-6 A1-13 A1-37 A1-49 A1-63 A1-70 A1-71 A1-76 A1-77 A1-81 A1-85
A1-88 A1-89 A1-106 A2-1 A2-8 A2-13 A2-25 A2-33 A2-38 A2-40 A2-41 A2-48 A2-56 A3-3 A3-10 A3-20
A3-21 A3-31 A3-41`) are unwinnable by every arm and **stay in the denominator** (freeze rule: the
ruler is not shrunk). Paired deltas on them are exactly zero; the effect is on power, not on sign.

## Gold

`docs/architecture/session-memory/receipts/gold-v2-dev.json` — sha256
`5632cd2b02a77dbd95ded3fae3aa32fa1599cd43929f43e44aa132343c3c6098`, 58,842 bytes, `gold_version`
v2, set DEV, **91 items**, 57 clusters, strata K 33 / P 29 / R 29, 4 items with more than one gold
session. The SEALED set is **not** used: it was spent on 2026-09-15 (`stage5-sealed-bge-gold.json`)
and D-12 rejects re-running it. This is a DEV-only measurement and will be labelled as such.

## Arms — planner variants, orthogonal to the transport arms

All five run through the **`mcp` transport arm** (`eval.arms.McpArm`: the real `session_search`
tool via FastMCP `call_tool`, `STUDYLOOP_RETRIEVAL_MODE=lexical`, `rows=10` message rows before
the collapse to sessions, `k=5`), so the only thing that differs between arms is the natural-
language planner. The variant is applied by substituting `retrieval.plan_natural_language` for
the duration of the arm's call — after `plan_query` has classified the string, so the explicit
door is identical in all five. Arm names in the receipt are `mcp:<planner>`; `mcp` alone is the
shipped planner.

| arm | `MATCH` strings tried, in order | tokens |
|---|---|---|
| `shipped` (`mcp`) | `AND` of filtered quoted terms → `OR` of the same | phrases + `_terms` (STOP, len>2) |
| `or_first_filtered` | `OR` of filtered quoted terms, alone | phrases + `_terms` |
| `and_first_unfiltered` | `AND` of every raw token quoted → `OR` of the same | `prose_or_query` tokenisation (no STOP, no length filter) |
| `or_only_unfiltered` | `prose_or_query(raw)` alone — the branch function as it was | raw tokens |
| **`and_then_prose_or`** (candidate) | shipped `AND` → `prose_or_query(raw)` | AND: filtered; widen: raw |

For the two unfiltered arms a question whose raw tokenisation is empty (punctuation only) is
`plan="none"`, mirroring the shipped no-content-terms return.

## Metrics and inference

- **Primary:** macro recall@5 over K/P/R (`eval.metrics.recall_at_k`, hit = any gold session in the
  first 5 distinct sessions).
- **Guardrails (reported, and clause 2 below):** precision@5 = |gold sessions ∩ first 5 distinct
  sessions returned| / 5 per item, macro-averaged over strata exactly like recall (the denominator
  is 5 even when fewer sessions come back — an empty result is precision 0, not undefined);
  MRR@5 macro (`eval.metrics.mrr_at_k`).
- **Also reported:** crashes by `ArmError` kind (a crash is a miss in the denominator); latency
  p50/p95 per arm (reported, never compared).
- **Inference:** paired **cluster** bootstrap, cluster = gold `cluster` (57), **10,000** resamples,
  seed **20260910**, percentile CI95 — the frozen Stage 1 ruler (`eval/__init__.py`: `RESAMPLES`,
  `SEED`). Recall uses the existing `eval.metrics.cluster_bootstrap`; precision and MRR use the same
  resampling over per-item values. The K-stratum non-inferiority entry the `gold` subcommand
  already emits is recorded for every pair.
- Every ordered pair of the five arms is compared; the pair that decides is
  **`mcp:and_then_prose_or` vs `mcp`**.

## Adopt rule — frozen

Adopt `and_then_prose_or` (S.4: one commit swapping only the widen string in
`retrieval.plan_natural_language` and `query_planner.plan`, plus a new golden for the widen path)
**if and only if all four hold**:

1. DEV macro recall@5 paired-bootstrap delta (`and_then_prose_or − shipped`) has **CI95 lower bound
   > 0** (strictly). *Note:* this is weaker than the programme's "established lift" (lower bound
   ≥ +0.05); D-12 chose it and it is recorded as such — the receipt reports both.
2. Macro precision@5 drop (`shipped − and_then_prose_or`, point estimate) **≤ 0.05 absolute**.
3. The explicit-door tests pass on the tree that produced the receipt:
   `test_query_planner_or_fallback.py::test_explicit_fts_prefix_is_verbatim`,
   `::test_uppercase_operator_outside_quotes_is_verbatim`, `::test_quoted_operator_is_not_explicit`.
4. `packages/agent-session-tools/tests/golden/session_search_pre_planner.json` is byte-identical
   to its committed form: sha256 `7152dae40af4918dffd6a51cc4b7d399c433384a3caa9a7ca64164e7a56795f6`
   (`::test_pre_planner_golden_unchanged`).

Anything else — including "the lift is positive but the interval touches zero", "crashes appeared",
or "a different arm won" — is **reject**: the shipped planner is left alone, the helper and its
tests stay as measured code, and the receipt records the numbers. No threshold is revisited after
seeing the numbers; a different arm that looks better is a *new* hypothesis for a new
pre-registration, not an adoption under this one.

## How the run is made and what it leaves behind

```
# one run, five arms, one clone, one receipt (raw, outside the repo)
uv run --group dev python -m agent_session_tools.eval gold \
  --db ~/.local/share/studyloop/eval-clones/lexical-or-fallback-20260915/sessions.db \
  --arms mcp,mcp:or_first_filtered,mcp:and_first_unfiltered,mcp:or_only_unfiltered,mcp:and_then_prose_or \
  --rows 10 --k 5 \
  --out ~/.local/share/studyloop/eval-clones/lexical-or-fallback-20260915/or-fallback-dev-2026-09-15.raw.json

# the verdict is computed from the receipt by code, not read off by eye
uv run --group dev python -m agent_session_tools.eval lexical-verdict \
  --receipt ~/.local/share/studyloop/eval-clones/lexical-or-fallback-20260915/or-fallback-dev-2026-09-15.raw.json \
  --candidate mcp:and_then_prose_or --control mcp \
  --out docs/architecture/session-memory/receipts/lexical/or-fallback-dev-2026-09-15.json
```

- The committed receipt `receipts/lexical/or-fallback-dev-2026-09-15.json` carries every per-arm
  metric block, every per-item row (`ranked`, `hit`, `rr`, `rank`, `error_kind`, latency) and every
  comparison from the raw receipt, plus a `verdict` block naming each clause and its truth value.
  Digests inside it are written in `sha256:<hex>` notation and the commit as `git:<sha>`: the
  repository's `detect-secrets` hook flags any bare quoted hex string (a 16-character prefix
  included — tested before this was written), and a prefixed digest is both hook-clean and
  verifiable in full. The raw receipt's own sha256 is recorded in the `.md` reading.
- `receipts/lexical/or-fallback-dev-2026-09-15.md` is the reading: the per-arm table, the CI95 for
  the deciding pair, an explicit `adopt: true|false` line and the clause(s) that decided it.
- Numbers in both files come from the commands above and nowhere else. If the harness cannot run
  against the clone, the exact error is recorded and the stream stops; nothing is estimated.

## Not measured here, said up front

- SEALED confirmation: spent; not available (D-12).
- Learner benefit: a ranking measurement says nothing about learning (D-16 wording applies).
- The `hybrid` mode: the candidate changes the lexical arm only; a fused effect is out of scope.
- The 91-item ruler at a 61-item ceiling has wide intervals; a null result here is "not
  established on DEV", not "no effect".
