# trufflehog in CI

The commit gate runs trufflehog on staged changes through
`scripts/security/trufflehog_redacted.py`, but only on a machine where a contributor installed
and kept the hook. The `secrets` job in `.github/workflows/ci.yml` runs it server-side on every
pull request (review pass 3, ruling D6).

> **Unproven on a hosted runner.** Everything below was checked against the action's source at the
> pinned commit and by running the pinned image locally with the action's own arguments. None of
> it has run on GitHub yet; the first pull request after this merges is the first real run.

## What runs

On a `pull_request` event, after the detect-secrets hooks:

1. **Range guard.** `trufflehog_redacted.py --check-range --base "$PR_BASE" --head "$PR_HEAD"`,
   with the two SHAs taken from the PR event through `env`. It exits 2, failing the job, unless
   both are commits in the clone and differ. The action does not do this itself: given an empty
   `base` it scans the head's whole history instead.
2. **Scan.** The official `trufflesecurity/trufflehog` action, pinned by commit, scans
   `base..head` (the PR's own commits) with `--results=verified,unknown`. Any result fails the job
   (trufflehog's `--fail`, exit 183).

The job has `permissions: contents: read`, checks out with `fetch-depth: 0` (both ends of the
range must be in the clone) and `persist-credentials: false` (the scanner container mounts the
whole workspace, so the job token stays out of the checkout's git config).

## What it reports, and what it does not

- Results are GitHub annotations: detector, file and line. The action's `--github-actions` printer
  never prints the matched value.
- **`verified`** (the credential authenticated against its provider) and **`unknown`** (the
  scanner could not verify it) fail the job.
- **`unverified`** results (verification ran and failed, for example a revoked or fake key) are
  not reported in CI. The commit-time hook still fails on them, because it asks for all three
  result types. That holds because of an ordering quirk in trufflehog's `PRE_COMMIT` override
  (ADR-0018); `test_trufflehog_pinned_image.py` runs the pinned release against a planted
  revoked-shape key to prove it, and goes red if upstream moves the quirk.
- `--only-verified` is deliberately absent. trufflehog replaces `--results` with `verified`
  whenever `--only-verified` is set, so the pair would drop every `unknown` result. A local run of
  the pinned image showed it: on a planted token, the pair exited 0, while `--results` on its own
  exited 183.
- Pushes straight to `main` are not range-scanned. The ruling scoped this step to pull requests.

## Pins

| What | Pinned to | Why both |
|---|---|---|
| Action | commit `e63326d6545de8f425d93ce24078c6e68d83f70e` (tag `v3.99.3`) | a tag can be moved |
| Scanner image | `3.99.3@sha256:63b6120f410beb64aea4e421f1ed277248e14b2942d124df289422b623f610d8` | the action's `version` input defaults to `latest` |

A contract test (`packages/studyloop/tests/test_ci_workflow_contract.py`) requires both pins, and
requires the image version to match the tag in the action line's comment. To move to a new
release `vX.Y.Z`, resolve each pin from two sources before editing:

```bash
gh api repos/trufflesecurity/trufflehog/git/ref/tags/vX.Y.Z --jq .object   # must be type "commit"
git ls-remote https://github.com/trufflesecurity/trufflehog.git refs/tags/vX.Y.Z
```

The image digest is the `Docker-Content-Digest` of the ghcr manifest for tag `X.Y.Z` (no `v`).
`docker pull ghcr.io/trufflesecurity/trufflehog:X.Y.Z` prints it as `Digest:`.

## Reproduce a PR scan locally

```bash
uv run --group dev python scripts/security/trufflehog_redacted.py --base origin/main --head HEAD
```

This scans the same `base..head` range through the redacting wrapper. It is stricter than CI,
because it also fails on `unverified` results.

## History triage (one-time, 2026-10-22)

Running `trufflehog_redacted.py --history` on `main` at `6db996b3` reports 13 findings, so it
exits 1. None is `verified`. Each one was identified by detector, file, line and the structure
of the match. The values themselves were never printed. **None is a credential**, and none needs
rotating. The PR-scoped step does not look at history, so these findings do not affect it.

| Detector | Where (file:line at the finding's commit) | Count | Disposition |
|---|---|---|---|
| PhraseAccessToken | `docs/architecture/session-memory/receipts/paraphrase-census.json:3`, `paraphrase-census-v2.json:3` | 4 (2 files × 2 commits) | **False positive.** The value is the receipt's `store_sha256`: 64 lowercase hex, a content digest. The detector fired on the keyword "phrase" inside "paraphrase". |
| URI | `packages/studyloop/tests/test_second_brain_config.py:195` | 1 | **Test fixture.** The `unsafe-userinfo` case of a parametrised test that must *reject* credentials in an xTiles URL. The username and password are placeholder words. Verification ran and failed. |
| URI | `docs/superpowers/plans/2026-09-04-second-brain-launcher.md:137` | 1 | **Documentation example.** The plan's sketch of the same rejection test. The username and password are placeholder words. |
| MongoDB | `packages/agent-session-tools/tests/test_scrubber.py:104` (now `:117`) | 2 (plain, and base64-decoded in an earlier commit) | **Test fixture.** The positive-match string in `test_connection_string_mongodb`, which checks that the scrubber's connection-string pattern fires. The username is a placeholder and the password is two dictionary words, on a synthetic host. Verification could not connect, so the state is `unknown`. |
| Postgres | `packages/studyloop/src/studyloop/session/child_env.py:34` at `2515d50f` | 1 | **Code-comment example.** A comment explaining why `DATABASE_URL` is withheld from agent children. Its username, password and host are placeholder words (the host is literally `host`). The text is gone from HEAD. |
| Box | `…/web/static/vendor/js/ghostty-web-0.4.0.js:1`, `ghostty-web-0.4.0.umd.js:1`, `phonemizer-1.2.1.js:1` | 4 | **False positive in vendored third-party bundles.** These are 32-character runs inside base64 data blobs in minified JS. None of them is at HEAD. |

The review brief called two of these findings "non-vendored". By file, nine are non-vendored, at
six sites. All 13 were triaged here.
