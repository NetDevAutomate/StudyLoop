#!/bin/sh
# Offline setup: seed the attempt directory with the file the check looks for, so the
# scaffold drill runs end to end without a learner. Exits 0; no network, Docker or kind.
set -eu
echo hello > hello.txt
echo "setup: wrote hello.txt in $STUDYLOOP_ATTEMPT_DIR for drill $STUDYLOOP_DRILL_ID"
