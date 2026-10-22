"""Run trufflehog and print findings WITHOUT the secret values.

trufflehog's default output prints the raw matched secret. That is the one
thing a pre-commit hook must never echo into a terminal, a CI log or an agent
transcript. This wrapper consumes trufflehog's ``--json`` stream and prints
only the detector, verification state, commit, file and line -- never ``Raw``
or ``RawV2`` -- and exits non-zero when anything was found.

Exit codes: 0 clean, 1 findings, 2 scanner error. Output this wrapper cannot
read (a stdout line that is not a finding object, or trufflehog's ``--fail``
code 183 with no parsed finding) is a scanner error, never a clean result, and
the unreadable lines are not echoed because they may carry the raw match.

Usage (from the repo root)::

    uv run python scripts/security/trufflehog_redacted.py            # staged changes; by hand also
                                                                   # commits not reachable from HEAD
    uv run python scripts/security/trufflehog_redacted.py --history  # whole git history
    uv run python scripts/security/trufflehog_redacted.py --base origin/main --head HEAD
                                                                     # a pull request's commits

The no-flag mode passes ``--since-commit=HEAD`` and no ``--branch``; what that
scans depends on who runs it. Under pre-commit, which sets ``PRE_COMMIT=1`` for
every hook run, trufflehog overrides both ends of the range to HEAD, so the
commit hook scans the staged changes and nothing else. Run by hand, a base
with no head is ``git log --all ^HEAD``: the staged changes plus every commit
on any ref that is not reachable from HEAD (an unmerged branch, a stash). More
findings, never fewer -- a by-hand run can fail where the hook passed, and
that is the stricter scan, not a bug. (trufflehog 3.99.3: ``main.go``
``isPreCommitHook`` override; ``gitparse.go`` ``RepoPath``, "a base-only scan
is ``--all ^base``".)

``--base``/``--head`` scan exactly the commits in ``base..head`` -- what CI's
pull-request step scans (``.github/workflows/ci.yml``, job ``secrets``), but
with all three result types, so it is the stricter of the two. Both ends must
resolve to commits in this clone; a missing, all-zero or unresolvable end, or
an empty range, is exit 2 before anything is scanned -- never a fallback to the
``--since-commit=HEAD`` scope (in CI that is HEAD..HEAD: nothing scanned, a
silent pass) or to a whole-history walk. ``--check-range`` performs only that
check and needs no trufflehog binary: it is CI's fail-closed guard in front of
the official action.

Findings are reported as ``verified`` (the credential authenticated against
its provider), ``unknown`` (could not attempt verification) or ``unverified``
(verification attempted and failed -- e.g. a revoked or fake key). All three
fail the hook: a revoked key still tells an attacker the shape of a real one.
trufflehog's own allowlist already drops AWS's documented sample access key,
so that fixture is never a finding. Verified 2026-09-15: a planted ``ghp_``
token in the index is caught with ``--since-commit=HEAD``; it was silently
dropped when ``unverified`` was not requested.

That last point rests on an upstream ordering quirk (ADR-0018, consequences).
Under ``PRE_COMMIT=1`` trufflehog means to narrow results to
``verified,unknown`` (``main.go``, ``isPreCommitHook``), but at 3.99.3 that
override runs after ``--results`` was parsed into the engine, so this
wrapper's ``--results=verified,unknown,unverified`` stands and the hook fails
on a revoked key. If upstream moves the override, the hook silently stops
failing on revoked or fake keys. ``test_trufflehog_pinned_image.py`` pins the
contract against the pinned release: a planted revoked-shape key under
``PRE_COMMIT=1`` must still be reported as ``state=unverified`` and exit 1.
"""

from __future__ import annotations

import argparse
import collections
import json
import shutil
import subprocess
import sys

REDACT_KEYS = {"Raw", "RawV2", "Redacted"}


class RangeError(ValueError):
    """A pull-request range that cannot be scanned as given."""


def _resolve_commit(ref: str | None) -> str | None:
    """Return the full SHA of the commit ``ref`` names in the repository here.

    Anything git cannot resolve to a commit is ``None``: git's all-zero "no
    commit" placeholder, a SHA a shallow clone never fetched, a typo. Empty and
    option-shaped values are refused before git sees them.
    """
    if not ref or not ref.strip() or ref.startswith("-"):
        return None
    proc = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"],
        capture_output=True,
        text=True,
        check=False,
    )
    sha = proc.stdout.strip()
    return sha if proc.returncode == 0 and sha else None


def _pr_range(base: str | None, head: str | None) -> tuple[str, str]:
    """Resolve a pull request's ``base..head`` to two distinct commits.

    Raises :class:`RangeError` rather than returning anything that would scan
    less than the range: a scan of the wrong range that finds nothing reads
    exactly like a clean pull request.
    """
    base_sha = _resolve_commit(base)
    if base_sha is None:
        raise RangeError(
            f"no usable base commit ({base!r}) -- the pull request's base must be a commit "
            "in this clone (CI checks out with fetch-depth: 0)"
        )
    head_sha = _resolve_commit(head)
    if head_sha is None:
        raise RangeError(f"no usable head commit ({head!r})")
    if base_sha == head_sha:
        raise RangeError(f"base and head are the same commit ({base_sha[:10]}): empty range")
    return base_sha, head_sha


