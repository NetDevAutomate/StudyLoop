#!/bin/sh
# Offline setup for the kubeconfig-context fixture: show which kubeconfig core injected and
# which context it names. Reads only $KUBECONFIG; creates nothing. Exits 0.
set -eu
echo "setup KUBECONFIG=${KUBECONFIG:-<unset>}"
echo "setup context $(kubectl config current-context)"
