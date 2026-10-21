#!/usr/bin/env bash
# Source this (or run a command through it) to give an UNATTENDED council run
# the 1Password service-account token the gateway key resolution needs.
#
#   source scripts/council/council_env.sh
#   uv run --group dev python scripts/council/run_council.py --brief ... --out ... --seat ...
#
# or, as a wrapper that runs one command with the variable set:
#
#   scripts/council/council_env.sh uv run --group dev python scripts/council/run_council.py ...
#
# The token is read from ~/.config/op/sa-token (mode 0600, created by the
# owner) into OP_SERVICE_ACCOUNT_TOKEN only. Nothing here prints it, and
# run_council.py's `op read` path never echoes what it resolves. If the file is
# missing the variable is left alone, so an already-exported token still works.
_sa_token_file="${OP_SA_TOKEN_FILE:-$HOME/.config/op/sa-token}"
if [ -z "${OP_SERVICE_ACCOUNT_TOKEN:-}" ] && [ -r "$_sa_token_file" ]; then
  OP_SERVICE_ACCOUNT_TOKEN="$(tr -d '[:space:]' < "$_sa_token_file")"
  export OP_SERVICE_ACCOUNT_TOKEN
fi
unset _sa_token_file

# Default gateway address. run_council.py reads LITELLM_BASE_URL from the proxy
# .env too; this only supplies a default when that .env is absent on a machine.
: "${LITELLM_BASE_URL:=http://127.0.0.1:4000}"
export LITELLM_BASE_URL

# Wrapper form only: when this file is EXECUTED with a command, run it. When it is
# SOURCED, $@ belongs to the caller, so never exec it (that would replace the
# caller's shell with the caller's own arguments).
if [ "${BASH_SOURCE[0]}" = "$0" ] && [ "$#" -gt 0 ]; then
  exec "$@"
fi
