#!/usr/bin/env bash
# Proposal: validate the committed HEAD in a clean clone by running the real CI workflow.
set -Eeuo pipefail

repo_root="$(git rev-parse --show-toplevel)"
cd "$repo_root"

for tool in act docker git; do
    command -v "$tool" >/dev/null 2>&1 || {
        printf 'error: required tool not found: %s\n' "$tool" >&2
        exit 127
    }
done

docker info >/dev/null 2>&1 || {
    printf 'error: Docker is not running\n' >&2
    exit 1
}

head_sha="$(git rev-parse HEAD)"
before_sha="$(git rev-parse HEAD^ 2>/dev/null || printf '%040d' 0)"
git_dir="$(git rev-parse --absolute-git-dir)"
scratch_parent="$git_dir/ci-local-scratch"
cache_root="$git_dir/ci-local-act-cache"
mkdir -p "$scratch_parent" "$cache_root/actions" "$cache_root/cache"
scratch="$(mktemp -d "$scratch_parent/run.XXXXXX")"

cleanup() {
    rm -rf -- "${scratch:?}"
}
trap cleanup EXIT INT TERM

clone_dir="$scratch/repo"
event_file="$scratch/push-event.json"

git clone --quiet --no-hardlinks --no-local "$repo_root" "$clone_dir"
git -C "$clone_dir" checkout --quiet --detach "$head_sha"

cat >"$event_file" <<JSON
{
  "ref": "refs/heads/main",
  "before": "$before_sha",
  "after": "$head_sha"
}
JSON

printf 'Running CI for committed HEAD %s from a clean clone\n' "$head_sha"
cd "$clone_dir"
act push \
    --workflows .github/workflows/ci.yml \
    --eventpath "$event_file" \
    --container-architecture linux/amd64 \
    --platform ubuntu-latest=catthehacker/ubuntu:act-latest \
    --action-cache-path "$cache_root/actions" \
    --cache-server-path "$cache_root/cache"
