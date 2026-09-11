# Stage 2 record — one lexical service; the crash class dies

**Date:** 2026-09-11 · **Commits:** `79425cbe` (service), `d060d3f2` (surfaces + harness + pins),
receipts commit (this file) · **Council:** single seat, `openai.gpt-6-astra` — see the addendum
at the foot once the review returns.

## What shipped

`agent_session_tools/retrieval.py` is the one lexical retrieval service. `session_search` (MCP)
and `session-query search` (CLI) both call `retrieval.search()` and return the same document —
`{"rows": [...], "retrieval_status": {...}}` — with a real `message_id` on every row and query-time
exclusion (`exclude_message_ids`) on the tool. The CLI's own SQL is gone.

The crash class dies by construction: FTS5 operators are uppercase by definition, so a query is
explicit FTS5 only when it carries an uppercase `AND`/`OR`/`NOT`/`NEAR` or the `fts:` prefix.
Everything else is planned into quoted terms that cannot fail to parse (AND first, widened to OR
when empty — the shipped semantics, kept). Double-quoted spans survive as phrases. An explicit
query FTS5 rejects is re-run as natural language with the rejection in `retrieval_status.note`.
An empty result is never silent: `plan="none"` plus a note says nothing was searched.

## Gates (freeze §5), measured — `stage2-gold.json`, `stage2-census-mcp.json`

| gate | required | measured |
|---|---|---|
| crashes through the real MCP tool | 0/91 | **0/91** (frozen control still 42/91) |
| crashes through the CLI | 0/91 | **0/91** (was 42/91 + zero rows on the other 49) |
| CLI ≡ MCP, ordered session lists | 91/91 | **91/91** — counted directly over the per-item `ranked` arrays (`stage2-census-transitions.json` → `gold_counters`), not inferred from equal aggregates |
| K-stratum paired delta vs frozen | not negative | K **0.182 → 0.303**; P 0.034 → 0.034; R 0.103 → 0.138 |
| planner golden | unchanged | **NOT MET AS WRITTEN — gate amended** (see below): equal after projecting `message_id` away, checked between `80ee57bb` and `d060d3f2` by `scripts/eval/stage2_council_evidence.py` |
| macro recall@5 (reported, not gated) | — | **0.1066 → 0.1585**, paired +0.052, CI95 [+0.011, +0.100] (57 clusters) |
| latency | — | mcp p50 20.8 ms / p95 92 ms (was 18.5 / 94.5) |

Honest detail: of the 42 former crashers only **5** become hits at K=5 (`frozen_crash_and_live_hit_at_5: 5`, counted per item; `moved_outside_crash_class: []`). The crash class is dead;
those questions now have the same ranking problem as everything else. That is Stage 4's problem,
and the K/P/R shape says so: K and R moved, P did not.

## Gate amendment — the golden gate was changed, not met

The freeze said "golden file unchanged". That literal gate is **not met**: `row_keys` gained
`"message_id"` and each case result gained its id (15 changed lines in the diff stat: the
trailing-comma lines count as changed). The seat was right that labelling this "unchanged" was
wrong. The gate is hereby **amended** to: *the golden is equal to its Stage 1 form after
projecting `message_id` away* — checked between named commits `80ee57bb` and `d060d3f2` by
`scripts/eval/stage2_council_evidence.py` (`golden_projection.equal_after_projecting_message_id_away:
true`, `added_row_key: ["message_id"]`). Why the amendment rather than a waiver: real message ids
were a Stage 2 requirement (the agent's interface had no citation handle; the census could not
gate the tool without them), and the invariant the gate protected — explicit-syntax and simple
cases do not move while the planner changes — is exactly what the projected equality checks.

## Census through the real tool — first time possible

`stage2-census-mcp.json`: 5,434 eligible · hits **3,345** · hit@5 **0.6156** (Stage 1 frozen
0.1305) · crash **0** (was 2,349) · vocabulary 257 · ranking 1,832 (untied 1,546) · tied hits 0.

A jump that size was not accepted on sight. The **full population** was re-run through both arms
with identical self-exclusion and the ranked *session lists* compared per question
(`stage2-census-transitions.json`, `per_question` carries every row; 1,834 s):

| class (frozen → live) | n | frozen own hit | live own hit |
|---|---|---|---|
| identical ranked lists (planner ran in both) | 1,844 | 845 | 845 |
| frozen **crash** (the and/or/not class) | 2,349 | 0 | 1,577 |
| frozen **empty**, live rows | 1,227 | 0 | 1,016 |
| different lists | 14 | 4 | 4 |
| **regressions** (frozen hit, live miss) | **0** of 5,434 | | |

Mechanism, read from the shipped code rather than inferred: for each frozen-empty question the
Stage 1 replica's own `_frozen_escape_fts_query` was applied to the text — **1,217 of 1,227**
produce a single double-quoted phrase spanning the whole question (`whole_question_as_one_phrase`;
10 `other`). The shipped code treated any text containing a `"` as "explicitly quoted" and
searched the *entire question* as one exact phrase, which matches nothing but the question
itself. Learner turns quote error messages, file names and code constantly (22.6% of the
population). The planner now lifts quoted spans out as phrases and plans the rest.

