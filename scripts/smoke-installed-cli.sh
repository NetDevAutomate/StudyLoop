#!/usr/bin/env bash

set -euo pipefail

if ! command -v studyctl >/dev/null 2>&1; then
  echo "studyctl is not on PATH" >&2
  exit 127
fi

export STUDYCTL_CONFIG="${STUDYCTL_CONFIG:-$(mktemp -d)/config.yaml}"

studyctl --help >/dev/null
studyctl config --help >/dev/null
studyctl content --help >/dev/null
studyctl review --help >/dev/null

doctor_output="$(mktemp)"
status=0
studyctl doctor --json >"$doctor_output" || status=$?

if [ "$status" -gt 2 ]; then
  cat "$doctor_output" >&2
  exit "$status"
fi

python -m json.tool "$doctor_output" >/dev/null
