"""Run trufflehog and print findings WITHOUT the secret values.

trufflehog's default output prints the raw matched secret. That is the one
thing a pre-commit hook must never echo into a terminal, a CI log or an agent
transcript. This wrapper consumes trufflehog's ``--json`` stream and prints
only the detector, verification state, commit, file and line -- never ``Raw``
or ``RawV2`` -- and exits non-zero when anything was found.

Usage (from the repo root)::

    uv run python scripts/security/trufflehog_redacted.py            # staged/uncommitted changes
    uv run python scripts/security/trufflehog_redacted.py --history  # whole git history

Findings are reported as ``verified`` (the credential authenticated against
its provider), ``unknown`` (could not attempt verification) or ``unverified``
(verification attempted and failed -- e.g. a revoked or fake key). All three
fail the hook: a revoked key still tells an attacker the shape of a real one.
trufflehog's own allowlist already drops AWS's documented sample access key,
so that fixture is never a finding. Verified 2026-09-15: a planted ``ghp_``
token in the index is caught with ``--since-commit=HEAD``; it was silently
dropped when ``unverified`` was not requested.
"""

from __future__ import annotations

import argparse
import collections
import json
import shutil
import subprocess
import sys

REDACT_KEYS = {"Raw", "RawV2", "Redacted"}


def _rows(stream: str) -> list[dict]:
    findings: list[dict] = []
    for line in stream.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if "DetectorName" not in item:
            continue
        git = ((item.get("SourceMetadata") or {}).get("Data") or {}).get("Git") or {}
        findings.append(
            {
                "detector": item.get("DetectorName", "?"),
                "verified": bool(item.get("Verified")),
                "commit": str(git.get("commit", ""))[:10],
                "file": git.get("file", ""),
                "line": git.get("line", ""),
            }
        )
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--history", action="store_true", help="scan the whole git history (default: since HEAD)"
    )
    parser.add_argument("--max-rows", type=int, default=50)
    args = parser.parse_args(argv)

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
    ]
    if not args.history:
        cmd.append("--since-commit=HEAD")
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    findings = _rows(proc.stdout)

    if proc.returncode not in (0, 183) and not findings:
        # 183 is trufflehog's "findings present" code when --fail is used; we
        # do not pass --fail, so anything non-zero here is a tool error.
        print(f"trufflehog exited {proc.returncode}: {proc.stderr[-800:]}", file=sys.stderr)
        return 2

    by = collections.Counter((f["detector"], f["verified"]) for f in findings)
    scope = "history" if args.history else "since HEAD"
    print(f"trufflehog findings: {len(findings)} ({scope})")
    for (det, ver), count in by.most_common():
        print(f"  {count:>4}  {det}  verified={ver}")
    for f in findings[: args.max_rows]:
        verified = "yes" if f["verified"] else "no"
        where = f"{f['file']}:{f['line']}"
        print(f"  - {f['detector']:<26} verified={verified:<3} {f['commit']} {where}")
    if len(findings) > args.max_rows:
        print(f"  … {len(findings) - args.max_rows} more")
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
