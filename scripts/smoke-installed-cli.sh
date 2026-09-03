#!/usr/bin/env bash

set -euo pipefail

require_on_path() {
  local name="$1"
  local resolved
  if ! resolved="$(command -v "$name" 2>/dev/null)"; then
    echo "$name is not on PATH" >&2
    exit 127
  fi

  if [ -n "${STUDYLOOP_EXPECT_BIN_DIR:-}" ]; then
    local expected_dir
    local resolved_dir
    if ! expected_dir="$(cd "$STUDYLOOP_EXPECT_BIN_DIR" 2>/dev/null && pwd -P)"; then
      echo "expected bin dir does not exist: $STUDYLOOP_EXPECT_BIN_DIR" >&2
      exit 127
    fi
    if ! resolved_dir="$(cd "$(dirname "$resolved")" 2>/dev/null && pwd -P)"; then
      echo "could not resolve $name path: $resolved" >&2
      exit 127
    fi
    case "$resolved_dir/" in
      "$expected_dir/"*) ;;
      *)
        echo "$name resolves outside expected bin dir: $resolved" >&2
        echo "expected inside: $expected_dir" >&2
        exit 127
        ;;
    esac
  fi
}

require_on_path "studyloop"
require_on_path "session-export"

export STUDYLOOP_CONFIG="${STUDYLOOP_CONFIG:-$(mktemp -d)/config.yaml}"
# STUDYLOOP_CONFIG alone does not move the session DB or state dir off the
# machine's real ~/.config/studyloop/sessions.db / ~/.local/share/studyloop --
# both are resolved independently of which config file is active, so every
# doctor/self-test check below would otherwise read real session history. A
# machine whose real session DB has drifted (e.g. FTS index drift from normal
# use) makes `doctor` report "fail", which the status-allowlist below then
# rejects -- breaking this smoke test for a reason that has nothing to do with
# the release under test.
export STUDYLOOP_DB="${STUDYLOOP_DB:-$(mktemp -d)/sessions.db}"
export STUDYLOOP_STATE_DIR="${STUDYLOOP_STATE_DIR:-$(mktemp -d)/state}"

studyloop --help >/dev/null
studyloop config --help >/dev/null
studyloop content --help >/dev/null
studyloop review --help >/dev/null
session-export --help >/dev/null

self_test_output="$(mktemp)"
self_test_status=0
studyloop self-test --json >"$self_test_output" || self_test_status=$?

case "$self_test_status" in
  0|1) ;;
  *)
    cat "$self_test_output" >&2
    exit "$self_test_status"
    ;;
esac

python3 -m json.tool "$self_test_output" >/dev/null

doctor_output="$(mktemp)"
doctor_status=0
studyloop doctor --json >"$doctor_output" || doctor_status=$?

case "$doctor_status" in
  0|1) ;;
  *)
    cat "$doctor_output" >&2
    exit "$doctor_status"
    ;;
esac

python3 -m json.tool "$doctor_output" >/dev/null
python3 - "$doctor_output" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    payload = json.load(handle)

if not isinstance(payload, list):
    print("doctor JSON must be a list", file=sys.stderr)
    raise SystemExit(1)

allowed_statuses = {"pass", "warn", "info"}
for item in payload:
    if not isinstance(item, dict):
        print("doctor JSON items must be objects", file=sys.stderr)
        raise SystemExit(1)
    status = item.get("status")
    if status not in allowed_statuses:
        print(f"unexpected doctor status: {status}", file=sys.stderr)
        raise SystemExit(1)
PY
