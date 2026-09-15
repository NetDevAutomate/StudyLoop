# §5 lexical OR-fallback — DEV measurement receipt (2026-09-15)

**Verdict: reject.** The pre-registered candidate `and_then_prose_or` (the shipped `AND` arm with
`prose_or_query(raw)` as its widen string) did **not** lift DEV macro recall@5 over the shipped
planner: paired delta **−0.0101**, CI95 **[−0.0500, +0.0278]**. Clause 1 of the frozen adopt rule
fails; the other three hold. The shipped planner is left alone (S.4 not applied); the helper
`query_planner.prose_or_query` and its tests stay as measured code.

```
adopt: false
```

Rule: `receipts/lexical/preregistration-2026-09-15.md` — frozen before this run, unchanged after it.
This is a **DEV-only** measurement (the SEALED set was spent on 2026-09-15; D-12). Every number
below is copied from `receipts/lexical/or-fallback-dev-2026-09-15.json`, which the
`lexical-verdict` subcommand derived from the raw gold receipt; nothing here was estimated or
computed by hand.

## What was run

| item | value |
|---|---|
| Tree | `git rev-parse HEAD` = `ed6281b4818bdec9e92fc461ffd006d95f090127` (branch `feat/lexical-or-fallback`, clean) — recorded in the receipt as `git_commit` |
| Measured corpus | `~/.local/share/studyloop/eval-clones/lexical-or-fallback-20260915/sessions.db` — **901,582,848 bytes**, sha256 `53b881b040555a45dcf6e83892e7e31f12f52dd839d25b1eda7b5f762bee4db5`, mode `0444`, `journal_mode=delete`, `user_version=48`, 2,205 sessions, 62,267 messages. This is the clone the pre-registration names, digest for digest; it was verified in place, not re-made, because re-cloning the live database (still receiving other agents' exports) would have produced a corpus the pre-registration does not name. |
| Harness fingerprint (`db.fingerprint`) | `469824ce96f5877bdc70b2b69a9d5a23f80509bcfb3963a1a4d92a65f910290c` — equal to the pre-registered value |
| Visibility | admitted `claude_code, codex, grok, kiro_cli, opencode, pi, study_mentor`; visible 2,205 of 2,205 sessions |
| Gold | `receipts/gold-v2-dev.json`, sha256 `5632cd2b02a77dbd95ded3fae3aa32fa1599cd43929f43e44aa132343c3c6098`, 91 items, 57 clusters, strata K 33 / P 29 / R 29, set DEV, `gold_version` v2 |
| Arms | `mcp`, `mcp:or_first_filtered`, `mcp:and_first_unfiltered`, `mcp:or_only_unfiltered`, `mcp:and_then_prose_or` — all through the `mcp` transport (`STUDYLOOP_RETRIEVAL_MODE=lexical`, `rows=10`, `k=5`) |
| Inference | paired cluster bootstrap, 57 clusters, 10,000 resamples, seed 20260910, percentile CI95 |
| Gold run | `created_utc` 2026-09-15T21:08:06+00:00, exit 0; `metrics_sha256` `b58861fadeb87dfa63a931bb3c413098b045fd6fbbbb378a624125bed64d132d` |
| Raw receipt (outside the repo) | `~/.local/share/studyloop/eval-clones/lexical-or-fallback-20260915/or-fallback-dev-2026-09-15.raw.json` — 293,937 bytes, sha256 `6b8c18095850e1cd253129af6d143a2be1b9407ce6938533117d4bd3e447b57d` (also recorded inside the committed receipt as `derived_from.raw_sha256`) |
| Committed receipt | `receipts/lexical/or-fallback-dev-2026-09-15.json` — the raw receipt with digests in `sha256:<hex>` / `git:<sha>` notation plus the `verdict` block |
| Reproducibility | an earlier gold run at the same tree against the same clone (2026-09-15T20:49:40+00:00, left uncommitted by the previous agent and kept beside the raw receipt as `*.raw.prev-agent-2049Z.json`) has the identical `metrics_sha256` `b58861fa…`; the stable view reproduced byte for byte |

The two commands were exactly those in the pre-registration's "How the run is made" block.

## Per-arm results (DEV, k=5, 91 items, 61-item ceiling)

| arm | macro recall@5 | K | P | R | macro precision@5 | macro MRR@5 | crashes | p50 ms | p95 ms |
|---|---|---|---|---|---|---|---|---|---|
| `mcp` (shipped) | **0.1700** | 0.303 (10/33) | 0.034 (1/29) | 0.172 (5/29) | 0.0363 | 0.1407 | 0/91 | 17.8 | 59.2 |
| `mcp:or_first_filtered` | 0.2274 | 0.303 (10/33) | 0.138 (4/29) | 0.241 (7/29) | 0.0478 | 0.1849 | 0/91 | 42.5 | 71.2 |
| `mcp:and_first_unfiltered` | 0.1411 | 0.182 (6/33) | 0.069 (2/29) | 0.172 (5/29) | 0.0305 | 0.1277 | 0/91 | 20.7 | 150.2 |
| `mcp:or_only_unfiltered` | 0.2274 | 0.303 (10/33) | 0.138 (4/29) | 0.241 (7/29) | 0.0478 | 0.1840 | 0/91 | 136.7 | 157.6 |
| **`mcp:and_then_prose_or`** (candidate) | **0.1599** | 0.273 (9/33) | 0.034 (1/29) | 0.172 (5/29) | 0.0343 | 0.1465 | 0/91 | 17.9 | 150.5 |

No arm crashed on any item (`errors_by_kind` is empty for all five). Latency is reported, never
compared. Full-precision values are in the JSON (`arms.<name>.metrics`).

## The deciding pair — `mcp:and_then_prose_or` vs `mcp` (candidate − control)

| metric | point | CI95 | reading |
|---|---|---|---|
| macro recall@5 | −0.010101010101010102 | [−0.049955791335101675, +0.027777777777777776] | lower bound not > 0; `established` (≥ +0.05) false |
| macro precision@5 | −0.00202020202020202 | [−0.009991158267020338, +0.005555555555555556] | `lower_above_zero` false |
| macro MRR@5 | +0.005741321258562637 | [−0.012448559670781893, +0.033169934640522876] | `lower_above_zero` false |
| K-stratum non-inferiority (`_K`) | −0.030303030303030304 | lower −0.09090909090909091, upper 0.0 | `non_inferior` false at margin 0.0; `upper_at_least_zero` true |

What moved, from the per-item rows: the candidate's ranked list differs from the shipped one on
**30 of 91** items (a list can only differ where the shipped `AND` arm returned nothing and the
widen ran) and is identical on the other 61. Hits changed on four: gained `A1-75` (R, rank 3); lost
`A2-11` (K, was rank 3) and `A3-33` (R, was rank 5); `A1-46` (K) rose from rank 4 to rank 1 (a hit
either way — the main source of the small MRR gain). Net: K −1 item, P 0, R 0 → macro −0.0101.

## Adopt rule — the four frozen clauses

| # | clause | result | the number that decided it |
|---|---|---|---|
| 1 | DEV macro recall@5 paired delta (candidate − shipped) has CI95 lower bound **> 0** | **FAIL** | lower bound **−0.049955791335101675** (point −0.0101; 10,000 resamples, seed 20260910, 57 clusters). The programme's stronger "established lift" (lower bound ≥ +0.05) is also false. |
| 2 | macro precision@5 drop (shipped − candidate) ≤ 0.05 absolute | PASS | drop **0.0020202020202020193** (control 0.03629397422500871, candidate 0.03427377220480669) |
| 3 | explicit-door tests pass on the tree that produced the receipt | PASS | `fts_prefix_is_verbatim` true, `uppercase_operator_outside_quotes_is_verbatim` true, `quoted_operator_is_not_explicit` true (re-evaluated by `eval.lexical.explicit_door_holds` on the live planner) |
| 4 | `tests/golden/session_search_pre_planner.json` byte-identical to its committed form | PASS | actual `sha256:7152dae40af4918dffd6a51cc4b7d399c433384a3caa9a7ca64164e7a56795f6` = expected |

`decided_by: 1_recall_ci95_lower_above_zero`. The rule is a conjunction; one failing clause is a
reject.

```
adopt: false
```

## Consequences

- **S.4 is not applied.** `retrieval.plan_natural_language` and `query_planner.plan` keep the shipped
  `OR`-of-filtered-terms widen. No `tests/golden/session_search_or_fallback.json` is created.
- `query_planner.prose_or_query` / `prose_tokens`, the planner-variant arms in `eval/arms.py`, the
  precision@K guardrail, the value bootstrap and the `lexical-verdict` door stay as measured code
  with their tests; they are the harness this receipt was made with, not a shipped behaviour.
- The hypothesis carried from `feat/knowledge-proof` — that the branch's `plan_prose_query`
  construction transfers to the current planner as a widen step — is **not established on DEV**
  against the current store and planner. The historical +0.142 / +0.168 were measured against the
  Stage 1 planner and a different corpus (pre-registration, "Hypothesis"), and did not carry.

## Seen but not adopted, said plainly

The two `OR`-only arms scored higher than the shipped planner on this DEV set: `mcp:or_first_filtered`
vs `mcp` +0.0575, CI95 [−0.0058, +0.1212]; `mcp:or_only_unfiltered` vs `mcp` +0.0575, CI95
[−0.0134, +0.1301]. Both intervals include zero, both are on DEV only, and neither is the
pre-registered candidate. Under the frozen rule "a different arm that looks better is a *new*
hypothesis for a new pre-registration, not an adoption under this one" — so it is recorded here and
nothing else is done with it. For whoever pre-registers it: the same receipt already shows the
precision@5 gain of either `OR`-only arm over the shipped arm is not itself established
(`or_first_filtered` +0.0115, CI95 [−0.0012, +0.0242]; `or_only_unfiltered` +0.0115, CI95
[−0.0027, +0.0260]), and the raw-token form pays for it in latency (p50 136.7 ms against 42.5 ms
filtered and 17.8 ms shipped).

## Not measured here

- SEALED confirmation (spent; D-12).
- Learner benefit — a ranking measurement says nothing about learning (D-16 wording).
- The `hybrid` mode — every arm here ran lexical.
- The 30 DEV items with no gold session in the hot tier stay in the denominator and are unwinnable
  by every arm; the ruler was not shrunk. A null result at this ceiling is "not established on
  DEV", not "no effect".
