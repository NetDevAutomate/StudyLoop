#!/usr/bin/env bash
# Stage 9 owner script — the remote half of the 2026-09-10 branch cleanup.
# Agents cannot push or delete remote refs on this repo (platform policy), so the
# owner runs this once. Every step is idempotent; the preflight refuses to run if
# any archive tag is missing or points somewhere other than the manifest says.
# Manifest: docs/architecture/session-memory/receipts/stage9-disposition-2026-09-10.md
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

echo "== preflight: every archive tag exists and points at the manifest's OID =="
declare -A EXPECT=(
  [archive/feat-knowledge-proof-pre-okf-removal-2026-09-10]=27842b79
  [archive/feat-sessionweaver-phase2-retrofit-2026-09-10]=031dbab9
  [archive/feat-b1-fresh-install-scope-2026-09-10]=40da8e5f
  [archive/feat-b2-ontology-migration-2026-09-10]=a6e78d3c
  [archive/feat-b3-concept-lifecycle-2026-09-10]=790eff34
  [archive/feat-b4-recall-surfaces-2026-09-10]=77f9ab1e
  [archive/feat-b5-real-corpus-2026-09-10]=a4c5b518
  [archive/rescue-session-memory-mvp-20260907-2026-09-10]=fc30e8b4
  [archive/wip-parallel-integration-gaps-20260908-2026-09-10]=ad2935d2
  [archive/gh-pages-2026-09-10]=0adb4d5e
  [archive/gh-pages-archive-local-2026-09-10]=4104a323
  [archive/gh-pages-archive-remote-2026-09-10]=89612961
  [archive/socratic-study-mentor-main-local-2026-09-10]=d9bbc73d
  [archive/socratic-study-mentor-main-remote-2026-09-10]=bb0a52dd
)
for t in "${!EXPECT[@]}"; do
  got="$(git rev-parse --verify -q "${t}^{commit}" | cut -c1-8 || true)"
  if [[ "$got" != "${EXPECT[$t]}" ]]; then echo "REFUSING: $t -> '$got', expected ${EXPECT[$t]}"; exit 1; fi
done
echo "  14/14 tags verified"

echo "== 1. push main and the surviving feature branch (fast-forward only) =="
git push origin main
git push origin feat/knowledge-proof

echo "== 2. push today's archive tags =="
git push origin 'refs/tags/archive/*-2026-09-10'

echo "== 3. delete the remote branches whose tips are now tagged or fully merged =="
git push origin --delete \
  feat/b1-fresh-install-scope feat/b2-ontology-migration feat/b3-concept-lifecycle \
  feat/b4-recall-surfaces feat/sessionweaver-phase2-retrofit rescue/session-memory-mvp-20260907 \
  archive/gh-pages archive/socratic-study-mentor-main codex/evidence-context-evaluation

echo "== 4. verify =="
git fetch --prune origin
echo "remote branches now:"; git branch -r | sed 's/^/  /'
echo "remote archive tags: $(git ls-remote --tags origin 'archive/*-2026-09-10' | wc -l | tr -d ' ') (expect 14)"
