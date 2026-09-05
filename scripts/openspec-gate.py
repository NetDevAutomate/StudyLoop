#!/usr/bin/env python3
"""OpenSpec early-warning hook — one body, three harness wrappers.

EARLY WARNING, NOT ENFORCEMENT. The hard gate is `just release-check`
(scripts/check-release-consistency.py --release) plus CI; this hook exists so
a release action is questioned at the keyboard instead of failing twenty
minutes later. Per the 2026-09-04 arbitration (Q5 step 3), and per its own
caution: a hook that cannot be shown to block must not be described as
enforcement. Verification state of the block mechanism, per harness:

* Kiro CLI      — VERIFIED against the harness's own hook documentation
                  (PreToolUse, exit 2 blocks; stderr forwarded).
* Claude Code   — DOCUMENTED by the vendor (PreToolUse, exit 2 blocks);
                  not attested by a recorded run in this repository.
* Codex         — events VERIFIED against the vendor hooks page in the
                  2026-09-04 review; the exit-2 block is documented there.

Behaviour (stdin carries the tool-call JSON; all three harnesses use the
``tool_input.command`` shape for their shell tool):

* ``git tag …`` or ``prepare-release`` → run the REAL release guard
  (imported from check-release-consistency.py, never a re-implementation);
  exit 2 with the guard's message when an openspec change with commits since
  the last tag is neither archived nor deferred.
* ``git commit …`` → same check, but WARN on stdout and exit 0: open changes
  are legal during a cycle, so a commit is never blocked.
* anything else → exit 0 immediately, no subprocess spawned.
* ``remind`` mode (UserPromptSubmit) → one terse line when the guard would
  fail, silence otherwise; always exit 0.

Fails OPEN on its own errors (exit 0): a broken early warning must never
block work the hard gate would allow.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from pathlib import Path

_RELEASE_RE = re.compile(r"\bgit\s+tag\b|\bprepare-release\b")
_COMMIT_RE = re.compile(r"\bgit\s+commit\b")


def _load_release_guard(repo_root: Path):
    """Import validate_openspec_changes_shipped from the real gate script.

    Imported, never copied: two implementations of "what counts as shipped"
    is how a hook and a release gate come to disagree.
    """
    path = repo_root / "scripts" / "check-release-consistency.py"
    spec = importlib.util.spec_from_file_location("_release_consistency", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.validate_openspec_changes_shipped


def _guard_failure(repo_root: Path) -> str | None:
    """The release guard's message when it would fail, else None."""
    try:
        _load_release_guard(repo_root)(repo_root)
    except ValueError as exc:
        return str(exc)
    return None


def _command_from_stdin() -> str:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return ""
    tool_input = payload.get("tool_input") or payload.get("toolInput") or {}
    if isinstance(tool_input, dict):
        return str(tool_input.get("command", ""))
    return ""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "mode", nargs="?", default="pre-tool-use", choices=["pre-tool-use", "remind"]
    )
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    repo_root = args.repo_root.resolve()

    try:
        if args.mode == "remind":
            failure = _guard_failure(repo_root)
            if failure:
                print(f"openspec early warning: {failure}")
            return 0

        command = _command_from_stdin()
        if _RELEASE_RE.search(command):
            failure = _guard_failure(repo_root)
            if failure:
                print(
                    f"openspec gate: {failure}\n"
                    "(early warning; the hard gate is `just release-check`)",
                    file=sys.stderr,
                )
                return 2
            return 0
        if _COMMIT_RE.search(command):
            failure = _guard_failure(repo_root)
            if failure:
                # Warn only: open changes are LEGAL during a cycle. Blocking
                # commits would gate normal work on a release-time rule.
                print(f"openspec reminder (not blocking): {failure}")
            return 0
        return 0
    except Exception as exc:  # fail OPEN — see module docstring
        print(f"openspec gate skipped (internal error: {exc})", file=sys.stderr)
        return 0


if __name__ == "__main__":
    sys.exit(main())
