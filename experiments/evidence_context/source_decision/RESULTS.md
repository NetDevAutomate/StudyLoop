# Stage 11 observed results

The explicit source adapter matched all 12 reviewed condition decisions across 11
distinct source/target pairs. These deterministic outcomes are displayed for both
draft repeats (24 output rows), not 24 independent successes. The conservative
gate blocked four justified outputs. The advisory model produced four unsupported
choices and one invalid response. This is a source-to-policy conformance result; no
improvement to the model's reasoning or general effectiveness has been established.

## Keep coverage, unsupported choices and false blocks separate

| Output path | Usable output decisions | Label matches | Unsupported A/B | False blocks on justified A/B | Justified A/B retained |
|---|---:|---:|---:|---:|---:|
| Advisory model draft | 23/24 | 19/23 valid | 4/23 valid | 0/8 positive outputs | 8/8 |
| Matched candidate fields only | 24/24 | 20/24 | 0/24 | 4/8 positive outputs | 4/8 |
| Explicit source adapter | 24/24 | 24/24 | 0/24 | 0/8 positive outputs | 8/8 |

There are twelve case conditions and eleven distinct source/target pairs, each with
two draft calls. Four positive conditions use three distinct source/target pairs.
Counts are descriptive; neither repeats nor the paired extraction-omission control
are independent evidence of general error rates. The deterministic outputs are the
same for both repeats; 24/24 is twelve condition outcomes displayed twice.

An always-none baseline would match 16/24 but block all 8 positive outputs. Always A
or always B would each match 4/24. Such baselines demonstrate why overall label match
alone would reward unhelpful caution on this imbalanced set.

## What happened in each case?

Values separated by a slash are repeats. The two deterministic columns apply to both.

| ID | Case | Expected | Advisory | Checked only | Source adapter |
|---|---|---|---|---|---|
| C01 | Present revision omitted by extraction | B | B / B | none | B |
| C02 | Wrong environment | none | none / none | none | none |
| C03 | Report only | none | B / B | none | none |
| C04 | Valid A | A | A / A | A | A |
| C05 | Winner B outside observed block, A inside | A | A / A | none | A |
| C06 | Missing winner | none | none / invalid | none | none |
| C07 | Two observed blocks | none | none / none | none | none |
| C08 | Wrong workload | none | none / none | none | none |
| C09 | Duplicate winner | none | none / none | none | none |
| C10 | Valid B; same source/target as C01 | B | B / B | B | B |
| C11 | Duplicate revision | none | B / B | none | none |
| C12 | Missing revision | none | none / none | none | none |

Here "false block" means withholding a choice justified by the complete source. The
conservative gate is behaving correctly under its narrower matched-candidate contract;
these counts measure lost usefulness against the source-level task, not coding defects.

C01 and C10 are an intentional counterfactual pair: the source and target remain fixed
while the scripted extraction omits a field in C01. C05 tests a different extraction
fault: the candidate quotes a winner outside the observed block. Both are false-block
controls for the conservative path, not natural extraction-error frequency estimates.

## Previous cases versus fresh development conditions

| Stratum | Advisory | Checked only | Source adapter |
|---|---|---|---|
| Three previous cases; 6 outputs | 2 matches, 4 unsupported | 6 matches | 6 matches |
| Nine fresh conditions; 18 outputs | 17 matches, 1 invalid | 14 matches, 4 false blocks | 18 matches |

All unsupported advisory choices occurred on previous failure cases (report kind and
duplicate revision). Among its 17 valid fresh responses, the model made no unsupported
choices or false blocks. We therefore cannot claim an observed safety advantage over
the model on fresh cases; the adapter reproduces known protections and survives these
fresh positive/negative controls. There is no independent real-world holdout here.

## Original parsing failures remain visible

All 24 gateway responses ended with `stop`. Only three were strict JSON. Twenty more
parsed after the **predeclared** complete-fence-only parser removed a Markdown wrapper.
One remained invalid because of an extra trailing closing bracket. That response is
preserved without repair or retry and is excluded from valid-choice denominators.
Its prose appeared to abstain, but extracting that apparent answer would change the
frozen parser contract after seeing the result. No such adjustment was made.

This differs from Stage 10: fence handling was declared before this run, while strict
JSON compliance is still reported separately. Transport success is not schema success.

## Explanation and reference checks

Every locator in all 24 outputs from each deterministic path resolved against its
bound source or target version. Every source-adapter abstention had a structured issue
and a nonempty next check (16/16 abstention outputs). Conservative abstentions likewise
had issue/check coverage (20/20). These are integrity/coverage checks, not a learner-value
or semantic-quality score.

All 23 valid advisory drafts had quotes locatable in the original source. Four still
recommended an unsupported choice. The report-only answers deferred deciding whether
report kind was acceptable to their next check. The duplicate-revision answers chose
the matching revision while omitting the conflicting one from their explanations.

The source adapter references original and target fields separately. Its missing-field
trace cites the inspected source rather than inventing an absent field quote. Its
next checks name what must be recorded, reconciled or rerun. These explanations are
code-rendered applications of the fixture rule. Model prose is never released, even
when the model's choice agrees.

## Execution and reproducibility

- 24 model calls, no new LLM extraction, no application retries or prompt tuning.
- Gateway-reported experiment cost: **$0.0106028**, with no missing cost fields.
  Council calls are additional.
- Recorded usage: 12,890 prompt tokens and 4,315 completion tokens. These are descriptive
  counters, not proof of independent uncached samples or an efficiency comparison.
- All **201 evidence-context tests passed**, including 28 Stage 11 tests. Tests challenge
  grammar edges, source/target locator swaps, mutation after snapshot creation, stale
  bindings, false blocks, bounded failures and replay. The forged-artifact test documents
  that source authenticity is still unverified.
- Frozen protocol, case labels, prompt and code fingerprints were written before the
  live calls. Original private files retain hashes; the readable frozen copy omits hash
  values. Current gate/runner/policy source still matches the executed fingerprints.
- Saved HTML is a viewer over actual observations. It does not rescore or call a model.
  Separate reference and replay commands are documented in GUIDE.md.

No sessions.db data, capture configuration, earlier exercises or production code were
changed. The shared-memory database engine remains an open decision.

The secret scanner flagged source/target content digests in saved JSON. Each of the
26 findings was verified by recomputing the digest from its synthetic source or target
and matching the scanner fingerprint. Only those exact findings were added as audited
non-secrets in .secrets.baseline; no detector or exclusion rule was weakened.
