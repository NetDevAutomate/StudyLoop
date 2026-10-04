#!/bin/sh
# Offline check: exit 0 when the named file's first line is "hello", 1 (task not complete)
# otherwise, 2 when called without a file name. Reads only the attempt directory.
set -u
if [ "$#" -ne 1 ]; then
  echo "usage: check.sh <file>" >&2
  exit 2
fi
if [ -f "$1" ] && [ "$(head -n 1 "$1")" = "hello" ]; then
  echo "check: $1 says hello"
  exit 0
fi
echo "check: $1 is missing or does not say hello"
exit 1
