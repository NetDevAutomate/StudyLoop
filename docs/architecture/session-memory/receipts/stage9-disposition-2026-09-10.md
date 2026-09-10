# Stage 9 — branch, worktree and Pages disposition (manifest before action)

**Date:** 2026-09-10 · **Owner directive:** "review all git branches and worktrees, removing all
un-needed branches and worktrees. The github pages and gh-pages branch is no longer needed now we have
www.studyloop.dev — so these can now be removed too." · **Rule applied to every deletion:** tag the tip
`archive/<name>-2026-09-10` first; nothing becomes unreachable. **Platform constraint:** agents cannot
push (branches *or* tags) or delete remote refs — those lines are collected in the owner script at the end.

Census source: `git fetch --prune` then `for-each-ref`, `rev-list --count main..`, `merge-base
--is-ancestor`, `worktree list --porcelain`, `status --porcelain`, `lsof`, launchd plist (all recorded
in the transcript; the two numbers that changed from the plan-council brief are flagged ⚠).

## Local branches (15)

| branch | tip | unique vs `main` | disposition | evidence |
|---|---|---|---|---|
| `main` | `71a587b5` | — | **KEEP** (36 ahead of origin — owner pushes) | |
| `feat/knowledge-proof` | `464a8cdc` | 69 | **KEEP — the one surviving feature branch** | Holds the learning-memory claims/evidence store and `plan_prose_query`, the *only* established retrieval lever (+0.142, `council-stage4`); ADR-0011 names them the semantic layer's prerequisites. Its OKF half was removed today (Stage 5); its receipts are already on `main`. Worktree stays. Pre-edit tip tagged. |
| `feat/sessionweaver-phase2-retrofit` | `031dbab9` | 31 | **TAG + DELETE** | PR #18 CLOSED 21:59Z; keep-half landed (`48900c3d`); drop-half retired by ADR-0011. Tip is an ancestor of `feat/knowledge-proof`'s pre-edit tag. Stage 8 needs `031dbab9:openspec/…/tasks.md` — reachable via the tag. Worktree removed. |
| `feat/b1-fresh-install-scope` | `40da8e5f` | 3 | **TAG + DELETE** | ancestor of knowledge-proof; keep-half commit landed on `main` |
| `feat/b2-ontology-migration` | `a6e78d3c` | 8 | **TAG + DELETE** | ancestor of knowledge-proof; ontology retired |
| `feat/b3-concept-lifecycle` | `790eff34` | 20 | **TAG + DELETE** | ancestor of knowledge-proof; sidecar retired |
| `feat/b4-recall-surfaces` | `77f9ab1e` | 30 | **TAG + DELETE** | tree byte-identical to PR #18's; ancestor of knowledge-proof |
| `feat/b5-real-corpus` | `a4c5b518` ⚠ | 46 (15 not in knowledge-proof) | **TAG + DELETE** | B5 = real-corpus acceptance of the retired programme (v50 migration, sidecar flows). ⚠ Its worktree held **uncommitted** work (+1,715/−223 across 4 files) — committed as `a4c5b518` *before* tagging so the tag holds it. Worktree removed. |
| `dev` | `538dc2bb` | 0 | **DELETE** (fully merged into `main`; no tag needed — tip is on `main`) | `merge-base --is-ancestor dev main` = yes |
| `codex/session-memory-mvp` | `5dfe0f9b` | 5 | **DELETE** (no tag: strict ancestor of `rescue/…`, which is tagged) | ancestor check = yes |
| `rescue/session-memory-mvp-20260907` | `fc30e8b4` | 6 | **TAG + DELETE** | the 2026-09-07 rescue of Phase 0 close-out work; = origin. Worktree `~/.codex/worktrees/session-memory-mvp/studyloop` removed. |
| `wip/parallel-integration-gaps-20260908` | `ad2935d2` | 1 | **TAG + DELETE** | its own subject: "superseded by retrofit B3/B4/B5" |
| `gh-pages` | `0adb4d5e` | 1 | **TAG + DELETE** (owner: Pages retired) | |
| `archive/gh-pages` | `4104a323` | 44 | **TAG + DELETE** | ⚠ **unrelated history** to `origin/archive/gh-pages` (neither is an ancestor of the other) — both tips tagged separately |
| `archive/socratic-study-mentor-main` | `d9bbc73d` | 6 | **TAG + DELETE** | ⚠ plan brief said 380; that is the *remote* tip. Local = 6 CI-fix commits from 2026-07/08. Unrelated to the remote tip — both tagged. |

