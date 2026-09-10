# Council record — Stage 9 (branch, worktree, pin and Pages disposition)

**Date:** 2026-09-10 · **Manifest reviewed:** `stage9-disposition-2026-09-10.md` (committed `b30d020c`
*before* any deletion) · **Cadence:** full three seats — `openai.gpt-6-astra` **APPROVE-WITH-CHANGES**
(7 findings, 44 s), `kimi-k2-thinking` **APPROVE-WITH-CHANGES** (9 findings, 48 s; replaces grok-4.6, which
failed to deliver on two of three stages), `qwen3-coder` **APPROVE** (2 MINOR, 11 s). No seat rejected;
**all three independently endorsed keeping `feat/knowledge-proof`** as the one surviving feature branch.

## Dispositions

Almost every finding was a verification request; each was run against git before acting.

| seat / id | severity | finding | disposition | check |
|---|---|---|---|---|
| kimi F1 | BLOCKING | knowledge-proof count and OKF residue UNVERIFIED by the seat | **CLOSED.** `main..464a8cdc` = 69 (manifest 69); OKF grep on its tip's `packages/` = 0 files. | `git rev-list --count`, `git grep -il` |
| kimi F2 / astra F2 | BLOCKING / MAJOR | b5's uncommitted work really committed? worktrees really clean, incl. ignored files? | **CLOSED.** `a4c5b518` = 4 files, +1,715/−223; b5 `status --porcelain` = 0. Ignored files in the five removed worktrees were mkdocs privacy-plugin cache, `.DS_Store` and `egg-info` — reproducible build output; the two pins had none. | `git show --stat`, `git ls-files --others --ignored` |
| kimi F3/F4, astra F7 | MAJOR / MINOR | are the local/remote `archive/*` pairs truly unrelated? distinct tag names? | **CLOSED.** `git merge-base --all` is **empty** for both pairs (no common ancestor at all). Tags are distinct: `…-archive-local-…` / `…-archive-remote-…` and `…-local-…` / `…-remote-…`. | `git merge-base --all` |
| kimi F5, astra F6 | MAJOR / MINOR | `dev` and `codex/session-memory-mvp` deleted without a tag — are they really reachable? | **CLOSED.** `538dc2bb` (dev) is contained by `main` and 11 other refs; `5dfe0f9b` (codex) is an ancestor of the tagged rescue tip. Manifest wording corrected: "every *deleted tip* is reachable from a tag or `main`", not "every tip tagged". | `git branch --contains`, ancestry |
| kimi F6 | MAJOR | wip's unique commit "superseded by B3/B4/B5" — is it actually contained? | **Correct concern, no loss.** It is *not* contained (its 8 files are unique); it is preserved by `archive/wip-parallel-integration-gaps-20260908-2026-09-10`. Manifest reason reworded from "superseded" to "preserved by tag; author marked it superseded". | ancestry checks |
| kimi F7, astra F3 | MAJOR | `lsof +D = 0` is a snapshot; audit the installed `session-export`'s resolved entrypoint | **CLOSED.** `~/.local/bin/session-export` → uv tool install `~/.local/share/uv/tools/agent-session-tools/…`; its interpreter imports `agent_session_tools` from that tool's own site-packages — **no pin in the chain**. The only launchd job runs that binary. No config file references either pin path. | symlink chain, shebang, `import agent_session_tools.__file__` |
| kimi F9 | MINOR | gh-pages unique commit may hold CNAME/custom-domain config | **CLOSED.** The commit is "Deployed 72c3dd3 with MkDocs 1.6.1" (`.nojekyll`, `404.html`, rendered HTML); **0 CNAME**. No CNAME anywhere tracked. | `git show --stat`, `git ls-tree` |
| kimi F8 | MINOR | delete the docs workflow instead of cutting it? | **Cut, not deleted**: the strict mkdocs build still fails CI on broken docs; the retirement contract is pinned by `test_docs_workflow_has_no_pages_deploy` (`60c2ee0c`), proven to discriminate against the old workflow. | test run |
| **astra F1** | MAJOR | manifest says the coordinator cannot do remote writes, then has the coordinator run the Pages API `DELETE` | **ACCEPT — my inconsistency.** The Pages deletion *is* a remote write; it was run because the owner authorised it explicitly and in words ("can now be removed too"), unlike pushes, which the platform blocks outright. Recorded as such: **owner-authorised, coordinator-executed**, verified `has_pages=false`. | `gh api repos/…/pages` → 404, `has_pages=false` |
| astra F4 | MAJOR | do Stages 6–8 need anything deleted here? | **CLOSED.** Stage 8's harvest input `031dbab9:openspec/…/tasks.md` is reachable via `archive/feat-sessionweaver-phase2-retrofit-2026-09-10` (checked with `cat-file -e`). Stage 6's DROP list is DB-only. Stage 7 touches the installer and `~/.grok`. No remaining stage references a removed worktree path or pin. | `git cat-file -e <tag>:<path>` |
| astra F5 | MAJOR | owner script's tag→OID mapping and fast-forwardability UNVERIFIED | **CLOSED.** `scripts/maintenance/stage9-owner-remote-cleanup.sh` carries an explicit 14-entry tag→OID **preflight that refuses to run on any mismatch** (dry-run: 14/14 verified); `origin/main` and `origin/feat/knowledge-proof` are both ancestors of the local tips → both pushes fast-forward. | script preflight, `merge-base --is-ancestor` |
| kimi Q8 | — | git notes / LFS not covered by tags | **CLOSED.** 0 notes refs; 0 LFS objects; no LFS filters. | `for-each-ref refs/notes`, `git lfs ls-files` |

