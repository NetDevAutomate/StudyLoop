#!/usr/bin/env bash

set -euo pipefail

if ! command -v studyloop >/dev/null 2>&1; then
  echo "studyloop is not on PATH" >&2
  exit 127
fi

export STUDYLOOP_CONFIG="${STUDYLOOP_CONFIG:-$(mktemp -d)/config.yaml}"

studyloop --help >/dev/null
studyloop config --help >/dev/null
studyloop content --help >/dev/null
studyloop review --help >/dev/null

doctor_output="$(mktemp)"
status=0
studyloop doctor --json >"$doctor_output" || status=$?

if [ "$status" -gt 2 ]; then
  cat "$doctor_output" >&2
  exit "$status"
fi

python -m json.tool "$doctor_output" >/dev/null