## Remote branches (11) — owner script

| remote | tip | disposition |
|---|---|---|
| `origin/main` | `0adeb6c8` | keep; owner fast-forwards it (`git push origin main`) |
| `origin/feat/knowledge-proof` | `9a3eb5e1` | keep; owner pushes the local tip (`git push origin feat/knowledge-proof`) |
| `origin/feat/b1…b4`, `origin/feat/sessionweaver-phase2-retrofit`, `origin/rescue/…` | = local tips | delete after tags pushed |
| `origin/archive/gh-pages` | `89612961` (44, unrelated to local) | tag `archive/gh-pages-remote-2026-09-10` → delete |
| `origin/archive/socratic-study-mentor-main` | `bb0a52dd` (380, unrelated to local) | tag `archive/socratic-study-mentor-main-remote-2026-09-10` → delete |
| `origin/codex/evidence-context-evaluation` | `d3054200` | 0 unique vs `main` → delete (no tag needed) |

## Worktrees (8)

| path | head | disposition | evidence |
|---|---|---|---|
| repo root | `main` | keep | |
| `.worktrees/knowledge-proof` | `feat/knowledge-proof` | **keep** | |
| `.worktrees/sessionweaver-phase2-retrofit` | `031dbab9` | remove | clean; branch tagged+deleted |
| `.worktrees/b5-real-corpus` | `a4c5b518` | remove | clean after the wip commit |
| `~/.codex/worktrees/session-memory-mvp/studyloop` | `rescue/…` | remove | clean; branch tagged+deleted |
| `~/.kiro/crew/scratch/runtime-3fa6fa09/baseline-c309d132` | detached `c309d132` | remove | sub-agent scratch; `c309d132` is on `main` |
| `~/.local/share/sessionweaver/production-pins/fb606468/checkout` | detached `fb606468` | **remove** | `lsof +D` = 0 handles; the only launchd job (`com.sessionweaver.export-sweep`) runs `~/.local/bin/session-export`, not the pin; no config file references the path; `fb606468` is the merge base of the retrofit and is on `main`'s history |
| `~/.local/share/studyloop/knowledge-proof/pins/031dbab9` | detached `031dbab9` | **remove** | `lsof +D` = 0; harness B0 pin for looks that are complete; `031dbab9` preserved by tag |

Stashes: 0. Ignored-but-edited docs in the root (`docs/architecture/c4-test-suite-context.md`,
`test-suite-design.md`): not worktree state; unchanged by this stage (owner's earlier call: leave).

## GitHub Pages (owner directive)

| item | disposition |
|---|---|
| live Pages deployment (`status=built`, source `gh-pages`) | **disable** via `gh api -X DELETE repos/NetDevAutomate/StudyLoop/pages` — a remote change; run by the coordinator and stated explicitly |
| `.github/workflows/docs.yml` | cut to **build + strict check only**; remove the `github-pages` environment, `pages: write`, `upload-pages-artifact`, `deploy-pages` steps |
| `mkdocs.yml` `site_url` | → `https://www.studyloop.dev/` |
| `CONTRIBUTING.md` github.io link | → the www equivalent (verified to resolve before commit) |
| `site/` (47 untracked files, local mkdocs output) | delete |

## Owner script (everything the platform blocks agents from doing)

```bash
# 1. push main and the surviving feature branch
git push origin main
git push origin feat/knowledge-proof
# 2. push every archive tag created today
git push origin --tags        # or: git push origin 'refs/tags/archive/*-2026-09-10'
# 3. delete the remote branches whose tips are now tagged (or fully merged)
git push origin --delete feat/b1-fresh-install-scope feat/b2-ontology-migration \
  feat/b3-concept-lifecycle feat/b4-recall-surfaces feat/sessionweaver-phase2-retrofit \
  rescue/session-memory-mvp-20260907 archive/gh-pages archive/socratic-study-mentor-main \
  codex/evidence-context-evaluation
```
