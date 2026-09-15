# Council brief — §5 receipt review: the pre-registered OR-fallback measurement and the ADR-0011 amendment

**Date:** 2026-09-15 · **Branch:** `feat/lexical-or-fallback` off `main` @ `a0272a52`; commits `90964e9c`
(RED), `8ebdeb48` (pre-registration, committed BEFORE any run), `cbc4d94c` (helper), `1ce14144` (precision@K +
value bootstrap), `ed6281b4` (planner-variant arms + `lexical-verdict` CLI), `d696bc8a` (measurement receipt,
verdict reject), `4e4a8ae6` (ADR-0011 amendment). **You are one independent seat**; no tools; the brief is the
complete evidence base. Tests on the tree: `test_query_planner_or_fallback.py` 13 passed; whole package
2120 passed; ruff + pyright clean.

## 0. What was decided before the run (D-12, arbitration)

Candidate = Grok's narrow form: `plan_prose_query`'s quoted-token OR replaces ONLY the OR-widen construction
inside the shipped AND-then-OR planner, after `retrieval.plan_query` has classified the string as natural
language; the AND arm, STOP set and `len(token) > 2` filter stay; the explicit `fts:`/uppercase door never
reaches it. Five planner arms orthogonal to the transport arms. Primary metric macro recall@5 on the
committed 91-item DEV gold; precision@5 and MRR@5 guardrails; paired cluster bootstrap CI95. Frozen adopt
rule: CI95 lower bound of the recall delta > 0 AND precision@5 drop ≤ 0.05 AND explicit-door tests pass AND
pre-planner golden unchanged. The historical +0.142 (DEV) / +0.168 (SEALED) from the archived branch was
declared prioritisation evidence, not confirmation: it was measured against the old crash-prone AND-first
planner, before `main`'s Stage 2 made the crash class die.

## 1. Pre-registration (binding sections, verbatim)

```markdown
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
…
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
```

## 2. The measurement receipt — human reading (verbatim)

```markdown
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
```

## 3. The verdict code that computed it — `eval/lexical.py`

