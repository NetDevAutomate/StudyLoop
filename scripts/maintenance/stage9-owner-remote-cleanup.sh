#!/usr/bin/env bash
# Stage 9 owner script — the remote half of the 2026-09-10 branch cleanup.
# Agents cannot push or delete remote refs on this repo (platform policy), so the
# owner runs this. Every step is idempotent, so re-running after a partial run is
# safe: already-pushed refs report "Everything up-to-date".
#
# First run (2026-09-10 23:47): steps 1-2 succeeded; step 3 was rejected for all
# nine branches with GH013 "Cannot delete this branch". Cause: repository ruleset
# "Default" (id 22585978) — active, target ~ALL branches, rules deletion +
# non_fast_forward, no bypass actors. The rule is worth keeping (it is what stops
# any identity, agents included, from force-pushing or deleting main), so step 3
# now asks before switching it off, switches it back on whether or not the
# deletions succeed, and proves afterwards that the ruleset is unchanged.
#
# Manifest: docs/architecture/session-memory/receipts/stage9-disposition-2026-09-10.md
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

REPO=NetDevAutomate/StudyLoop
RULESET_ID=22585978
RULESET_NAME=Default
DOOMED=(
  feat/b1-fresh-install-scope feat/b2-ontology-migration feat/b3-concept-lifecycle
  feat/b4-recall-surfaces feat/sessionweaver-phase2-retrofit rescue/session-memory-mvp-20260907
  archive/gh-pages archive/socratic-study-mentor-main codex/evidence-context-evaluation
)

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

echo "== 1. push main and the surviving feature branch (fast-forward only; no-op if already pushed) =="
git push origin main
git push origin feat/knowledge-proof

echo "== 2. push today's archive tags (no-op if already pushed) =="
git push origin 'refs/tags/archive/*-2026-09-10'

echo "== 3. delete the remote branches whose tips are now tagged or fully merged =="
# The ruleset is switched off only for this step. The full ruleset body is sent on
# both PUTs (not just the enforcement field) so nothing depends on partial-update
# semantics, and the pre-change snapshot is kept for comparison and for a manual
# restore if one were ever needed.
SNAP="$(mktemp -t stage9-ruleset)"
gh api "repos/${REPO}/rulesets/${RULESET_ID}" > "${SNAP}"
minimal() { jq -c --arg e "$1" \
  '{name, target, enforcement: $e, bypass_actors: (.bypass_actors // []), conditions, rules}' "${SNAP}"; }
reenable() {
  minimal active | gh api -X PUT "repos/${REPO}/rulesets/${RULESET_ID}" --input - --silent \
    && echo "  ruleset '${RULESET_NAME}' re-enabled (enforcement=active)"
}
echo "  ruleset '${RULESET_NAME}' (${RULESET_ID}) currently: $(jq -r .enforcement "${SNAP}"), rules $(jq -c '[.rules[].type]' "${SNAP}"), target $(jq -c .conditions.ref_name.include "${SNAP}")"
echo "  snapshot: ${SNAP}"
read -r -p "  Switch it OFF for the deletions and straight back ON? [y/N] " ans
if [[ "${ans}" =~ ^[Yy]$ ]]; then
  minimal disabled | gh api -X PUT "repos/${REPO}/rulesets/${RULESET_ID}" --input - --silent
  echo "  ruleset disabled"
  trap reenable EXIT                       # safety net: re-enable even if a deletion fails
  git push origin --delete "${DOOMED[@]}" || echo "  some deletions were rejected (see above)"
  reenable; trap - EXIT
  # prove the ruleset came back exactly as it was
  after="$(gh api "repos/${REPO}/rulesets/${RULESET_ID}" | jq -c '{name, target, enforcement, bypass_actors: (.bypass_actors // []), conditions, rules}')"
  before="$(minimal active)"
  if [[ "${after}" == "${before}" ]]; then echo "  ruleset unchanged (verified against the snapshot)"; rm -f "${SNAP}"
  else echo "  WARNING: ruleset differs from the snapshot — restore by hand from ${SNAP}"; echo "    before: ${before}"; echo "    after:  ${after}"; fi
else
  echo "  skipped: the nine remote branches stay (their tips are tagged; nothing is at risk)"
fi

echo "== 4. verify =="
git fetch --prune origin
echo "remote branches now:"; git branch -r | grep -v HEAD | sed 's/^/  /'
echo "remote archive tags: $(git ls-remote --tags origin 'archive/*-2026-09-10' | grep -vc '\^{}') (expect 14)"
echo "ruleset '${RULESET_NAME}' enforcement: $(gh api "repos/${REPO}/rulesets/${RULESET_ID}" --jq .enforcement) (expect active)"
