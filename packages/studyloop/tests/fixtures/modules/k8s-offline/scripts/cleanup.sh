#!/bin/sh
# Offline cleanup for the kubeconfig-context fixture. The cluster itself is core's to delete
# (proposal §5.5 *Cleanup*: target teardown is a core operation, not module shell), so this
# script only reports what it saw. Exits 0.
set -u
echo "cleanup KUBECONFIG=${KUBECONFIG:-<unset>}"
