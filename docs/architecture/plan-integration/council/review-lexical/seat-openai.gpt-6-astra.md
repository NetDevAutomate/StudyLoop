## 1. Verdict on the verdict

**`adopt: false` is correct: the candidate’s recall-delta CI95 lower bound is −0.04996, not strictly greater than zero, so the frozen conjunction fails regardless of the other three clauses.**

The rule was sound as a conservative **DEV screening gate**, not as confirmation of generalisable improvement. Pre-specifying one candidate, one primary comparison and the decision threshold before measurement is its principal strength.

Its prospective power is **not established by the brief**: no target effect, discordance assumption or power calculation was registered. The 91 items are not 91 independent observations; inference uses 57 clusters, and 30 items cannot contribute improvements. Keeping those items reduces attainable measured lift but preserves the intended population.

For scale only, the candidate CI width implies a normal-approximation standard error of about 0.0198. At that variance, clearing a two-sided CI95 lower bound above zero with 80% power would require roughly **+0.055 absolute macro recall**. This is a retrospective approximation, not a design-power calculation: bootstrap discreteness, cluster composition and the pattern of gains and losses matter.

I would have pre-registered:

- A smallest worthwhile effect, for example **+0.05 macro recall**, and a cluster-aware sample-size simulation targeting 80% power to detect it against zero.
- DEV as screening evidence, with adoption requiring fresh, untouched confirmation.
- A meaningful precision margin. With shipped precision@5 at **0.0363**, allowing a **0.05** drop permits precision to fall to zero; that guardrail is vacuous on this baseline.

None would rescue this candidate. Its point estimate is negative, and its reported CI upper bound, **+0.0278**, is below +0.05. That bounds this measured comparison; it does not prove “no effect” in other settings.

## 2. Statistical findings

- **🔵 Paired cluster bootstrap fits the design, conditionally.** Resampling the same gold clusters for both arms preserves pairing and within-cluster dependence. Ten thousand resamples and a fixed seed provide reproducibility. Whether the 57 clusters capture all material dependence, including shared sessions across clusters, is **not established by the brief**.

- **🟡 Percentile intervals are defensible, not uniquely correct.** They were frozen and preserve continuity with the programme’s ruler. BCa can address bias and skew, but cluster-jackknife acceleration can itself be unstable with sparse, discrete hit changes. Do not switch methods after this result. For a future study, evaluate coverage by simulation; any BCa calculation should jackknife clusters, not items.

- **🔵 Crashes belong in the denominator as misses.** This measures delivered retrieval, rather than retrieval conditional on successful execution. Precision and MRR should also be zero on crashes. Keep crash counts separately: the pre-registration additionally says that “crashes appeared” means reject, a requirement the verdict implementation does not enforce.

- **🔵 Keeping all 91 items is correct.** Removing the 30 unreachable items after measurement would change the estimand. An explicitly secondary reachable-item analysis could diagnose retrieval conditional on availability, but cannot replace the frozen metric. Because recall is macro-averaged over K/P/R, **61/91 is not automatically the macro-recall ceiling**; the unreachable items’ stratum allocation is needed.

- **🔵 No multiplicity adjustment is required for the one pre-specified deciding pair.** The other 19 ordered comparisons are descriptive/exploratory; reversed pairs are not independent discoveries. Claiming whichever arm wins as confirmed would introduce selection and multiplicity problems.

- **🟡 Equal aggregate scores do not establish equivalent OR-only arms.** Their differing recall intervals and MRR values already warn against that inference.

- **🟡 Correct the human receipt’s accounting.** “Hits changed on four” is inaccurate: binary hit status changed on **three** items—one gain and two losses. `A1-46` changed rank while remaining a hit. Say “four items changed hit status or a successful-hit rank.”

- **🟡 Reproducibility is narrower than corpus-independent replication.** Identical `metrics_sha256` across two runs supports deterministic reproduction on the same tree and clone. It supplies no independent outcome evidence. Record the first measurement and the reproduction explicitly rather than describing the execution literally as “one run.”