```python
"""§5 stream (council D-12): the adopt/reject verdict for the prose-OR widen candidate.

The pre-registration (``docs/architecture/session-memory/receipts/lexical/
preregistration-2026-09-15.md``) froze four clauses before any number existed.
This module evaluates them **from a gold receipt**, by code, so the verdict is
a function of the receipt and the tree and not of a reader's eye:

1. the DEV macro recall@K paired-bootstrap delta ``candidate - control`` has a
   CI95 lower bound strictly above zero;
2. the macro precision@K drop ``control - candidate`` is at most
   :data:`PRECISION_DROP_MAX` absolute;
3. the explicit door holds on the tree that produced the receipt -- the same
   three assertions ``tests/test_query_planner_or_fallback.py`` pins, re-run
   here against the live planner;
4. ``tests/golden/session_search_pre_planner.json`` is byte-identical to the
   form committed at ``d060d3f2``.

It also derives the *committed* form of the receipt: the raw gold receipt with
every digest written in ``sha256:<hex>`` notation and the commit as
``git:<sha>``, plus the verdict block. The repository's ``detect-secrets`` hook
flags any bare quoted hex string (a 16-character prefix included), and a
prefixed digest is both hook-clean and checkable in full.
"""

from __future__ import annotations

import copy
import hashlib
from pathlib import Path
from typing import Any

from agent_session_tools.retrieval import QueryPlan, plan_query

from . import K

#: Clause 2's frozen threshold: absolute macro precision@K drop the candidate may cost.
PRECISION_DROP_MAX = 0.05
#: Clause 4's fixture and its committed digest (a content hash of a public file).
PRE_PLANNER_GOLDEN_RELATIVE = Path(
    "packages/agent-session-tools/tests/golden/session_search_pre_planner.json"
)
PRE_PLANNER_GOLDEN_SHA256 = "7152dae40af4918dffd6a51cc4b7d399c433384a3caa9a7ca64164e7a56795f6"  # pragma: allowlist secret
#: Where the rule these clauses implement is written down.
RULE = "docs/architecture/session-memory/receipts/lexical/preregistration-2026-09-15.md"
DEFAULT_CANDIDATE = "mcp:and_then_prose_or"
DEFAULT_CONTROL = "mcp"

#: Receipt keys whose values are bare hex digests in the raw gold receipt.
_SHA256_KEYS = frozenset({"sha256", "fingerprint", "metrics_sha256"})
_GIT_KEYS = frozenset({"git_commit"})


def repo_root() -> Path:
    return Path(__file__).resolve().parents[5]


def explicit_door_holds() -> dict[str, bool]:
    """Clause 3, re-evaluated on the live planner: the three S.1 explicit-door assertions."""
    prefixed = plan_query("fts:error OR authentication")
    return {
        "fts_prefix_is_verbatim": prefixed
        == QueryPlan(explicit=True, terms=(), queries=("error OR authentication",)),
        "uppercase_operator_outside_quotes_is_verbatim": (
            plan_query("error OR authentication").explicit
            and plan_query('"exact phrase" OR authentication').explicit
            and plan_query("error OR authentication").queries
            == ("error OR authentication",)
        ),
        "quoted_operator_is_not_explicit": (
            not plan_query('"error OR warning" recovery').explicit
            and not plan_query('"error or warning" recovery').explicit
        ),
    }


def golden_sha256(root: Path | None = None) -> str:
    """The current digest of the pre-planner golden under ``root``."""
    path = (root or repo_root()) / PRE_PLANNER_GOLDEN_RELATIVE
    return hashlib.sha256(path.read_bytes()).hexdigest()


def judge(
    receipt: dict[str, Any],
    *,
    candidate: str = DEFAULT_CANDIDATE,
    control: str = DEFAULT_CONTROL,
    k: int = K,
    root: Path | None = None,
) -> dict[str, Any]:
    """Evaluate the four frozen clauses against ``receipt``; never adopts on a missing arm.

    ``decided_by`` names every clause that failed (the rule is a conjunction,
    so any one of them decides a reject); on an adopt it says so explicitly.
    """
    arms = receipt["arms"]
    for name in (candidate, control):
        if name not in arms:
            raise KeyError(
                f"arm {name!r} is not in the receipt; present: {sorted(arms)}"
            )
    recall = receipt["comparisons"][f"{candidate}_vs_{control}"]
    precision_key = f"precision@{k}"
    candidate_precision = float(arms[candidate]["metrics"][precision_key]["macro"])
    control_precision = float(arms[control]["metrics"][precision_key]["macro"])
    drop = control_precision - candidate_precision
    door = explicit_door_holds()
    current_golden = golden_sha256(root)
    clauses: dict[str, dict[str, Any]] = {
        "1_recall_ci95_lower_above_zero": {
            "holds": float(recall["ci95"][0]) > 0.0,
            "point": recall["point"],
            "ci95": list(recall["ci95"]),
            "resamples": recall["resamples"],
            "seed": recall["seed"],
            "clusters": recall["clusters"],
            # The programme's stronger rule, reported beside D-12's weaker one.
            "established_lift_at_min_lift": recall.get("established"),
        },
        "2_precision_drop_at_most_0.05": {
            "holds": drop <= PRECISION_DROP_MAX,
            "control": control_precision,
            "candidate": candidate_precision,
            "drop": drop,
            "max_drop": PRECISION_DROP_MAX,
        },
        "3_explicit_door_tests_pass": {"holds": all(door.values()), **door},
        "4_pre_planner_golden_unchanged": {
            "holds": current_golden == PRE_PLANNER_GOLDEN_SHA256,
            "expected": f"sha256:{PRE_PLANNER_GOLDEN_SHA256}",
            "actual": f"sha256:{current_golden}",
        },
    }
    failed = [name for name, clause in clauses.items() if not clause["holds"]]
    adopt = not failed
    return {
        "adopt": adopt,
        "candidate": candidate,
        "control": control,
        "k": k,
        "rule": RULE,
        "clauses": clauses,
        "decided_by": failed or ["all four clauses hold"],
    }


def prefix_digests(value: Any) -> Any:
    """Rewrite bare hex digests as ``sha256:<hex>`` / ``git:<sha>``, recursively.

    Idempotent: a value that already carries its prefix is left alone, so the
    derivation can be re-run over its own output.
    """
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, inner in value.items():
            if key in _SHA256_KEYS and isinstance(inner, str) and inner:
                out[key] = inner if inner.startswith("sha256:") else f"sha256:{inner}"
            elif key in _GIT_KEYS and isinstance(inner, str) and inner:
                out[key] = inner if inner.startswith("git:") else f"git:{inner}"
            else:
                out[key] = prefix_digests(inner)
        return out
    if isinstance(value, list):
        return [prefix_digests(inner) for inner in value]
    return value


def derive_receipt(
    raw: dict[str, Any], raw_bytes: bytes, verdict: dict[str, Any], *, raw_path: str
) -> dict[str, Any]:
    """The committed receipt: the raw one, digests prefixed, plus the verdict.

    ``metrics_sha256`` keeps the raw receipt's value (it is the digest of the
    raw stable view, and stays checkable against the raw file named in
    ``derived_from``); the derived document does not claim a digest of itself.
    """
    out = prefix_digests(copy.deepcopy(raw))
    out["derived_from"] = {
        "raw_receipt": raw_path,
        "raw_sha256": f"sha256:{hashlib.sha256(raw_bytes).hexdigest()}",
        "digest_notation": "sha256:<hex> for content digests, git:<sha> for commits; "
        "values are otherwise byte-for-byte the raw receipt's",
    }
    out["verdict"] = verdict
    return out


def format_verdict(verdict: dict[str, Any]) -> str:
    """The console reading of a verdict, one clause per line, ``adopt:`` last."""
    lines = [
        f"rule: {verdict['rule']}",
        f"pair: {verdict['candidate']} vs {verdict['control']}",
    ]
    for name, clause in verdict["clauses"].items():
        detail = {key: value for key, value in clause.items() if key != "holds"}
        lines.append(f"  {name}: {'HOLDS' if clause['holds'] else 'FAILS'}  {detail}")
    lines.append(f"decided_by: {', '.join(verdict['decided_by'])}")
    lines.append(f"adopt: {'true' if verdict['adopt'] else 'false'}")
    return "\n".join(lines)


__all__ = [
    "DEFAULT_CANDIDATE",
    "DEFAULT_CONTROL",
    "PRECISION_DROP_MAX",
    "PRE_PLANNER_GOLDEN_RELATIVE",
    "PRE_PLANNER_GOLDEN_SHA256",
    "RULE",
    "derive_receipt",
    "explicit_door_holds",
    "format_verdict",
    "golden_sha256",
    "judge",
    "prefix_digests",
    "repo_root",
]
```

