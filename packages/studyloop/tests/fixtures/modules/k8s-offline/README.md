# k8s-offline

Lane K0's fixture module for the disposable-cluster tests (module-contract v1): a
`target.kind: kubeconfig-context` drill that proves core creates the cluster, writes the
one-context kubeconfig and exports `KUBECONFIG` -- without a real `kind`.

## Prerequisites

`kind`, `kubectl`, `docker` -- in the core suite these are fake shell scripts on a scratch
PATH (`tests/test_module_cluster.py`); the module's scripts only need `kubectl` and `/bin/sh`.

## What runs

`scripts/setup.sh`, `scripts/check.sh` and `scripts/cleanup.sh` each echo `$KUBECONFIG` and
read `kubectl config current-context`. `check.sh` exits 0 when that context is the attempt's
`kind-studyloop-*` cluster, 1 otherwise, 2 when kubectl cannot run. No script creates or
deletes anything: the cluster is core's (proposal §5.5 *Kubernetes identity* and *Cleanup*).

## Data collected

A transient `practice_check` event per phase (identity, exit class, duration, delivery
outcome). No learner observation, no mastery, no output text.

## Limits

Reads only the injected `KUBECONFIG`. No network, Docker or kind beyond what core itself
runs to provision and delete the attempt's cluster.
