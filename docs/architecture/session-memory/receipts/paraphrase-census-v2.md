# Paraphrase census v2 — six-source corpus (sidecar to `paraphrase-census.json`)

**Date:** 2026-09-10 · **Supersedes the per-harness rows for retired labels in** `paraphrase-census.json`
(v1, committed unchanged — sha256 `16165c88…a6a4d`). Receipts are never edited after commit; this
sidecar carries the correction. The v2 artefact is `paraphrase-census-v2.json` (same script, same
planner, scoped store).

## Why a v2

v1 was measured over a learning-memory store ingested from **all 14** `sessions.db` source labels.
On 2026-09-10 the supported adapter set was ruled to be exactly six harnesses (kiro-cli, Claude Code,
Codex, OpenCode, pi, Grok Build; receipt `adapter-scope-2026-09-10.md`), plus `study_mentor` as a
first-party source. The 1,279 sessions under the 7 retired labels (`repoprompt`, `aider`,
`kilocode_cli`, `litellm-proxy`, `gemini_cli`, `bedrock_proxy`, `omp`) are hidden from every read
path, never deleted. A retrieval census must be measured over the corpus the retriever will actually
serve, so v1's figures — and in particular its rows for the retired labels — no longer describe the
product.

## What is withdrawn

The following `summary.by_harness` rows in v1 are **withdrawn as product findings**. They remain in
the v1 file as a historical record of what a 14-source index measured; they must not be cited as
evidence about any supported adapter, and the labels are not adapters (no adapter code for them
exists anywhere in the repository — see `adapter-scope-2026-09-10.md` §Findings):

| v1 row | n | hit_rate | disposition |
|---|---|---|---|
| `aider` | 204 | 0.005 | withdrawn — retired label; the 1/204 figure was never an adapter defect, it is a label whose transcripts carry almost no learner prose |
| `kilocode_cli` | 147 | 0.469 | withdrawn — retired label |
| `repoprompt` | 430 | 0.416 | withdrawn — retired label |
| `litellm-proxy` | 360 | 0.894 | withdrawn — retired label (gateway envelopes, not a harness) |
| `gemini_cli` | 97 | 0.608 | withdrawn — retired label (Gemini **API** provider is unaffected; only the CLI harness is gone) |

v1's `zero_overlap_examples` (12 rows) are drawn from `gemini_cli`, `litellm-proxy`, `opencode`,
`repoprompt`; the 10 rows from retired labels are withdrawn as examples. v2 carries its own 12 examples
(`kiro_cli`, `opencode`).

## v2 headline vs v1

Same script (`scripts/knowledge_proof/paraphrase_census.py`), same planner
(`learning_memory.store.plan_prose_query`, phrase-token OR), same eligibility rules (≥ 3 content
tokens, ≤ 200 words, human-driven sessions only), all eligible questions (no sampling).

| measure | v1 (14 sources) | v2 (six + study_mentor) | delta |
|---|---|---|---|
| learner turns in human sessions | 8,414 | 4,710 | −3,704 (retired labels' turns) |
| measured questions | 4,577 | 3,299 | −1,278 |
| overlap with own session (mean / median) | 0.614 / 0.667 | 0.647 / 0.700 | +0.033 / +0.033 |
| share zero overlap | 7.43 % | 5.70 % | −1.73 pt |
| **self-retrieval@5 hit rate** | **57.29 %** | **61.08 %** | **+3.79 pt** |
| miss — vocabulary gap | 7.43 % (340) | 5.70 % (188) | −1.73 pt |
| miss — ranking | 35.29 % (1,615) | 33.22 % (1,096) | −2.07 pt |

Per supported harness (rows with n ≥ 50, the script's reporting threshold; opencode 14 sessions,
pi 3, study_mentor 6 contribute the remaining 21 questions and fall under it):

| harness | n (v1 → v2) | hit_rate v1 → v2 | vocab-gap misses v1 → v2 | ranking misses v1 → v2 |
|---|---|---|---|---|
| `kiro_cli` | 2,151 → 2,151 | 0.590 → **0.601** | 175 → 175 | 706 → **684** |
| `codex` | 787 → 787 | 0.654 → 0.654 | 4 → 4 | 268 → 268 |
| `claude_code` | 205 → 205 | 0.390 → 0.395 | 1 → 1 | 124 → 123 |
| `grok` | 135 → 135 | 0.867 → 0.867 | 5 → 5 | 13 → 13 |

## Reading the delta honestly

- **The question set for every supported harness is unchanged** (identical `n`, identical
  vocabulary-gap counts). Only the *competitor pool in the FTS index* shrank. So the +3.79 pt headline
  is two effects, and only one of them is "retrieval got better":
  1. **Composition** (most of it): removing 1,278 questions whose own hit rates were low or extreme
     (`aider` 0.5 %, `repoprompt` 41.6 %, …) shifts the weighted average. This is a *re-scoping*, not
     an improvement.
  2. **Less cross-talk** (small, real): with 1,279 fewer sessions competing, 22 kiro_cli questions and
     1 claude_code question that lost their top-5 slot to a retired-label session now rank. That is a
     genuine effect of serving the scoped corpus: 23 ranking misses gone, 0 new misses anywhere.
- **Vocabulary gap is unchanged per harness** — as it must be: overlap is measured against the
  question's *own* session, which scoping cannot alter. The headline vocab-gap drop (7.4 → 5.7 %) is
  entirely composition.
- **Ranking remains the dominant miss class** (33.2 % of questions; 1,096 misses vs 188 vocabulary).
  The 70 % self-retrieval target named after v1 is **not met** on the six-source corpus (61.1 %);
  the ranking pass is still the next retrieval lever. This plan does not close it (council receipt
  `council-plan-2026-09-10.md`, "Missing work").
- **Stage 4's planner is not a confound.** Both censuses queried the shipped phrase-token OR planner
  (script docstring, item 2); landing PR #18's keep-half changes what `main` ships, not what this
  census measured. A census after Stage 4 would be measuring the same planner over the same store.
- **Corpus stability:** `sessions.db` held 5,879 sessions at both runs; the archive per-source counts
  recorded in `ingest-archive-v1.json` (`archive_per_source_sessions`) equal today's live counts for
  every in-scope label, so no session arrived between v1 and v2. The 20 in-scope sessions v2 rejected
  are the same `NoEvidenceError` (nothing citable) rejects v1 recorded.

## Provenance (re-derivable)

| artefact | value |
|---|---|
| store v2 | `~/.local/share/studyloop/knowledge-proof/learning-memory-v2.db`, sha256 `e0d507fefa799916…` (matches `paraphrase-census-v2.json:store_sha256`), WAL empty |
| store v1 (untouched) | `…/learning-memory.db`, sha256 `f5e923e878b05970…` = `paraphrase-census.json:store_sha256` |
| ingest v2 | `ingest-archive-v2.json` — scope `[claude_code, codex, grok, kiro_cli, opencode, pi, study_mentor]`, 4,580/4,600 ingested, hidden 1,279 across 7 labels, FTS integrity `ok`, 20.7 s |
| ingest command | `uv run python -m learning_memory.ingest_archive --db ~/.config/studyloop/sessions.db --store <v2> --receipt <ingest-archive-v2.json>` (default scope = `SUPPORTED_SOURCES`) |
| census command | `KNOWLEDGE_PROOF_STORE=<v2> uv run python scripts/knowledge_proof/paraphrase_census.py --out <paraphrase-census-v2.json>` (4 m 50 s) |
| code | `feat/knowledge-proof` @ `5b930dbd` (scoped `ArchiveAdapter`), `sessions.db` read-only |