Bound on the attribution: the transition table is a paired classification, not an ablation.
The crash class and the whole-phrase class are disjoint by construction (a question is
classified by what the frozen code did to it), so the counts above are exact for this corpus;
they are not a claim about other corpora. One instrument difference, stated so the numbers are
not mistaken for each other: the transition script excludes the question's **single** message
id, while `run_census` also excludes its byte-identical re-asks within the same session; so the
script's absolute rates (frozen 0.1562 / live 0.6334) run slightly above the receipts (0.1305 /
0.6156). Both arms receive identical exclusions inside each instrument, so the classes, the
mechanism and the zero-regression count stand; the receipts remain the official numbers.

Per source (Stage 1 → Stage 2): claude_code 0.016 → 0.806 (its turns are the quote-heavy,
punctuation-heavy ones), kiro_cli 0.202 → 0.520, codex 0.168 → 0.475, grok 0.221 → 0.588.

## Verification

- `ruff check`, `ruff format --check`, `pyright` (src + tests): clean; pre-commit hooks green on
  both commits (the first attempt at a surfaces-only commit was refused by the pyright hook
  because the harness still imported the deleted planner — the two were then landed together,
  which is the correct unit).
- `agent-session-tools`: **1,833 passed** on the final tree (1,805 before Stage 2, +28).
- `studyloop` package, **matched control**: the pre-Stage-2 tree (`80ee57bb`, worktree, same
  sandbox) fails 305 node ids; the Stage 2 tree fails 313; **299 in common**, identical exception
  profiles (158 `RuntimeError` event-loop leaks, 15 `TimeoutError`, 14 journey-root guards, 11
  `MultiplexerError` = no `tmux`, 11 `CalledProcessError` = no PyPI, in both). The 14 only-in-Stage-2
  ids are wheel-build smoke tests (network), one live-provider test, and two lifecycle ids that
  differ only by stderr noise concatenated into the node id; none touch search. Suspected
  environmental; not demonstrated clean beyond this comparison.
- Toy corpus (CI validation tier): 7/7 on measured values.

## Deferred, with reason

- `memory_search` (R3 "ideally"): it already plans safely over a different index
  (`context_evidence_fts`, OR of quoted terms in `context/collection.py`). Unifying its planner
  with `retrieval.plan_query` is a refactor with no behaviour change today; deferred to Stage 4
  where the shared service changes shape for the hybrid arm.
- Lexical tuning (the `len(token) > 2` filter, stop-word list, AND-first vs OR-first): Stage 2
  preserved the shipped semantics on purpose so the change is attributable. The planner is now
  one function with a receipt behind it; Stage 4 tunes it against the toy set and confirms once
  on SEALED.

## What Stage 3 and Stage 4 inherit

- The service is the seam the semantic arm plugs into: `RetrievalStatus.mode` is `"lexical"`
  and becomes `"hybrid"` only when the arm is established.
- The census can now gate the real tool (`supports_exclusion` read from the tool's schema).
- Ranking, not vocabulary and not crashes, is the dominant miss on the corpus the product serves:
  1,832 ranking misses vs 257 vocabulary misses.

## Council addendum — single seat `openai.gpt-6-astra`, verdict **REJECT** (6 findings)

Brief 25.5 KB; 58 s; 844 words. Every finding verified at source before acting.

| id | sev. | finding | disposition |
|---|---|---|---|
| F1 | MAJOR | fallback after a rejected explicit query re-entered explicit detection; `fts:fts:alpha?` runs `alpha?` unguarded | **CONFIRMED at runtime** (reproducer crashed with `fts5: syntax error near "?"`). Fixed: the fallback calls `plan_natural_language()` only, strips every prefix; regression tests through MCP and CLI (`fts:fts:alpha?`, `fts:"alpha" OR ? AND`) |
| F2 | MAJOR | an uppercase operator inside a quoted span classified as explicit, so `"error OR warning" recovery` never widened | **CONFIRMED.** Operators now count only outside double-quoted spans (`_has_operator_outside_quotes`); tests pin the seat's discriminating case (upper == lower inside quotes; operator outside quotes still explicit) |
| F3 | MAJOR | census attribution overclaimed from a 400-sample; mechanism unverified | **ACCEPTED** → full-population per-question transition receipt; mechanism read from the frozen escape function (1,217/1,227); zero regressions across 5,434; bound and instrument difference stated |
| F4 | MAJOR | golden gate labelled met when it was changed; "five added lines" vs 15-line stat | **ACCEPTED** → gate marked NOT MET AS WRITTEN and amended to projected equality, checked between named commits by script; the 15 lines are trailing-comma changes on lines that also gained a comma |
| F5 | MINOR | 91/91 and "5 rescued" inferred, not counted | **ACCEPTED** → counted directly (`gold_counters`): 91/91 ordered lists, 5 of 42, `moved_outside_crash_class: []` |
| F6 | MINOR | studyloop attribution lacked a matched control | **ACCEPTED** → pre-Stage-2 worktree run in the same sandbox; 299/305 common ids, identical exception profiles |

After the corrections the code fix and tests are in `c8c105c4`; the gold and census receipts
were **not** regenerated for F1/F2 because neither reproducer pattern occurs in the gold set or
in the census population in a way that changes an outcome (checked over all 5,434 texts: zero start
with `fts:`; **4** carry an uppercase operator inside quotes — all four re-run through the fixed tool
keep their recorded own-session outcome, 3 hits and 1 miss, now via the `or` plan). The receipts
therefore stand exactly.
Escalation rule: a REJECT with MAJORs escalates to three seats — **pending Andy's call** whether
to run the three-seat council now or fold Stage 2 into the Stage 3 three-seat review already
scheduled.
