# Council record — Stage 1 (instruments and baselines)

**Date:** 2026-09-11 · **Cadence:** single seat, `openai.gpt-6-astra` (plan council F10) ·
**Verdict:** **ACCEPT-WITH-CORRECTIONS** — 5 findings (1 MAJOR, 4 MINOR), all closed below by code or
measurement before the freeze was committed. Brief 27 KB; seat returned in 57 s.

## What Stage 1 delivered (commits `3826a9b4` … this record)

The instrument, built before any product change: the retriever seam and frozen ruler constants; the
harness (`agent_session_tools.eval`: metrics ported from the branch scorer, gold runner, receipts with a
stable-metrics digest, three arms — the real MCP tool through FastMCP `call_tool`, the CLI as a subprocess,
a frozen replica of today's planner and SQL); the paraphrase census adapted to `sessions.db` with the
tied-question analysis; a planted public toy corpus so CI computes the same metrics; the model
measurements; the baseline receipts; and the freeze (`stage1-freeze.md`). 88 hermetic tests; gates clean.

## Dispositions

| id | sev. | finding | disposition |
|---|---|---|---|
| F1 | MAJOR | "unwinnable" is not an impossibility test: 81 hits among 397 "unwinnable" questions in the first census; the "ceiling" is an ambiguity-filtered rate | **ACCEPT → renamed and re-defined.** `tied` (identical text in > K sessions — a handicap, not an impossibility), `untied_share`, `hit_rate_untied` (hits on untied / untied), `hits_tied` reported never credited. In the honest re-run tied hits are **0**, which is what identical text should produce once the question's own copy is excluded — the 81 were self-hits. |
| F2 | MINOR | "ranking" misses included 2,220 crashes | **ACCEPT → `crash` is its own miss class**, never folded into ranking. Re-run: crash 2,349 · ranking 2,178 · vocabulary 198. |
| F3 | MINOR | ruler-side self-exclusion is not fail-closed: a hit with no message ids survives; the MCP arm returns none, so contamination was **UNVERIFIED** | **ACCEPT → the headline number changed.** The frozen arm now excludes at SQL level (`NOT IN`); the census **refuses** arms that cannot exclude (`supports_exclusion=False`); `apply_exclusions` drops hits of unknown provenance. Honest census hit@5 = **0.1305**, not 0.5256: the earlier figure was almost entirely the question finding itself. The contaminated receipt stays on disk, withdrawn by sidecar. |
| F4 | MINOR | parity evidence compared `(rank, hit, error_kind)`, not ranked lists | **ACCEPT →** every gold item now carries its ranked session ids in the receipt; mcp vs frozen identical on **91/91** ranked lists. |
| F5 | MINOR | the freeze names mutable dependencies (visibility config, fingerprint scope) without recording their resolved values | **ACCEPT →** receipts record `db.visibility` = admitted sources, visible/total sessions (7 sources; 4,600 / 5,879). |

Seat's Q-answers folded in: the `mcp` arm through `call_tool` is the right gating arm (what it cannot see —
transport, timeouts — does not move recall); the frozen *copy* is the right control while a test pins it
equal to the live planner, with a pinned-commit subprocess arm as the fallback if that test ever fails;
the bootstrap's 57 clusters make +0.05 a meaningful but coarse bar — confirmation on SEALED stays
mandatory; `syntax:<` questions (XML-ish agent prompts) stay in the census population — they are what
agents actually send.

## Baselines (the anchors; every later receipt pairs against these)

| ruler | arm | number |
|---|---|---|
| gold DEV 91 | mcp | macro recall@5 **0.1066** (K 0.182 · P 0.034 · R 0.103) · MRR 0.084 · **42/91 crash** (backtick 31 · `?` 8 · no-such-column 2 · comma 1) · p50 18 ms |
| gold DEV 91 | cli | **0.000** — same 42 crashes, 0 rows on the other 49 (strict adjacency phrase) |
| gold DEV 91 | frozen | 0.1066 · identical ranked ids to mcp on 91/91 |
| census 5,434 | frozen | hit@5 **0.1305** · on the 3,085 that ran **0.230** · hit-untied 0.141 · crash **2,349 (43.2%)** · ranking 2,178 (untied 1,955) · vocabulary 198 · tied hits 0 |
| census 5,434 | mcp | 0.5256 — **WITHDRAWN** (self-hits; evidence only) |
| cost | — | corpus 51,729 embeddable messages (not 57,247); overflow 21.8 / 15.7 / 18.1 % (MiniLM / bge-small / mpnet) — chunking mandatory; KNN 4.6 ms @384-d, 8.5 ms @768-d |

## What Stage 2 inherits

- The defect's true size: **43.2%** of real learner turns crash the shipped search, and the CLI the skill
  designates as the fallback answers nothing. On questions that run, the own session is found 23% of the
  time; ranking misses outnumber vocabulary misses **~11:1** — the census now says what the store census
  said, on the corpus the product serves.
- Gates from the freeze: 0/91 crashes through `mcp`; `cli` ≡ `mcp` ranked ids on the 91; golden file
  unchanged; K-stratum paired delta not negative against `frozen`.
- Two product findings for the service: `session_search` must return **message ids** (the agent's
  interface currently gives evidence no provenance, which is also why the census could not run through
  it), and it must accept query-time exclusion so the census can gate it.
