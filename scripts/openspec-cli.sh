#!/usr/bin/env bash
# openspec-cli.sh — the ONE place that decides which OpenSpec CLI runs.
#
# Usage: scripts/openspec-cli.sh <openspec args…>
#
# Resolution (plan 7, ARBITRATION-pass9.md §4 Q4/Q6, §8.2 R4; order revised by pass 10 Q3):
#   1. A local `openspec` on PATH is used ONLY if `openspec --version` equals the pin
#      ($OPENSPEC_VERSION, exported by the Justfile). A validator at another release applies other
#      rules, so its "pass" would be about a different contract: a mismatched binary is never used.
#   2. Otherwise `npx --yes @fission-ai/openspec@$OPENSPEC_VERSION` validates the pinned contract in
#      the same command (exact top-level pin; the package's own dependencies float on caret ranges —
#      the residual the repo also accepts for `uv tool run pip-audit@…`). When a mismatched local
#      binary was bypassed, one stderr line says so, naming both versions.
#   3. npx cannot run AND a mismatched local binary exists: exit 2 — a wrong-version tool on PATH is
#      a fact the reader must see, never reported as "no tool here".
#   4. Nothing at all: on a contributor's machine print SKIPPED and exit 0 — a gate that fails for a
#      reason nobody is working on teaches people to ignore it — but under CI ($CI set, as GitHub
#      sets it) exit 1: a skip is not a pass, and CI is where the gate is enforced.
#
# Fetch is separated from validate: `--version` is run first so an environmental failure (no node,
# npx cannot resolve) is reported as such, and the validation's own exit code is the gate — it is
# exec'd, never laundered.
#
# OPENSPEC_TELEMETRY=0 is set so an npx-fetched CLI does not start reporting usage from a machine
# whose owner never installed openspec. OPENSPEC_NO_NPX=1 disables step 2 (tests use it to stay
# offline).

set -euo pipefail

: "${OPENSPEC_VERSION:?OPENSPEC_VERSION must be set (the Justfile exports it)}"
export OPENSPEC_TELEMETRY=0

pointer="see docs/contributor-conventions.md § OpenSpec"
local_version=""      # what a local binary reported, when one is on PATH
local_mismatch=""     # non-empty when that version is not the pin

if command -v openspec >/dev/null 2>&1; then
    local_version="$(openspec --version 2>/dev/null | tr -d '[:space:]' || true)"
    if [[ -z "$local_version" ]]; then
        echo "openspec-cli: a local openspec is on PATH but printed no version; ignoring it" >&2
    elif [[ "$local_version" == "$OPENSPEC_VERSION" ]]; then
        exec openspec "$@"
    else
        local_mismatch=1
    fi
fi

npx_ok=""
if [[ -z "${OPENSPEC_NO_NPX:-}" ]] && command -v npx >/dev/null 2>&1; then
    # fetch first: an unresolvable package is environmental, not a validation result
    if npx --yes "@fission-ai/openspec@$OPENSPEC_VERSION" --version >/dev/null 2>&1; then
        npx_ok=1
    fi
fi

if [[ -n "$npx_ok" ]]; then
    if [[ -n "$local_mismatch" ]]; then
        echo "openspec-cli: local openspec $local_version ignored (the repository pins $OPENSPEC_VERSION);" >&2
        echo "openspec-cli: validating with $OPENSPEC_VERSION via npx; $pointer" >&2
    fi
    exec npx --yes "@fission-ai/openspec@$OPENSPEC_VERSION" "$@"
fi

if [[ -n "$local_mismatch" ]]; then
    echo "openspec-cli: local openspec is $local_version but the repository pins $OPENSPEC_VERSION," >&2
    echo "openspec-cli: and npx cannot supply the pinned release here; refusing to use the local one" >&2
    echo "openspec-cli: (install $OPENSPEC_VERSION, or make node available); $pointer" >&2
    exit 2
fi

if [[ -n "${CI:-}" ]]; then
    echo "openspec-cli: openspec $OPENSPEC_VERSION is not available (no matching local binary, npx unavailable);" >&2
    echo "openspec-cli: CI enforces this gate, so absence is a failure; $pointer" >&2
    exit 1
fi

echo "SKIPPED — NOT VERIFIED: openspec $OPENSPEC_VERSION is not available on this machine (CI enforces it); $pointer"
exit 0