## Executed (local)

- **14 archive tags** created (13 tips to be deleted + the pre-OKF-removal tip), each pointing at the
  commit named in the manifest.
- **6 worktrees removed** (all `status --porcelain` = 0): PR #18's, b5 (after committing its work as
  `a4c5b518`), the codex rescue checkout, a sub-agent scratch checkout, and both `~/.local/share` pins.
- **13 local branches deleted**, each only after an automated check that its tip is reachable from an
  archive tag, `main`, or `feat/knowledge-proof` (the check refuses otherwise; nothing was refused).
- **GitHub Pages retired**: live deployment disabled (owner-authorised API call; `has_pages=false`);
  `docs.yml` cut to a build-check job with read-only permissions; `site_url` → www.studyloop.dev;
  CONTRIBUTING link → `docs/contributing.md` (www has no `/contributing/`); local `site/` removed;
  retirement pinned by a discriminating test.
- Remaining: **`main`** and **`feat/knowledge-proof`** (branch + its worktree). Stashes 0.

## Remaining for the owner (`scripts/maintenance/stage9-owner-remote-cleanup.sh`)

Push `main` (now 39 ahead) and `feat/knowledge-proof`; push the 14 tags; delete the 9 remote branches
whose tips are tagged or fully merged. The script's preflight re-verifies every tag→OID first.

## Addendum — owner ran the remote script (2026-09-10 23:47)

- **Steps 1–2 succeeded and are verified on the remote:** `origin/main` `0adeb6c8 → 4497efed`,
  `origin/feat/knowledge-proof` `9a3eb5e1 → 464a8cdc`, all **14** `archive/*-2026-09-10` tags present.
- **Step 3 rejected for all nine branches** (`GH013 … Cannot delete this branch`). Cause, read from the
  API: repository ruleset **"Default" (id 22585978)** — `enforcement=active`, `target=branch`,
  `include=["~ALL"]`, rules `deletion` + `non_fast_forward`, **no bypass actors**. It applies to every
  identity, so the web UI and the API would refuse the same way. The classification did not account for
  it; the plan council's Q-list did not ask about server-side protection. Recorded as a census gap.
- **Not recommended:** adding the owner as a bypass actor — agents push under the owner's identity, so
  that would make the protection permanently moot for exactly the actor it most usefully constrains.
- **Recommended and scripted:** switch the ruleset off for the deletion step only, with the script
  asking first, sending the full ruleset body on both PUTs, re-enabling through an `EXIT` trap even if a
  deletion fails, and diffing the ruleset against a pre-change snapshot afterwards. The script is
  idempotent, so re-running it repeats steps 1–2 as no-ops. Untested on the live ruleset by design (an
  access-control change is the owner's); the disabled body was dry-run against the live GET and equals the
  current ruleset with only `enforcement` changed.
- Nothing is at risk while the branches remain: every tip is tagged on the remote.
