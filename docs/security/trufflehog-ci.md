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
  result types.
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