## 3. Instrument findings

**Planner arms**

`eval/arms.py::plan_and_then_prose_or` implements the narrow construction shown:

- Calls the captured shipped planner, preserving its AND query, terms and note.
- Returns the shipped empty plan when there are no content terms.
- Replaces only the second query with `prose_or_query(raw)`.
- Deduplicates when widen equals AND.
- Adds an empty-widen safeguard; whether any shipped-content input can trigger it is **not established by the brief**.

The helper constructs plans; execution of the fallback only after zero AND rows depends on the retrieval executor. That behaviour is stated in the brief, but the executor implementation is not supplied.

**Transport arms can receive explicit-syntax input; the substituted natural-language planner must not.** Patching `retrieval.plan_natural_language`, rather than `plan_query`, places the substitution behind the explicit door. The other variants match their registered constructions.

**🟡 Global patching needs an isolation guarantee.** `_planner_context` patches a module attribute, and `McpArm` also patches process environment. Overlapping calls can contaminate even the shipped arm, whose context is a no-op. Serial execution of this run is **not established by the brief**; identical repeated metrics do not prove isolation.

Proposed tests in `tests/test_query_planner_or_fallback.py`:

- `test_candidate_preserves_and_terms_and_note`
- `test_candidate_empty_content_never_searches`
- `test_candidate_widens_only_after_zero_and_rows`
- `test_candidate_deduplicates_equal_queries`
- `test_all_variants_bypass_planning_for_explicit_input`
- `test_planner_patch_restored_after_tool_error`

Use process isolation or enforce non-overlapping calls, including shipped calls, before supporting concurrent evaluation.

**Verdict code**

`eval/lexical.py::judge` correctly computes the four Boolean checks for the supplied numerical inputs. It is **not a complete validator of the frozen experiment**:

| Finding | Consequence | Required protection |
|---|---|---|
| No frozen candidate/control enforcement | An exploratory arm can be labelled adopted under `RULE` | Reject non-default pairs for this rule; separate generic comparison from registered verdict |
| No DEV, k=5, rows=10, lexical-mode, gold/corpus or bootstrap-setting validation | Another experiment can receive this experiment’s verdict | Validate the registered configuration and provenance before judging |
| Explicit-door and golden checks use the current checkout | Passing checks on another tree can certify a failing measurement tree, or vice versa | Bind guardrail evidence to the measured commit and tree state; record derivation-tree identity separately |
| No crash rejection | Positive recall could produce adoption despite the frozen “crashes appeared” wording | Encode that eligibility requirement explicitly without rewriting the registration |
| No finite-value or CI-consistency validation | Positive infinity or malformed intervals can pass clause 1 | Reject nonfinite metrics, reversed intervals and inconsistent records |

The receipt states a clean measurement tree at `ed6281b4`; these gaps do **not** overturn its rejection. They block trusting `judge` as a general fail-closed adoption gate.

Proposed `tests/test_eval_lexical.py` cases:

- `test_judge_zero_lower_bound_rejects`
- `test_judge_precision_boundary_is_inclusive`
- `test_judge_rejects_wrong_registered_pair`
- `test_judge_rejects_wrong_experiment_metadata`
- `test_judge_rejects_measurement_guardrail_tree_mismatch`
- `test_judge_rejects_crashes_under_frozen_rule`
- `test_judge_rejects_nonfinite_or_reversed_ci`

`derive_receipt` correctly hashes the supplied raw bytes and preserves the raw stable-view digest rather than claiming a self-hash. It does not verify that its parsed `raw` argument corresponds to those bytes; that guarantee belongs in the CLI or a validation layer, whose implementation is **not established by the brief**. Replace “values are otherwise byte-for-byte” with “values are otherwise unchanged”: JSON reserialization is not byte preservation.

