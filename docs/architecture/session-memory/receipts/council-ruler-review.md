# Council review of the validation ruler — receipt

Round 1: `a2ff86ee`, `9f5d8401` (gpt-5.6-terra). Round 2: `aca2034b` (deepseek-3.2).
Brief: adversarial; find ways to pass without value / fail with value. Verdicts on v1:
REJECT (15 blocking) · REJECT (14 blocking) · APPROVE-WITH-CHANGES (5 blocking).
Transcripts: `~/.kiro/crew/subagents/<id>/result.txt` (rotate within hours; dispositions
below are the durable record). Every finding was checked against the v1 text before
disposition; "adopted" means v2 contains the change.

## Adopted (converged across ≥ 2 reviewers unless noted)

| Finding | Reviewers | v2 change |
|---|---|---|
| Per-question bootstrap ignores clustering | all 3 | cluster = source session / fact cluster; ≤ 2 q per cluster; cluster bootstrap |
| "CI excludes 0" certifies trivial gains | all 3 | established lift = paired lower bound ≥ +0.05 |
| 30 / stratum too small for P thresholds | all 3 | ≥ 50 / stratum, n ≥ 150, balanced ±5 % |
| Pooled metric dominated by K | a2ff, 9f5d | macro-average over K/P/R gated |
| 4 adaptive looks at one gold set inflate α | a2ff, 9f5d | DEV / SEALED split; one SEALED look per gate |
| Frozen-but-readable gold allows overfitting | a2ff, 9f5d | SEALED stored outside the repo, path never given to builders, SHA only committed |
| Fingerprint of ids + counts is too weak | all 3 | content digest over ids, message ids, bodies, tokenizer, config |
| Mutable "current planner" control | all 3 | factorial B0 (frozen) / B1 / B1+feature; B1 non-inferior to B0 |
| Fusion arm unspecified | a2ff, 9f5d | versioned fusion-spec receipt before first DEV look; equal byte budgets |
| G1 can pass on legacy-unbound concepts | 9f5d | candidate arm uses bound concepts only |
| K/R regressions hidden under pooled score | a2ff, aca | per-stratum non-inferiority (upper bound ≤ 0.05) |
| G2 proves bytes, not meaning | a2ff, 9f5d | blinded 100-concept entailment audit ≥ 95 %; mutation tests |
| No decision-correctness gate | all 3 | new G6: precision ≥ 0.95, conflict surfacing, abstention on no-coverage |
| No latency / payload budget | all 3 | p95 ≤ 500 ms and ≤ 2×B1; payload ≤ 32 KiB; no paid call in serving path |
| G3a determinism can hash a stale/wrong graph | a2ff, 9f5d | mutation must change hash; fixture graph; reconciliation receipt |
| G3b comparator chosen after seeing data | 9f5d, aca | comparator pre-registered = Stage 3 fused arm frozen at G1 |
| G3b rejects the ontology's typed-query value | 9f5d | separate typed-query benchmark (30 q, accuracy ≥ 0.90) with its own Stage 6 rule |
| G5 confounded ablation (removes raw search too) | 9f5d | both arms keep raw FTS; only knowledge-layer retrieval differs |
| G5 20 pairs / mean of ordinal / no blinding controls | all 3 | 40 pairs, counterbalanced, metadata stripped, α ≥ 0.70, Wilcoxon, MID 0.5; renamed **pilot** |
| Rubric rewards shallow behaviour ("fewer clarifying turns") | a2ff | those two items removed; "substantive first question" kept |
| No cheaper honest proxy | a2ff, 9f5d | decision-reconstruction benchmark before G5 |
| Stop rule ambiguous | a2ff, aca | "improvement" = DEV lower bound rose |
| Budget omits elapsed time and non-$ cost paths | a2ff, aca | 7-day cap; run-count caps; $0 external API without approval |
| "Proven" undefined as a composite | 9f5d | claim matrix; composite claim needs G1+G2+G6+budgets+G5 |
| Receipt chain integrity | aca | each receipt carries the previous receipt's SHA |
| Council authority ambiguous | aca | gate pass = mechanical clauses AND council review with no blocking objection; override only by cited artifact evidence |
| Gold admission gives no denominator; session-id-only gold | a2ff, 9f5d | atomic answer + evidence span; generated/rejected/admitted counts with reasons |
| Adversarial authoring brief | aca | explicit brief: P must defeat keyword index, R must need two sessions |

## Rejected, with reason

| Finding | Reviewer | Why not adopted |
|---|---|---|
| n ≥ 250 | aca | no power argument offered; n ≥ 150 balanced with cluster bootstrap and a +0.05 minimum lift is the calibrated choice; revisit if the DEV interval width exceeds 0.10 |
| Clopper-Pearson instead of Wilson | aca | Wilson is descriptive only in v2; the inferential statistic is the paired cluster bootstrap |
| "cold ≤ 2 s on reference hardware" | aca | 5 s is the code's existing `_MAX_COLD_REBUILD_SECONDS` contract (`ontology_live.py:28`); a new number would be an unmotivated claim |
| Council approval "cannot be overridden" | aca | adopted in modified form: override permitted only with cited artifact evidence, recorded — a council can be wrong about a fact |
| 2/3 CI runs per commit | aca | one green run of the identical commit suffices; transient exclusions need root cause (adopted) |
| G5 ≥ 80 topics for d ≈ 0.3 | a2ff | correct but beyond programme scope; G5 is explicitly a pilot and licenses no outcome claim |
| Token cost per solved problem in G5 | aca | G5 has no objective "solved" endpoint; token budgets are equalised across arms instead |
| Overall CI weighted by operational query prevalence | aca | prevalence is unknown; macro-average adopted instead |

## Not addressed (out of programme scope, recorded)

- Human audit sample for G5 ratings (a2ff #19): no human in the loop by instruction;
  recorded as a limitation of the pilot claim.