## 4. The planner-variant arms — `eval/arms.py` diff

```diff
diff --git a/packages/agent-session-tools/src/agent_session_tools/eval/arms.py b/packages/agent-session-tools/src/agent_session_tools/eval/arms.py
index a9577800..2dee8222 100644
--- a/packages/agent-session-tools/src/agent_session_tools/eval/arms.py
+++ b/packages/agent-session-tools/src/agent_session_tools/eval/arms.py
@@ -13,6 +13,14 @@
   from the shipped planner while stage 1 still shipped; the live planner has
   since changed by design, so an equality test against it would now fail for
   the right reason and prove nothing.
+
+A second, orthogonal axis (§5 stream, council D-12) is the **planner
+variant**: which natural-language planner the retrieval service runs behind
+the same tool. ``mcp:and_then_prose_or`` is the real ``session_search`` with
+one planner function substituted for the duration of the call, after
+``plan_query`` has classified the string, so the explicit door is identical
+across variants. Variants are in-process by construction (a substituted
+function), so the subprocess CLI arm and the frozen control refuse one.
 """

 from __future__ import annotations
@@ -27,14 +35,23 @@ import sqlite3
 import subprocess
 import sys
 from concurrent.futures import ThreadPoolExecutor
-from contextlib import contextmanager, suppress
+from contextlib import contextmanager, nullcontext, suppress
 from pathlib import Path
 from typing import TYPE_CHECKING, Any

+from agent_session_tools import retrieval
+from agent_session_tools.query_planner import (
+    _quote_term,
+    _terms,
+    prose_or_query,
+    prose_tokens,
+)
+from agent_session_tools.retrieval import QueryPlan, _phrase_terms
+
 from .seam import ArmError, classify_failure, collapse_to_sessions

 if TYPE_CHECKING:
-    from collections.abc import Coroutine, Iterator, Sequence
+    from collections.abc import Callable, Coroutine, Iterator, Sequence

     from .seam import Hit, Query

@@ -42,6 +59,138 @@ if TYPE_CHECKING:
 DEFAULT_ROWS = 10


+# --------------------------------------------------------------------------- planner variants (§5)
+# The shipped natural-language planner, captured at import. The variants below
+# replace ``retrieval.plan_natural_language`` for the duration of one tool call,
+# so the candidate must build on THIS reference, never on the module attribute
+# it is temporarily standing in for.
+_SHIPPED_PLAN_NATURAL_LANGUAGE = retrieval.plan_natural_language
+
+PLANNER_SHIPPED = "shipped"
+PLANNER_OR_FIRST_FILTERED = "or_first_filtered"
+PLANNER_AND_FIRST_UNFILTERED = "and_first_unfiltered"
+PLANNER_OR_ONLY_UNFILTERED = "or_only_unfiltered"
+PLANNER_AND_THEN_PROSE_OR = "and_then_prose_or"
+
+_NO_CONTENT_TERMS_NOTE = (
+    "the query has no content terms once stop words and tokens shorter "
+    "than three characters are removed; nothing was searched"
+)
+_NO_RAW_TOKENS_NOTE = (
+    "the query has no token carrying an alphanumeric character; nothing was searched"
+)
+
+
+def _empty_plan(note: str) -> QueryPlan:
+    return QueryPlan(explicit=False, terms=(), queries=(), note=note)
+
+
+def _filtered(query: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
+    """The shipped planner's terms and their quoted forms: phrases, then ``_terms``."""
+    phrases, remainder = _phrase_terms(query.strip())
+    terms = (*phrases, *_terms(remainder))
+    quoted = tuple(t if t.startswith('"') else _quote_term(t) for t in terms)
+    return terms, quoted
+
+
+def _unfiltered(query: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
+    """The candidate's tokenisation: every raw token, quoted the FTS5 way."""
+    tokens = prose_tokens(query)
+    return tokens, tuple('"' + t.replace('"', '""') + '"' for t in tokens)
+
+
+def _and_then_or(
+    terms: tuple[str, ...], quoted: tuple[str, ...], note: str
+) -> QueryPlan:
+    if not terms:
+        return _empty_plan(note)
+    and_query, or_query = " AND ".join(quoted), " OR ".join(quoted)
+    queries = (and_query,) if and_query == or_query else (and_query, or_query)
+    return QueryPlan(explicit=False, terms=terms, queries=queries)
+
+
+def plan_or_first_filtered(query: str) -> QueryPlan:
+    """Arm 2: the shipped OR form alone -- filtered terms, no AND pass first."""
+    terms, quoted = _filtered(query)
+    if not terms:
+        return _empty_plan(_NO_CONTENT_TERMS_NOTE)
+    return QueryPlan(explicit=False, terms=terms, queries=(" OR ".join(quoted),))
+
+
+def plan_and_first_unfiltered(query: str) -> QueryPlan:
+    """Arm 3: AND of every raw token, widened to OR of the same -- no stop list."""
+    terms, quoted = _unfiltered(query)
+    return _and_then_or(terms, quoted, _NO_RAW_TOKENS_NOTE)
+
+
+def plan_or_only_unfiltered(query: str) -> QueryPlan:
+    """Arm 4: the archived branch's ``plan_prose_query`` exactly as it stood."""
+    terms, _quoted = _unfiltered(query)
+    if not terms:
+        return _empty_plan(_NO_RAW_TOKENS_NOTE)
+    return QueryPlan(explicit=False, terms=terms, queries=(prose_or_query(query),))
+
+
+def plan_and_then_prose_or(query: str) -> QueryPlan:
+    """Arm 5, the candidate: the shipped AND arm, then the prose-OR as the widen.
+
+    Everything but the widen string is the shipped plan: its terms (STOP set,
+    ``len > 2``), its no-content-terms return (the widen is never reached
+    without an AND arm in front of it) and its de-duplication when the two
+    strings coincide.
+    """
+    shipped = _SHIPPED_PLAN_NATURAL_LANGUAGE(query)
+    if not shipped.terms:
+        return shipped
+    and_query = shipped.queries[0]
+    widen = prose_or_query(query)
+    queries = (and_query,) if not widen or widen == and_query else (and_query, widen)
+    return QueryPlan(
+        explicit=False, terms=shipped.terms, queries=queries, note=shipped.note
+    )
+
+
+#: Planner name -> the function that stands in for ``retrieval.plan_natural_language``
+#: (``None`` = the shipped planner, nothing substituted).
+PLANNERS: dict[str, Callable[[str], QueryPlan] | None] = {
+    PLANNER_SHIPPED: None,
+    PLANNER_OR_FIRST_FILTERED: plan_or_first_filtered,
+    PLANNER_AND_FIRST_UNFILTERED: plan_and_first_unfiltered,
+    PLANNER_OR_ONLY_UNFILTERED: plan_or_only_unfiltered,
+    PLANNER_AND_THEN_PROSE_OR: plan_and_then_prose_or,
+}
+
+#: Where the substitution lands: the one entry into natural-language planning.
+_PLANNER_ENTRY = "agent_session_tools.retrieval.plan_natural_language"
+
+
+def _planner_context(planner: str) -> Any:
+    """A context that runs the service under ``planner``; a no-op for the shipped one."""
+    variant = PLANNERS[planner]
+    if variant is None:
+        return nullcontext()
+    from unittest.mock import patch
+
+    return patch(_PLANNER_ENTRY, variant)
+
+
+def _validate_planner(planner: str) -> str:
+    if planner not in PLANNERS:
+        raise ValueError(f"unknown planner {planner!r}; known: {', '.join(PLANNERS)}")
+    return planner
+
+
+def _arm_name(transport: str, planner: str) -> str:
+    """``mcp`` for the shipped planner, ``mcp:<planner>`` for a variant."""
+    return transport if planner == PLANNER_SHIPPED else f"{transport}:{planner}"
+
+
+def split_arm_name(name: str) -> tuple[str, str]:
+    """``"mcp:and_then_prose_or"`` -> ``("mcp", "and_then_prose_or")``; bare -> shipped."""
+    transport, _, planner = name.partition(":")
+    return transport, planner or PLANNER_SHIPPED
+
+
 def _repo_root() -> Path:
     return Path(__file__).resolve().parents[5]

@@ -182,6 +331,11 @@ class McpArm:
     through the real agent interface honest. Against the pre-Stage-2 tool the
     argument is absent, the flag is ``False``, and the ruler filters the
     returned hits instead.
+
+    ``planner`` selects a natural-language planner variant (:data:`PLANNERS`)
+    substituted into the service for the duration of each call; the shipped
+    planner is the default and substitutes nothing. The arm's ``name`` carries
+    the variant (``mcp:and_then_prose_or``) so receipts and comparisons do.
     """

     name = "mcp"
@@ -191,9 +345,16 @@ class McpArm:
     #: Which retrieval mode this arm pins through ``STUDYLOOP_RETRIEVAL_MODE``.
     mode = "lexical"

-    def __init__(self, db_path: Path | str, rows: int = DEFAULT_ROWS) -> None:
+    def __init__(
+        self,
+        db_path: Path | str,
+        rows: int = DEFAULT_ROWS,
+        planner: str = PLANNER_SHIPPED,
+    ) -> None:
         self.db_path = Path(db_path).expanduser()
         self.rows = rows
+        self.planner = _validate_planner(planner)
+        self.name = _arm_name(type(self).name, self.planner)
         self.tool_arguments = _tool_argument_names("session_search")
         self.supports_exclusion = self.EXCLUDE_ARG in self.tool_arguments
         #: ``retrieval_status`` from the most recent call, or ``None``.
@@ -217,6 +378,7 @@ class McpArm:
                 return_value=self.db_path,
             ),
             _quiet_errors(),
+            _planner_context(self.planner),
         ):
             with patch.dict(os.environ, {"STUDYLOOP_RETRIEVAL_MODE": self.mode}):
                 result = _run(mcp_server.mcp.call_tool("session_search", arguments))
@@ -248,6 +410,7 @@ class McpArm:
             "arm": self.name,
             "interface": "fastmcp call_tool(session_search)",
             "mode": self.mode,
+            "planner": self.planner,
             "rows": self.rows,
             "db_path": str(self.db_path),
             "git_commit": _git_head(),
@@ -514,24 +677,50 @@ ARMS = {
     FrozenShippedArm.name: FrozenShippedArm,
 }

+#: The transport arms a planner variant can be applied to: in-process, through
+#: the retrieval service. The CLI is a subprocess and the frozen replica is a
+#: control that must not move, so neither takes one.
+PLANNER_TRANSPORTS = frozenset({McpArm.name, HybridMcpArm.name})
+

 def build_arm(name: str, db_path: Path | str, rows: int = DEFAULT_ROWS) -> Any:
-    """Construct one arm by name."""
+    """Construct one arm by name; ``<transport>:<planner>`` selects a planner variant."""
+    transport, planner = split_arm_name(name)
     try:
-        factory = ARMS[name]
+        factory = ARMS[transport]
     except KeyError:
         raise ValueError(
-            f"unknown arm {name!r}; known: {', '.join(sorted(ARMS))}"
+            f"unknown arm {transport!r}; known: {', '.join(sorted(ARMS))}"
         ) from None
-    return factory(db_path, rows)
+    _validate_planner(planner)
+    if planner == PLANNER_SHIPPED:
+        return factory(db_path, rows)
+    if transport not in PLANNER_TRANSPORTS:
+        raise ValueError(
+            f"arm {transport!r} cannot take a planner variant; planner variants run "
+            f"in-process through the retrieval service ({', '.join(sorted(PLANNER_TRANSPORTS))})"
+        )
+    return factory(db_path, rows, planner=planner)


 __all__ = [
     "ARMS",
     "DEFAULT_ROWS",
+    "PLANNERS",
+    "PLANNER_AND_FIRST_UNFILTERED",
+    "PLANNER_AND_THEN_PROSE_OR",
+    "PLANNER_OR_FIRST_FILTERED",
+    "PLANNER_OR_ONLY_UNFILTERED",
+    "PLANNER_SHIPPED",
+    "PLANNER_TRANSPORTS",
     "CliArm",
     "FrozenShippedArm",
     "McpArm",
     "build_arm",
     "frozen_session_search_queries",
+    "plan_and_first_unfiltered",
+    "plan_and_then_prose_or",
+    "plan_or_first_filtered",
+    "plan_or_only_unfiltered",
+    "split_arm_name",
 ]
```

