#!/usr/bin/env bash
# openspec-cli.sh — the ONE place that decides which OpenSpec CLI runs.
#
# Usage: scripts/openspec-cli.sh <openspec args…>
#
# Resolution (plan 7, ARBITRATION-pass9.md §4 Q4/Q6, §8.2 R4):
#   1. A local `openspec` on PATH is used ONLY if `openspec --version` equals the pin
#      ($OPENSPEC_VERSION, exported by the Justfile). A different version is REFUSED — a validator
#      at another release may apply other rules, so its "pass" would be about a different contract.
#   2. Otherwise `npx --yes @fission-ai/openspec@$OPENSPEC_VERSION` (exact top-level pin; the
#      package's own dependencies float on caret ranges — the same residual the repo accepts for
#      `uv tool run pip-audit@…`).
#   3. If neither can run: on a contributor's machine print SKIPPED and exit 0 — a gate that fails for
#      a reason nobody is working on teaches people to ignore it (Justfile, release-check notes) —
#      but under CI ($CI set, as GitHub sets it) exit 1: a skip is not a pass, and CI is where the
#      gate is enforced.
#
# Fetch is separated from validate: `--version` is run first so an environmental failure (no node,
# npx cannot resolve) is reported as such, and the validation's own exit code is the gate.
#
# OPENSPEC_TELEMETRY=0 is set so an npx-fetched CLI does not start reporting usage from a machine
# whose owner never installed openspec. OPENSPEC_NO_NPX=1 disables step 2 (tests use it to stay
# offline).

set -euo pipefail

: "${OPENSPEC_VERSION:?OPENSPEC_VERSION must be set (the Justfile exports it)}"
export OPENSPEC_TELEMETRY=0

pointer="see docs/contributor-conventions.md § OpenSpec"

run_local() {
    local found
    found="$(openspec --version 2>/dev/null | tr -d '[:space:]' || true)"
    if [[ -z "$found" ]]; then
        echo "openspec-cli: a local openspec is on PATH but printed no version; ignoring it" >&2
        return 1
    fi
    if [[ "$found" != "$OPENSPEC_VERSION" ]]; then
        echo "openspec-cli: local openspec is $found but the repository pins $OPENSPEC_VERSION;" >&2
        echo "openspec-cli: refusing to use it (uninstall it, or install $OPENSPEC_VERSION); $pointer" >&2
        exit 2
    fi
    exec openspec "$@"
}

run_npx() {
    if [[ -n "${OPENSPEC_NO_NPX:-}" ]]; then
        return 1
    fi
    if ! command -v npx >/dev/null 2>&1; then
        return 1
    fi
    # fetch first: an unresolvable package is environmental, not a validation result
    if ! npx --yes "@fission-ai/openspec@$OPENSPEC_VERSION" --version >/dev/null 2>&1; then
        return 1
    fi
    exec npx --yes "@fission-ai/openspec@$OPENSPEC_VERSION" "$@"
}

if command -v openspec >/dev/null 2>&1; then
    run_local "$@" || true   # a matching binary execs; a mismatch exits 2; a silent one falls through
fi

run_npx "$@" || true

if [[ -n "${CI:-}" ]]; then
    echo "openspec-cli: openspec $OPENSPEC_VERSION is not available (no matching local binary, npx unavailable);" >&2
    echo "openspec-cli: CI enforces this gate, so absence is a failure; $pointer" >&2
    exit 1
fi

echo "SKIPPED — NOT VERIFIED: openspec $OPENSPEC_VERSION is not available on this machine (CI enforces it); $pointer"
exit 0