**Metric code**

The macro aggregation and paired value bootstrap match the stated design. Specific contracts need tests in `tests/test_eval_metrics.py`:

- `test_precision_fixed_denominator_for_short_and_empty_results`
- `test_precision_uses_first_k_distinct_sessions`
- `test_crashed_item_has_zero_precision_and_mrr`
- `test_bootstrap_preserves_paired_cluster_multiplicity`
- `test_recall_bootstrap_matches_committed_receipt`
- `test_metrics_reject_invalid_k_resamples_and_item_sets`

`precision_values` slices before deduplicating. That is correct **only if** `ItemScore.ranked` already contains distinct sessions, as the stated collapse stage intends. It also assumes crashes have empty ranked lists and silently substitutes empty gold for unknown item IDs. Validate these invariants rather than masking schema errors.

`_macro_diff_values` averages over strata present in each draw. That matches the documented implementation, but absent strata change the draw’s weights. Preserve the frozen ruler here; investigate its coverage before a future registration.

Finally, soften `prose_or_query`’s “Nothing this returns can fail to parse.” Quoting protects the grammar of nonempty constructed queries; empty output requires caller handling, and arbitrary-input/backend limits are not proven absent.

## 4. The unadopted signal

**A new study of `or_first_filtered` is justified if fresh evaluation data can be obtained; “the lexical ceiling is reached” is not supported.** Thirty unreachable items establish an availability ceiling, not saturation of lexical ranking on the reachable items.

Prefer the filtered arm as the next hypothesis: it preserves shipped token semantics while isolating removal of AND-first gating. Equal DEV recall does not establish that filtering is immaterial.

A concrete new registration:

| Element | Proposal |
|---|---|
| Primary pair | `mcp:or_first_filtered − mcp`, both lexical, rows=10, k=5 |
| Arms | Those two only; any additional arm explicitly exploratory |
| Data | Fresh, untouched, cluster-separated gold on a frozen corpus; current DEV used only for planning |
| Primary rule | Paired cluster-bootstrap CI95 recall-delta lower bound >0 |
| Worthwhile effect | +0.05 absolute macro recall, declared before collecting outcomes |
| Precision | One-sided 95% lower bound on precision delta ≥−0.005 absolute |
| Safety | Zero crashes, all explicit-door tests pass, pre-planner golden unchanged |
| Inference | Frozen cluster definition, resample count, seed, estimator and missing-stratum policy |

The **0.005** precision margin is a proposed decision tolerance, not a fact established by the receipt; the owner must accept it before registration.

The filtered OR-only CI implies a rough standard error of **0.0324**. At that noise level, 80%-power detection against zero requires approximately **+0.091**, considerably larger than the observed +0.0575. Detecting +0.05 would require roughly **3.3 times the current effective information**, about **190 similarly informative independent clusters**, under a crude inverse-square approximation. Final sample size should come from cluster-aware simulation and also power the precision guardrail.

Do not reuse spent SEALED data or relabel current DEV as confirmation. Without fresh evidence and an adequate sample budget, retain the signal as exploratory and stop this stream without adoption.

## 5. ADR-0011 amendment

**The amendment structure preserves history appropriately; several conclusions and execution claims need correction.**

In `docs/adr/0011-retire-okf-ontology-and-concept-sidecar.md`, dated supersession markers plus an appended disposition section preserve the earlier expectations while making their current status explicit. Keeping the unmerged branch ADR under its original number is appropriate.

Required changes:

1. **Distinguish decision from execution.** The brief expressly says PR closure and archive tagging have not happened. Therefore “PR #19 is closed,” “Its tip … is tagged,” and “remain reachable via that tag” are unacceptable present-tense completion claims. Use:
   > Decision: close PR #19 and tag tip `464a8cdc` as `archive/feat-knowledge-proof-2026-09-15`. Execution pending.

   Update both the header annotation and disposition item 4. Record completion only after command output establishes it.