## 5. The helper — `query_planner.py` diff

```diff
diff --git a/packages/agent-session-tools/src/agent_session_tools/query_planner.py b/packages/agent-session-tools/src/agent_session_tools/query_planner.py
index 8a5efe33..9ed50352 100644
--- a/packages/agent-session-tools/src/agent_session_tools/query_planner.py
+++ b/packages/agent-session-tools/src/agent_session_tools/query_planner.py
@@ -3,6 +3,7 @@
 from __future__ import annotations

 import re
+import unicodedata
 from dataclasses import dataclass

 # Pinned verbatim from SessionWeaver v0.2.0. Keep this string form so changes
@@ -16,6 +17,12 @@ STOP = frozenset(

 _TERM = re.compile(r"[a-zA-Z0-9_./-]+")

+# Unicode general categories dropped from a raw token before it is quoted:
+# control characters (Cc) and surrogates (Cs). Everything else -- punctuation,
+# symbols, other scripts -- is left for the FTS5 tokenizer, which is what makes
+# the quoted form parse-safe without a whitelist of characters.
+_UNSAFE_CATEGORIES = frozenset({"Cc", "Cs"})
+

 def _terms(question: str) -> tuple[str, ...]:
     return tuple(
@@ -30,6 +37,40 @@ def _quote_term(term: str) -> str:
     return f'"{term}"'


+def prose_tokens(question: str) -> tuple[str, ...]:
+    """Every whitespace-separated token of ``question`` that carries an alphanumeric.
+
+    The §5 candidate's tokenisation (council D-12), ported from the archived
+    ``feat/knowledge-proof`` branch's ``plan_prose_query``: no stop list, no
+    length filter, case preserved. Control and surrogate characters are
+    stripped from each token first; a token left with no alphanumeric at all
+    (``---``, ``???``) is dropped because FTS5 could match nothing in it.
+    """
+    tokens: list[str] = []
+    for raw in question.split():
+        token = "".join(
+            char for char in raw if unicodedata.category(char) not in _UNSAFE_CATEGORIES
+        )
+        if any(char.isalnum() for char in token):
+            tokens.append(token)
+    return tuple(tokens)
+
+
+def _quote_prose_token(token: str) -> str:
+    """Quote a raw token as one FTS5 string; an embedded ``"`` is doubled, per FTS5."""
+    return '"' + token.replace('"', '""') + '"'
+
+
+def prose_or_query(question: str) -> str:
+    """The §5 candidate widen string: every raw token quoted and joined with ``OR``.
+
+    Nothing this returns can fail to parse: each token is a double-quoted FTS5
+    string, so operators, columns, prefixes and punctuation inside it are
+    plain text for the tokenizer. Returns ``""`` when no token survives.
+    """
+    return " OR ".join(_quote_prose_token(token) for token in prose_tokens(question))
+
+
 @dataclass(frozen=True)
 class QueryPlan:
     """The pure AND-to-OR plan for one question."""
```

