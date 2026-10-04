# runner-offline

Lane R's offline fixture module for the drill runner tests (module-contract v1).

## Prerequisites

None. `/bin/sh`, `head`, `rm` and `echo` only.

## What runs

`scripts/setup.sh` writes `hello.txt`; `scripts/check.sh hello.txt` exits 0 when its first
line is `hello`, 1 otherwise, 2 when called without a file; `scripts/cleanup.sh` removes it.
Each phase is one executable plus literal arguments, run with `shell=False` from the module
snapshot in a core-created attempt directory.

## Data collected

A transient `practice_check` event per phase (identity, exit class, duration, delivery
outcome). No learner observation, no mastery, no output text.

## Limits

Nothing outside the attempt directory is read or written. No network, Docker or kind.
