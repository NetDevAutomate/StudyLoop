# Ruler amendment 002 — gold v2 provenance re-certified with reproducible hashes

**Trigger:** the two-family validity council on `stage-d-look1-b1clean.json` (seat gpt-5.6-terra,
run `4ed818c7`) returned VOID on four provenance findings. The ruler makes council findings
leads until verified against the artefact; the orchestrator verified each. This amendment records
the outcome. **The frozen ruler is not edited.** No gate threshold, statistic, look count or
stop rule changes.

## What the council found, and what verification showed

| # | Finding | Verified? | Disposition |
|---|---|---|---|
| F1 | `candidate_commit` equals, not postdates, the fusion-spec commit | True: the look ran at HEAD `690a37d4`, the commit that *added* the spec, so declaration and code are the same commit. The receipt (`ca55c653`) postdates both. | **Not a void condition.** The ruler requires the spec to be versioned *before the first DEV look*; a spec committed at T and a look run at T+10 s from that HEAD satisfies it. Receipts now also record `fusion_spec.declared_commit` (the commit that added the spec file) so the ordering is mechanical. |
| F2 | No `fusion_spec_version` field on the receipt | True; the harness never wrote one. | **Accepted.** `score.py` now records `fusion_spec.{path, sha256, declared_commit}` on every receipt. |
| F3 | `gold-v2-receipt.json` `dev.sha256` (`eeca2aaf…`) does not identify the DEV file (`5632cd2b…`) | True — and worse than the seat knew: `sealed.sha256` (`459723c0…`) does not match the SEALED file either (`90ef67ad…`). Neither reproduces under 384 serialisations of the respective file. | **Accepted as a Stage 2 record defect.** Both hashes were computed by an in-session script that was not preserved. |
| F4 | `corpus_digest` `a0df30bb…` (gold receipt) ≠ `9aa2b495…` (result receipts); the ruler voids on mismatch | True. `a0df30bb…` does not reproduce from *any* surviving artefact (DEV∪SEALED files, the 175-item admitted bundle, the 216 candidates, with/without cluster ids, with/without the schema trailer). | **Accepted; cannot be overridden** — the evidence that would refute it does not exist. |
| F5 | B1-vs-B0 non-inferiority recorded per stratum only, not on the aggregate | True. | **Accepted.** `non_inferiority_macro` added; every comparison now records the aggregate first. |
| F6 | The measured intervention bundles planner + index; scope filter differs | Partly. `visibility_sql` excludes **0 of 5,879** sessions on the live DB, so scope is not a confound. Planner vs index *is* bundled. | **Accepted as a measurement question**, answered by a control arm (`B1_planner`: shipped index, new planner only) declared in fusion-spec v1.1 and scored in look 2. |
| F10 | Store provenance not bound into the receipt; `KNOWLEDGE_PROOF_STORE` can redirect the arm | True. | **Accepted.** `--store` records the store file's sha256 and size on the receipt. |

## Is the gold data intact?

Yes, on four independent checks: the DEV file is byte-identical to its first commit
(`d83b3b41`); the SEALED file's mtime is `2026-09-10T00:17:52Z`, the certification instant to
the second, and its mode is `0400`; **zero** of the 114 gold sessions' messages carry a timestamp
after Stage 2 authoring and none are missing from the DB; and the whole-gold digest computed over
DEV ∪ SEALED (`0c29ba96…`) equals the digest computed independently over the 175-item admitted
bundle in scratch. The item sets did not change. The *record* of them did not reproduce.

## What this amendment does

1. Issues `receipts/gold-v2-receipt-r2.json`, produced by `scripts/knowledge_proof/recertify_gold.py`
   (method in its docstring; anyone holding the two files and the DB can recompute every value):
   `dev.sha256 = 5632cd2b…`, `sealed.sha256 = 90ef67ad…`, `corpus_digest.dev = 9aa2b495…`,
   `corpus_digest.sealed = 965f5b1e…`, `corpus_digest.whole = 0c29ba96…`, drift check embedded.
2. Declares the **matching rule** the ruler's clause is read under from here on: a DEV receipt's
   `corpus_digest` must equal `corpus_digest.dev`; the single SEALED receipt's must equal
   `corpus_digest.sealed`. Both live in r2 so the check is mechanical.
3. Marks `gold-v2-receipt.json` **superseded for provenance** (its admission counts, strata,
   rejection reasons and split rule remain the record of *how* the gold was built).
4. Voids `stage-d-look1-b1clean.json` as the seat required; **look 1 is still counted** against the
   G1 family's four DEV looks (the number was seen). Look 2 re-scores the same arms plus the
   `B1_planner` control under the corrected harness; identical numbers for B0/B1/B1_clean are the
   regression check that the harness edits changed no statistic.

## Lesson recorded

Provenance hashes are computed by a committed script or they are not provenance. The Stage 2
split ran in-session and the script was lost; every hash in this programme is now produced by a
file under `scripts/knowledge_proof/`.