def _mapping(value: object) -> dict:
    return value if isinstance(value, dict) else {}


def _rows(stream: str) -> tuple[list[dict], int]:
    """Parse trufflehog's ``--json`` stdout into redacted finding rows.

    Returns the rows and the number of nonblank lines that were NOT a finding
    object. trufflehog 3.x writes exactly one finding object per stdout line and
    sends its logs to stderr (checked against 3.99.2), so any such line means
    the output format changed under this wrapper: the scan cannot be read as
    clean, and the caller fails closed.
    """
    findings: list[dict] = []
    unrecognised = 0
    for line in stream.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            unrecognised += 1
            continue
        if not isinstance(item, dict) or "DetectorName" not in item:
            unrecognised += 1
            continue
        git = _mapping(_mapping(_mapping(item.get("SourceMetadata")).get("Data")).get("Git"))
        findings.append(
            {
                "detector": item.get("DetectorName", "?"),
                "state": _state(item),
                "commit": str(git.get("commit", ""))[:10],
                "file": git.get("file", ""),
                "line": git.get("line", ""),
            }
        )
    return findings, unrecognised


def _state(item: dict) -> str:
    """Sort a finding the way trufflehog's own ``--results`` filter does.

    engine.go at the pinned commit: ``Verified`` true is ``verified``; false
    with a ``VerificationError`` is ``unknown`` (the provider could not be
    asked -- no network, a timeout); false without one is ``unverified`` (the
    provider was asked and said no: a revoked or fake key). Only the word is
    kept; the error text may name an endpoint or carry a redacted hint.
    """
    if item.get("Verified"):
        return "verified"
    if item.get("VerificationError"):
        return "unknown"
    return "unverified"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--history", action="store_true", help="scan the whole git history (default: since HEAD)"
    )
    parser.add_argument("--base", help="pull-request scan: the commit the PR is based on")
    parser.add_argument("--head", help="pull-request scan: the PR's head commit")
    parser.add_argument(
        "--check-range",
        action="store_true",
        help="only check that --base..--head is a scannable range (no trufflehog needed)",
    )
    parser.add_argument("--max-rows", type=int, default=50)
    args = parser.parse_args(argv)

    pr_range: tuple[str, str] | None = None
    if args.base is not None or args.head is not None or args.check_range:
        try:
            if args.history:
                raise RangeError("--history and a --base/--head range are different scans")
            pr_range = _pr_range(args.base, args.head)
        except RangeError as exc:
            print(f"trufflehog PR scan refused: {exc}", file=sys.stderr)
            return 2
        if args.check_range:
            print(f"PR range ok: {pr_range[0][:10]}..{pr_range[1][:10]}")
            return 0

    binary = shutil.which("trufflehog")
    if binary is None:
        print("trufflehog is not installed (mise/brew install trufflehog)", file=sys.stderr)
        return 2

    cmd = [
        binary,
        "git",
        "file://.",
        "--results=verified,unknown,unverified",
        "--no-update",
        "--json",
        # Exit 183 when anything was found: a signal that does not depend on
        # this wrapper parsing the JSON, so 183 with no parsed row is caught.
        "--fail",
    ]
    if pr_range is not None:
        cmd += [f"--since-commit={pr_range[0]}", f"--branch={pr_range[1]}"]
    elif not args.history:
        cmd.append("--since-commit=HEAD")
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    findings, unrecognised = _rows(proc.stdout)

    if proc.returncode not in (0, 183) and not findings:
        # 0 = clean, 183 = findings (--fail); anything else is a tool error.
        print(f"trufflehog exited {proc.returncode}: {proc.stderr[-800:]}", file=sys.stderr)
        return 2

    if unrecognised or (proc.returncode == 183 and not findings):
        # Never echo the unreadable lines: they may carry the raw match.
        print(
            "trufflehog output not recognised -- failing closed: "
            f"{unrecognised} stdout line(s) were not a finding object, "
            f"{len(findings)} finding(s) parsed, trufflehog exit {proc.returncode}. "
            "Check the installed trufflehog version against this wrapper.",
            file=sys.stderr,
        )
        return 2

    by = collections.Counter((f["detector"], f["state"]) for f in findings)
    scope = "history" if args.history else "since HEAD"
    if pr_range is not None:
        scope = f"PR range {pr_range[0][:10]}..{pr_range[1][:10]}"
    print(f"trufflehog findings: {len(findings)} ({scope})")
    for (det, state), count in by.most_common():
        print(f"  {count:>4}  {det}  state={state}")
    for f in findings[: args.max_rows]:
        where = f"{f['file']}:{f['line']}"
        print(f"  - {f['detector']:<26} state={f['state']:<10} {f['commit']} {where}")
    if len(findings) > args.max_rows:
        print(f"  … {len(findings) - args.max_rows} more")
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