2. **Bound the prerequisite conclusion.** Shipping and sealing the semantic layer without the claims/evidence store refutes that store’s necessity for **this shipped programme**. It does not establish that claim-centric memory has no other useful role.

3. **Attribute the measured loss to the tested retrieval arm.** Replace “the store was a cost to recall” with “the tested fused-claims arm reduced recall relative to prose alone.” The receipts compare retrieval configurations, not storage in isolation.

4. **Replace “did not carry” with the narrower result.**
   > The historical lift was not established for the pre-registered narrow widen placement on this DEV corpus against the Stage 2 planner.

   This avoids implying that the two OR-only hypotheses were disproved.

5. **Avoid exhaustive claims without exhaustive evidence.** “The one retrieval win the branch produced” is broader than the supplied evidence. “The historical retrieval improvement cited here” is supportable.

The human receipt also says raw-token OR “pays for it in latency,” despite freezing latency as “reported, never compared.” Keep the measurements, remove that comparative conclusion, or explicitly acknowledge the descriptive comparison as outside the registered analysis.

## 6. Definition of done check

**Accept the numerical rejection; withhold completion sign-off until provenance wording and instrument protections are resolved.**

- [ ] **Regression output:** `uv run --group dev pytest packages/agent-session-tools/tests/test_query_planner_or_fallback.py` reports all tests passing, including:
  - `test_explicit_fts_prefix_is_verbatim`
  - `test_uppercase_operator_outside_quotes_is_verbatim`
  - `test_quoted_operator_is_not_explicit`
  - `test_pre_planner_golden_unchanged`

  The brief reports **13 passed** on the supplied tree.

- [ ] **New contract tests:** the proposed planner-isolation, verdict-validation and metric-invariant tests above pass. Their existence is **not established by the brief**.

- [ ] **Package quality:** whole-package pytest, ruff and pyright exit zero. The supplied baseline is **2120 passed**, ruff and pyright clean; record updated counts after fixes.

- [ ] **No serving adoption:** diff output against `a0272a52` shows no behavioural change to `retrieval.plan_natural_language` or `query_planner.plan`; `session_search_or_fallback.json` is absent.

- [ ] **Golden integrity:** hash output for `packages/agent-session-tools/tests/golden/session_search_pre_planner.json` equals
  `7152dae40af4918dffd6a51cc4b7d399c433384a3caa9a7ca64164e7a56795f6`.

- [ ] **Receipt integrity:** hash output matches the registered clone, gold and raw-receipt digests; validation confirms five arms, **455 per-item rows**, 20 ordered comparisons, 91 items, 57 clusters, k=5, rows=10, 10,000 resamples and seed 20260910.

- [ ] **Verdict reproduction:** the registered `lexical-verdict` command against the preserved raw receipt produces `adopt: false`, failing clause 1 only, with recall delta **−0.010101010101010102** and CI95 **[−0.049955791335101675, +0.027777777777777776]**. Measurement-tree guardrail evidence is explicitly bound to `ed6281b4`.

- [ ] **Execution isolation:** runner evidence establishes non-overlapping patched calls for the measurement. If it cannot, label this provenance gap and produce an explicitly identified isolated validation run against the same clone without overwriting the original receipt.

- [ ] **Documentation corrections:** the human receipt distinguishes three hit flips from one additional rank change, removes the latency conclusion, and records both run timestamps without treating reproduction as new evidence.

- [ ] **Archive completion:** `git rev-parse 'archive/feat-knowledge-proof-2026-09-15^{commit}'` resolves to the full commit beginning `464a8cdc`; `gh pr view 19 --json state,closedAt` reports `CLOSED` with a completion timestamp before the ADR claims execution.

- [ ] **Historical record retained:** diff output preserves the original ADR text with dated supersession annotations, leaves the frozen pre-registration unchanged, and records subsequent corrections as dated amendments.
