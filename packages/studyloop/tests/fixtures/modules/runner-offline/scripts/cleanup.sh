#!/bin/sh
# Offline cleanup: remove what setup created. Exits 0; nothing outside the attempt directory.
set -u
rm -f hello.txt
echo "cleanup: removed hello.txt"
