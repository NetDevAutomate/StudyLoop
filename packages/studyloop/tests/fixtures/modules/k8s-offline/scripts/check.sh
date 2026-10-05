#!/bin/sh
# Offline check for the kubeconfig-context fixture: exit 0 when $KUBECONFIG is set and names
# exactly one context (the disposable cluster's), 1 (task not complete) otherwise, 2 when
# kubectl cannot be run. Reads only $KUBECONFIG.
set -u
echo "check KUBECONFIG=${KUBECONFIG:-<unset>}"
if [ -z "${KUBECONFIG:-}" ]; then
  echo "check: KUBECONFIG is not set" >&2
  exit 2
fi
context="$(kubectl config current-context)" || exit 2
echo "check context $context"
case "$context" in
  kind-studyloop-*) exit 0 ;;
esac
echo "check: current context is not the attempt's disposable cluster"
exit 1
