# ADR-0018: trufflehog in CI scans each pull request's own range, pinned and fail-closed

**Status:** Accepted, 2026-10-22 (proposed and implemented the same day; the owner accepted the
eight pass-3 records together at 16:36 BST) · **Date:** 2026-10-22 · **Deciders:** council pass 3
of the 2026-10-21 full-repository review (five no-tool seats: kimi-k3, gpt-6-astra, grok-4.6,
deepseek-r1, mistral-large-3), arbitrated by argument by the review coordinator under the owner's
standing delegation; accepted by Andy Taylor (owner). · **Change:** 2026-10-22 council pass 3, ruling D6 (5–0); implemented in `a5a17045`
(step, wrapper, tests) and `8965206d` (history triage), merge `659fea3a` (lane H,
`ci-trufflehog-pr`). Operating reference: `docs/security/trufflehog-ci.md`.

The council record (`reviews/2026-10-21-full-repo-review/`, gitignored, owner's machine only)
holds the seat transcripts; everything this record relies on is restated here. Symbols were read
at `309074c7`.

## Context

Secret scanning ran in two places that did not match. At commit time, `.pre-commit-config.yaml`
runs trufflehog over staged changes through `scripts/security/trufflehog_redacted.py`, which prints
detector, file and line and never the secret, and which the review's lane 7 made fail closed (an
unparseable or empty scanner result is a scanner error, exit 2). In CI, the `secrets` job ran the
same pre-commit **secret hooks** server-side (detect-secrets against the baseline,
detect-private-key, detect-aws-credentials) with pinned action SHAs, but **not trufflehog**, so the
one scanner with provider-specific detectors and live verification was advisory only: git treats
client-side hooks as the committer's choice.

Lane 7 had measured why no obvious CI mode worked: `--history` on the clean tree reported 13
unverified findings, 11 of them in vendored JavaScript and review receipts, so a full-history scan
could not be green without an exclude list; and trufflehog's default `--since-commit=HEAD` is
always empty in CI. A meaningful mode needs a base reference and a pinned binary.

The brief's option (a) was mislabelled "detect-secrets-only"; CI already ran three hooks. One seat
caught that and the ruling records it.

## Decision

A **pull-request-scoped** trufflehog step in the `secrets` job:

- Trigger `pull_request`; job `permissions: contents: read`; `actions/checkout` with
  `fetch-depth: 0` because `base..head` needs both ends in the clone.
- **Fail closed on a missing base.** The official action does not fail when `base` is empty; it
  scans the whole history instead. So a guard step runs first:
  `trufflehog_redacted.py --check-range --base <sha> --head <sha>` exits 2 on an empty, identical
  or unknown SHA and 0 on a genuine range. The step never degrades to `HEAD..HEAD`.
- The action pinned **by commit SHA** (`e63326d6545de8f425d93ce24078c6e68d83f70e`, tag `v3.99.3`,
  resolved from two sources and confirmed a third way with `git ls-remote`), **and** the scanner
  image pinned by digest, because the action's `version` input defaults to `latest`. A contract
  test requires both pins and requires the image version to match the tag in the comment.
- Results `--results=verified,unknown`, **without** `--only-verified`. The ruling as written asked
  for both; the lane ran the pinned image and showed trufflehog **replaces** `--results` with
  `verified` whenever `--only-verified` is set, so the pair would have passed on a planted token.
  The ruling's intent (verified plus unknown) is kept; its flag text was wrong and a contract test
  pins the corrected form.
- Output goes through the action's redacted annotations; raw secret bytes never reach the log.
- The 13 history findings got a **one-time triage**, recorded in
  `docs/security/trufflehog-ci.md` by detector, file and line only: four are receipt digests where
  the detector keyword "phrase" matched inside "paraphrase", two are URL-rejection test fixtures
  with placeholder credentials, two are the scrubber's own MongoDB fixtures, one is a code comment
  whose host is literally `host`, four are base64 inside vendored minified JS. None is plausibly a
  live credential.

Grounding adopted: trufflehog's own documented CI pattern (scan the PR range), and git's position
that client-side hooks are advisory, so the gate that matters is the server-side one.

## Alternatives considered

- **(a) Keep CI as it was (the three hooks); trufflehog at commit time only; document the
  split.** Rejected 5–0: it leaves the strongest scanner advisory, and a `--no-verify` or a clone
  with a foreign `core.hooksPath` bypasses it silently.
- **(c) Full-history trufflehog in CI with an exclude file for the vendored and receipt paths,
  after triaging the remaining findings.** Rejected: the exclude list is maintenance that grows
  with every receipt, and a full-history scan on every run re-finds the same triaged history. The
  triage was done anyway, once, so (c) stays cheap to adopt later if the owner wants it.

## Consequences

- **Direct pushes to `main` are not range-scanned**; the step runs on pull requests, by the
  ruling's scope. Owner pushes rely on the commit-time hook and detect-secrets in CI.
- **Hosted execution is unproven** until the owner pushes: the workflow was checked by YAML parse
  and contract tests; `actionlint` is not installed here. The first pull request's `secrets` job is
  the first real run and should be watched.
- Moving to a new trufflehog release means resolving two pins from two sources each
  (`docs/security/trufflehog-ci.md` §Pins gives the commands); the contract test refuses a
  half-moved pin.
- The commit-time hook's ability to catch a revoked key depends on an ordering quirk inside
  trufflehog that upstream could change (ledgered); the CI step's `unknown` results are the
  backstop.
- The wrapper's no-flag docstring says "staged changes" but it also walks commits unreachable from
  `HEAD`; that fails closed (more findings, never fewer) and is a docstring fix (ledgered).

*Amendment, 2026-10-22 (plan 4, lane M, merged `e1692522`): the two ledgered items above are
closed. `test_trufflehog_pinned_image.py` (marker `integration`) runs the pinned 3.99.3 image under
`PRE_COMMIT=1` against a planted revoked-shape key and goes red if the ordering quirk moves; the CI
step's `unknown` results remain the backstop. The wrapper's docstring now states both scopes: under
pre-commit the staged changes only, by hand also commits not reachable from `HEAD`. `actionlint`
1.7.12 (scratch install, not added to CI) reports no findings on the four workflows, and the
`audit-full` job now pins `pip-audit` and uses `runner.temp` like `audit`. Hosted execution is
still unproven until the owner pushes.*

## Verification

`packages/studyloop/tests/test_ci_workflow_contract.py`: the step exists, is pinned by a 40-hex
SHA and an image digest that match the commented tag, has read-only permissions, uses
`fetch-depth: 0`, carries no `--since-commit=HEAD`, and passes `--results=verified,unknown`
without `--only-verified`. `test_trufflehog_redacted.py`: a missing, identical or unknown base
exits 2 with a clear message; a scanner error still exits 2; a parsed finding exits 1. Coordinator
check: the action SHA resolved to `v3.99.3` by `git ls-remote` against upstream; `--check-range`
exercised by hand on each refusal case and one genuine range.
