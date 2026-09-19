# Stage 0 — Jev access spike (2026-09-19)

**Programme:** `feat/jev-judge` — evaluate TypeSafe's Jev (a "System One" judgement model:
typed questions against a text state, returns typed answers with probabilities and
confidence, no text generation) as an *optional judgement provider* for StudyLoop's
unfilled judgement slots. Out of scope by design: the decision engine and completion
review (`learning/decision.py`, `planning/views.py`) — those count and compare dates,
which the vendor's own jaggedness page says Jev cannot do.

**Question this stage answers:** does the pre-release account answer at all, does the SDK
match its docs, and do the five 1–4 teach-back dimensions map onto Jev's Score legend?
It is an access and shape check, **not** a measurement of accuracy (n = 1 synthetic state).

## Method

- Script: `scripts/eval/jev_stage0_spike.py` (disposable; reads `TYPESAFE_API_KEY` from
  the environment, never prints it). SDK `typesafe-sdk==0.7.0`, Python 3.12.8.
- Model pinned to `jev-1.13.0` — never the `jev-latest` alias, because any threshold
  tuned against an alias silently moves when the alias does (vendor's advice, adopted).
- State: one synthetic teach-back (1,873 chars) — a networking-background learner
  explaining Python decorators with a middlebox/NAT analogy and a retry-decorator
  transfer example. **One factual error planted on purpose**: "the wrapping happens every
  time you call the decorated function, not when it's defined". A human marks that
  Accuracy 2 ("mostly correct, minor gaps") at best.
- Questions in one call: five `Score` questions whose four criteria are the verbatim level
  descriptors from `agents/shared/teach-back-protocol.md` (Recitation → Teaching), plus
  two `Noul` controls — positive (`has_factual_error`) and negative (`not_english`).
- Three identical calls to measure spread.

## Results

| dimension | jev score ×3 (0–3) | StudyLoop 1–4 (mean) | confidence ×3 | range | human expectation |
|---|---|---|---|---|---|
| accuracy | 2.09, 2.10, 2.15 | **3.11** | 0.52, 0.52, 0.54 | 0.06 | **2** (planted error) |
| own_words | 2.98, 2.98, 2.98 | 3.98 | 0.98, 0.98, 0.98 | 0.00 | 4 (novel analogies) |
| structure | 2.90, 2.88, 2.87 | 3.88 | 0.90, 0.88, 0.87 | 0.03 | 3–4 |
| depth | 2.03, 2.03, 2.03 | 3.03 | 0.96, 0.96, 0.97 | 0.00 | 3 (WHAT/HOW/WHY, no tradeoffs) |
| transfer | 2.67, 2.65, 2.68 | 3.67 | 0.67, 0.65, 0.68 | 0.03 | 3–4 |
| noul: has_factual_error | 0.48, 0.48, 0.43 | – | – | 0.05 | high |
| noul: not_english | 0.01, 0.01, 0.01 | – | – | 0.00 | ≈ 0 |

Per-level probabilities are returned for every Score (accuracy call 1:
`{0: 0.02, 1: 0.16, 2: 0.54, 3: 0.28}`), so a caller can take the argmax level and gate on
its mass instead of rounding the expected-value float — the docs say score levels are weak
in numerical calibration and warn against interpolating between levels.

Access: `model_answered = jev-1.13.0`. Latency 1,779 ms cold, then 521 / 534 ms. Usage
973 input / 107 output tokens per call → about $0.00004 per teach-back at $0.042 / Mtok.
Cost is not a factor in any later decision.

## Findings

1. **Access works and the SDK matches its docs.** `TypeSafeClient()`, `Score`, `Noul`,
   `client.system_one(state=, questions=, model=)`; answers carry `score`, `confidence`,
   `probabilities`, `legend`.
2. **Consistent, not deterministic — confirmed by probe, not by prose.** Across identical
   calls the Score range was ≤ 0.06 on a 0–3 scale (two dimensions identical to three
   decimals), Noul range ≤ 0.05. Any Stage 1/2 test must assert a band or a level, never
   an exact float, and CI must replay recorded fixtures rather than call live.
3. **The pedagogical dimensions landed where a human would put them.** Own words, structure
   and depth scored within the human expectation with confidence ≥ 0.87; depth 3.03 is
   exactly the "WHAT, HOW and WHY, but no tradeoffs" reading of the text.
4. **Accuracy was blind to the planted error.** 82 % of the mass sat on the two "accurate"
   levels and the error Noul stayed at 0.43–0.48, i.e. "don't know". This is the vendor's
   documented *literal reading* / *no technical precision* edge: Jev is a common-sense
   judge, not a Python-semantics checker. **But the confidence signal worked** — accuracy
   was the least-confident dimension (0.52 vs ≥ 0.65 elsewhere), so a confidence gate
   would have routed it to "ask the learner" rather than recording a 3.
5. Negative control held at 0.01: the Noul is not agreeing with everything.

## Design consequences carried into Stage 1 / Stage 2

- **Split by strength.** Correctness is domain knowledge; pedagogy is calibrated
  judgement. Stage 2 should have the mentor agent (harness LLM, which does know Python
  semantics) supply the *accuracy* judgement, and Jev score the four pedagogical
  dimensions — own words, structure, depth, transfer — where it excelled and where a
  generative model is weakest at calibration. Do **not** ship Jev as a sole accuracy judge.
- **Argmax + gate, not rounding.** Map a Score to StudyLoop's 1–4 as `argmax(probabilities)
  + 1`, and record it only when the argmax mass clears a threshold pinned to `jev-1.13.0`;
  below it, the dimension is "not scored — ask the learner" (the same never-fabricate rule
  the parked Bedrock extractor taught: `history/teachback.py` must never receive a guess).
- **Hypothesis for the Stage 2 gold set, not a result:** the two least-confident dimensions
  here (accuracy 0.52, transfer 0.67) were the two a human would hesitate on. Whether
  confidence tracks human disagreement is the first thing the labelled set should test.

## Limits

One synthetic state, three repeats, no gold labels. Nothing above is an accuracy figure;
it is a shape check that surfaced one hard constraint (finding 4) early enough to design
around it.

## Reproduce

```bash
set -a; . /path/to/studyloop/.env; set +a   # TYPESAFE_API_KEY only; never committed
uv run --no-project --python 3.12 --with typesafe-sdk==0.7.0 python scripts/eval/jev_stage0_spike.py
```

Writes `stage0-receipt.json` beside this file (the committed copy is the run described
above). Numbers will differ slightly on re-run — see finding 2.