## 6. Precision + value bootstrap — `eval/metrics.py` diff

```diff
diff --git a/packages/agent-session-tools/src/agent_session_tools/eval/metrics.py b/packages/agent-session-tools/src/agent_session_tools/eval/metrics.py
index 851b3370..2af0247e 100644
--- a/packages/agent-session-tools/src/agent_session_tools/eval/metrics.py
+++ b/packages/agent-session-tools/src/agent_session_tools/eval/metrics.py
@@ -135,6 +135,104 @@ def _clusters_of(
     return dict(clusters)


+def precision_values(
+    per_item: Mapping[str, ItemScore], items: Sequence[Mapping[str, Any]], k: int
+) -> dict[str, float]:
+    """Per-item precision@k: gold sessions among the first ``k`` ranked, over ``k``.
+
+    The denominator is ``k`` even when the arm returned fewer sessions -- an
+    empty (or crashed) answer is precision ``0.0``, never undefined -- so a
+    widen step that returns five sessions to find one gold is scored against
+    the same denominator as an ``AND`` arm that returned one (§5
+    pre-registration, guardrail 2). Gold ids are read from ``items`` because
+    :class:`ItemScore` carries the ranked list but not the ruler's answer key.
+    """
+    gold = {str(item["id"]): set(item["gold_session_ids"]) for item in items}
+    return {
+        item_id: len(set(score.ranked[:k]) & gold.get(item_id, set())) / k
+        for item_id, score in per_item.items()
+    }
+
+
+def macro_average_values(
+    per_item: Mapping[str, ItemScore], values: Mapping[str, float]
+) -> dict[str, Any]:
+    """:func:`macro_average` over an arbitrary per-item value map (strata from ``per_item``)."""
+    by_stratum: defaultdict[str, list[float]] = defaultdict(list)
+    for item_id, score in per_item.items():
+        by_stratum[score.stratum].append(values[item_id])
+    if not by_stratum:
+        return {"by_stratum": {}, "macro": 0.0}
+    strata = {name: sum(vals) / len(vals) for name, vals in sorted(by_stratum.items())}
+    return {"by_stratum": strata, "macro": sum(strata.values()) / len(strata)}
+
+
+def precision_at_k(
+    per_item: Mapping[str, ItemScore], items: Sequence[Mapping[str, Any]], k: int
+) -> dict[str, Any]:
+    """Macro precision@K over strata (a guardrail, reported beside recall)."""
+    return macro_average_values(per_item, precision_values(per_item, items, k))
+
+
+def _macro_diff_values(
+    sample: Iterable[str],
+    clusters: Mapping[str, list[str]],
+    stratum_of: Mapping[str, str],
+    a_values: Mapping[str, float],
+    b_values: Mapping[str, float],
+) -> float:
+    """Macro (over strata present in the sample) paired difference ``a - b``."""
+    by_stratum: defaultdict[str, list[float]] = defaultdict(list)
+    for cluster in sample:
+        for item_id in clusters[cluster]:
+            by_stratum[stratum_of[item_id]].append(
+                a_values[item_id] - b_values[item_id]
+            )
+    if not by_stratum:
+        return 0.0
+    return sum(sum(v) / len(v) for v in by_stratum.values()) / len(by_stratum)
+
+
+def paired_cluster_bootstrap(
+    a_values: Mapping[str, float],
+    b_values: Mapping[str, float],
+    items: Sequence[Mapping[str, Any]],
+    resamples: int = RESAMPLES,
+    seed: int = SEED,
+) -> dict[str, Any]:
+    """Paired cluster bootstrap of a macro-averaged per-item value difference ``a - b``.
+
+    The one resampling scheme every paired interval in the harness uses: gold
+    clusters (not items) are drawn with replacement, ``resamples`` times, from
+    ``random.Random(seed)``, and the percentile CI95 of the macro difference
+    is reported. :func:`cluster_bootstrap` is this over hits; precision and
+    MRR intervals pass their own per-item values. ``lower_above_zero`` is the
+    §5 adopt clause 1 (D-12) -- weaker than :data:`.MIN_LIFT`, and named so
+    the two are never confused.
+    """
+    clusters = _clusters_of(items)
+    names = sorted(clusters)
+    stratum_of = {str(item["id"]): str(item["stratum"]) for item in items}
+    rng = random.Random(seed)  # nosec B311 - statistical bootstrap, not cryptography
+    point = _macro_diff_values(names, clusters, stratum_of, a_values, b_values)
+    draws = sorted(
+        _macro_diff_values(
+            rng.choices(names, k=len(names)), clusters, stratum_of, a_values, b_values
+        )
+        for _ in range(resamples)
+    )
+    lower = draws[int(0.025 * resamples)] if names else 0.0
+    upper = draws[max(int(0.975 * resamples) - 1, 0)] if names else 0.0
+    return {
+        "point": point,
+        "ci95": [lower, upper],
+        "resamples": resamples,
+        "seed": seed,
+        "clusters": len(names),
+        "lower_above_zero": lower > 0.0,
+    }
+
+
 def _macro_diff(
     sample: Iterable[str],
     clusters: Mapping[str, list[str]],
@@ -164,24 +262,24 @@ def cluster_bootstrap(
     Gold clusters (not items) are the resampling unit, because items inside a
     cluster share a session and are not independent. Percentile CI95; a lift
     is *established* only when the lower bound clears :data:`.MIN_LIFT`.
+    :func:`paired_cluster_bootstrap` over the per-item hits, with the same
+    draws in the same order (pinned against a committed receipt by
+    ``tests/test_eval_metrics.py``).
     """
-    clusters = _clusters_of(items)
-    names = sorted(clusters)
-    rng = random.Random(seed)  # nosec B311 - statistical bootstrap, not cryptography
-    point = _macro_diff(names, clusters, a_per_item, b_per_item)
-    draws = sorted(
-        _macro_diff(rng.choices(names, k=len(names)), clusters, a_per_item, b_per_item)
-        for _ in range(resamples)
+    stats = paired_cluster_bootstrap(
+        {item_id: float(score.hit) for item_id, score in a_per_item.items()},
+        {item_id: float(score.hit) for item_id, score in b_per_item.items()},
+        items,
+        resamples=resamples,
+        seed=seed,
     )
-    lower = draws[int(0.025 * resamples)]
-    upper = draws[max(int(0.975 * resamples) - 1, 0)]
     return {
-        "point": point,
-        "ci95": [lower, upper],
+        "point": stats["point"],
+        "ci95": stats["ci95"],
         "resamples": resamples,
         "seed": seed,
-        "clusters": len(names),
-        "established": lower >= MIN_LIFT,
+        "clusters": stats["clusters"],
+        "established": stats["ci95"][0] >= MIN_LIFT,
     }


@@ -238,7 +336,11 @@ __all__ = [
     "hit_and_rank",
     "latency_percentiles",
     "macro_average",
+    "macro_average_values",
     "mrr_at_k",
     "non_inferiority",
+    "paired_cluster_bootstrap",
+    "precision_at_k",
+    "precision_values",
     "recall_at_k",
 ]
```

## 7. ADR-0011 amendment — diff

```diff
diff --git a/docs/adr/0011-retire-okf-ontology-and-concept-sidecar.md b/docs/adr/0011-retire-okf-ontology-and-concept-sidecar.md
index c5304509..42c2faf9 100644
--- a/docs/adr/0011-retire-okf-ontology-and-concept-sidecar.md
+++ b/docs/adr/0011-retire-okf-ontology-and-concept-sidecar.md
@@ -1,10 +1,13 @@
 # ADR-0011: Retire the OKF import, the tier-1 ontology and the concept sidecar

-**Status:** Accepted · **Date:** 2026-09-10 · **Deciders:** Andy Taylor (owner)
+**Status:** Accepted · **Date:** 2026-09-10 · **Amended:** 2026-09-15 · **Deciders:** Andy Taylor (owner)
 **Supersedes:** the IN-FLIGHT ontology and concept-sidecar claims in
 `docs/architecture/session-memory/README.md` (2026-09-09 record) and the corresponding sections of
 the branch ADR *0011-claim-centric-learning-memory* on `feat/knowledge-proof` (marked RETIRED there;
 its claim-centric learning-memory decision itself stands and will be renumbered when merged).
+[Superseded 2026-09-15: that decision was never merged and will not be — PR #19 is closed and the
+branch tip is archived; see *Disposition after semantic-layer completion* below. The sentence is
+kept as written.]

 ## Context

@@ -50,6 +53,8 @@ What is **kept**, because it is not OKF and the data supports it:
   `get_concept_context`) — a first-party concept store with its own contract, unrelated to the sidecar;
 - the **evidence tier** and the **learning-memory** claims/evidence store on `feat/knowledge-proof`
   (ADR *claim-centric learning memory*) — the semantic layer's prerequisites;
+  [Superseded 2026-09-15: the semantic-layer programme sealed without this store; see the
+  disposition section below. The bullet is kept as written.]
 - every **receipt** and evidence file that documents the experiment and this decision (immutable
   history, marked RETIRED where it describes the removed layers).

@@ -78,3 +83,51 @@ What is **kept**, because it is not OKF and the data supports it:
 - **Leave the code on branches "in case".** Rejected: unmerged branches rot, and the owner's failure
   mode is open tasks that never close. Tips are tagged `archive/*-2026-09-10` before deletion, so
   nothing is lost.
+
+## Disposition after semantic-layer completion (2026-09-15)
+
+Written under council decision D-13
+(`docs/architecture/plan-integration/council/arbitration-plan-round1-2026-09-15.md`): this ADR is
+amended, not rewritten. Everything above is preserved as written on 2026-09-10; the two statements
+that no longer hold are marked superseded in place, and this section records what actually happened.
+
+1. **The claim-centric learning-memory decision was not merged.** The header above says the branch
+   ADR's "claim-centric learning-memory decision itself stands and will be renumbered when merged".
+   It did not merge and will not: `feat/knowledge-proof` was never integrated into `main`, and its
+   pull request is closed (item 4). The sentence is superseded; it stays in the header as the record
+   of what was expected on 2026-09-10.
+
+2. **The semantic layer did not need that store.** The *Decision* section keeps "the evidence tier
+   and the learning-memory claims/evidence store on `feat/knowledge-proof` … — the semantic layer's
+   prerequisites". The semantic-layer programme on `main` **sealed on 2026-09-15** without it
+   (`docs/architecture/session-memory/receipts/semantic-layer/`; SEALED outcome recorded at
+   `a0272a52`: G2 met, G1 not established, owner keeps the `mcp`/`web` hybrid default). No claim or
+   evidence table participates in the shipped `session_search`; the "prerequisites" claim is
+   superseded. It had already been contradicted by the branch's own data: **Stage F measured the
+   fused claims arm at −0.140 recall@5** on DEV, below prose alone (recorded in
+   `docs/architecture/session-memory/receipts/okf-removal-inventory-2026-09-10.md`, citing branch
+   ADR-0011:301, which also records the fused arm "significantly *worse* than prose alone (−0.154,
+   CI95 [−0.252, −0.065]), replicating DEV (−0.140)"). Measured, the store was a cost to recall, not
+   a prerequisite for it.
+
+3. **The portable lexical hypothesis was separated from the retired architecture and measured on
+   its own.** The one retrieval win the branch produced (F-B0-1, *Context* above) was a planner
+   construction — `plan_prose_query`'s quoted-raw-token `OR` — and owed nothing to the storage or
+   ontology layers this ADR retired. It was ported to `main` as
+   `agent_session_tools.query_planner.prose_or_query` and pre-registered (D-12) in its narrowest
+   position, the `OR` *widen* step of the shipped planner:
+   `docs/architecture/session-memory/receipts/lexical/preregistration-2026-09-15.md`. The verdict is
+   `docs/architecture/session-memory/receipts/lexical/or-fallback-dev-2026-09-15.md`:
+   **`adopt: false`** — DEV macro recall@5 paired delta −0.0101, CI95 [−0.0500, +0.0278]; clause 1
+   (CI95 lower bound > 0) failed, the other three clauses held. The shipped planner is unchanged; the
+   helper and its tests stay as measured code. The historical +0.142 (*Context*) was measured against
+   the Stage 1 planner and a different corpus and did not carry.
+
+4. **Branch disposition.** PR #19 is closed. Its tip `464a8cdc` is tagged
+   `archive/feat-knowledge-proof-2026-09-15`; the branch's primary receipts (Stage F, the claims-layer
+   gate results cited in *Context*) remain reachable via that tag. Nothing from the branch is deleted
+   from history.
+
+5. **No renumbering.** An ADR that was never merged is not renumbered. `0011` on `main` is this
+   document; the branch ADR *0011-claim-centric-learning-memory* remains what it is — a record on an
+   archived branch, cited above by its branch line numbers.
```

## 8. Deliverables — numbered H2 sections, in this order

1. **Verdict on the verdict:** is `adopt: false` the correct reading of the frozen rule against these
   numbers? One sentence. Then: was the rule itself sound as pre-registered (a strict > 0 lower bound on a
   91-item DEV set with a 61-item ceiling — what power did this test have to detect the effect it was
   looking for)? Say what you would have pre-registered instead, if anything, and whether that would have
   changed the outcome here.
2. **Statistical findings** 🔴/🟡/🔵/💡: the paired cluster bootstrap (57 clusters, 10,000 resamples, seed
   20260910, percentile CI) — correct for this design? Percentile vs BCa? Is treating a crash as a miss in
   the denominator right? Is the "61-item ceiling" handled correctly (unwinnable items kept in the
   denominator)? Any multiple-comparison issue in reporting all ordered pairs while adopting on one
   pre-specified pair?
3. **Instrument findings:** the arms as implemented vs as pre-registered (does `and_then_prose_or` do
   exactly and only what §0 says? does any arm see explicit-syntax input?); the verdict code (does it
   implement the four clauses literally; any way it could pass a candidate it should reject or vice
   versa); the metric code.
4. **The unadopted signal.** Both OR-only arms scored 0.2274 vs shipped 0.1700 (+0.0575, CI95 crossing
   zero). The receipt correctly refuses to adopt them under this pre-registration. Should a NEW
   pre-registration be written for `or_first_filtered`, and if so what would its rule, arms and minimum
   detectable effect be? Or is the honest reading "the lexical ceiling is reached; stop"?
5. **ADR-0011 amendment:** does it supersede without rewriting history; are the claims bounded to what the
   receipts establish; anything stated that is not established (the brief tells you the archive tag and
   the PR close are stated from the decision, not yet executed — is that acceptable wording for an ADR)?
6. **Definition of done check** for this stream as a checklist a reviewer ticks from command output.

Be concrete: a line number, a number, a test name.
