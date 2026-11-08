# Arbitration — council G1, the finished contributor guide (2026-10-04)

**Coordinator:** Kiro (default). **Brief:** `2026-10-04-review-brief.md`. **Subject:** the twenty
pages on `feat/contributor-guide` at `648d2dbc`. **Seats:** gpt-5.6-sol (704 w, 1 UNVERIFIED, 11
findings) · deepseek-3.2 (1,081 w, 1 repo cite, 3 UNVERIFIED, 3 findings) · glm-5 (1,456 w, 7
repo cites, 4 UNVERIFIED, 2 findings) · qwen3-coder-next (648 w, 0 repo cites, 7 UNVERIFIED, 4
"findings"). Every adopted finding was re-verified by the coordinator against the tree before the
fix was written; fixes landed as `0705b05e`.

## 1. Seat reliability

| Seat | Held | Did not | Weight |
| --- | --- | --- | --- |
| gpt-5.6-sol | all 11 findings verified: MkDocs in the `docs` extra (`pyproject.toml:20-23`); doctor exit codes (`cli/_doctor.py:261-272`); CI triggers (`ci.yml:3-7`); the default docs tier executes an allowlist (`test_contributor_guide_drift.py:14,301`); strict build ≠ prose truth; the 150-line rule's three exceptions; subject-length shares at the anchor are 24/71/88 % (coordinator re-ran `git log -n 300 --format=%s 60bbb504`); router vs changelog page; router vs AI page; missing `studyloop setup` (`cli/_setup.py:216`, `test_fresh_install_scope.py:190`); missing `studyloop web` (`cli/_web.py:35,138`). Also: the env↔first-contribution link loop; W-B's spine judged a good pattern; `acceptance-testing.md` a two-job wall | — | full |
| deepseek-3.2 | finding 2 (fixer vs reporter hooks is unclear to a first-week reader — adopted as a UX fix, not a contradiction); finding 3 (the router's "find the owning layer" step adds load — adopted: the step now names the four make-a-change pages) | finding 1 is UNVERIFIED by its own label and therefore not a finding under the brief | partial |
| glm-5 | the journey and naming judgements agree with GPT | both findings were already answered on the pages cited (`contributor-environment.md:12` says uv installs the pinned interpreter; `contributor-testing.md:50` shows `just e2e path/to/test_file.py`); found none of the eleven contradictions | agreement only |
| qwen3-coder-next | — | reviewed the main checkout instead of the named worktree and reported as findings that `test_contributor_guide_drift.py` and `.github/PULL_REQUEST_TEMPLATE.md` "do not exist" (both present, 23,681 bytes and 19 lines); "no access to justfile" (false); its one checked claim confirms the guide | zero |

Fourth round today with the same shape: one seat reads the code and finds real things; the
others restate the brief or review the wrong tree. The catch-rate table is what makes dropping a
seat defensible; Qwen is at two useless reviews out of four (planning: over-budget but usable;
M0: approve-all; G1: wrong tree).

## 2. What was fixed (`0705b05e`), by finding

GPT 1–11 as listed above; DeepSeek 2 and 3; the link loop (router step 1 now says fork-and-clone
first, then one forward link; the environment page's back-link is unchanged because it is the
owning page for the fork commands); the four "a stale sentence fails the build" claims rewritten to
distinguish the strict build, the drift pins and human review. A new fenced command
(`uv run studyloop setup`) is receipted in `evidence/A1/commands.txt` as **not executed** against
the owner's HOME (it writes real configuration) with `setup --help` executed instead — the same
judgement W-B made for `doctor`.

Verified after the fixes: `test_contributor_guide_drift.py` 119 passed; the five docs suites 484
passed, 3 skipped; `just docs` strict green; every edited page under its cap (router 189/200).

## 3. Recorded, not fixed here

- `docs/acceptance-testing.md` is 645 lines and two jobs (acceptance from line 1, UAT from 517):
  split into two pages in a follow-up `docs(acceptance)` change; until then it is exempt from the
  structure checks by design.
- `just test-web` is a fixed nine-file list (W-B's finding): a follow-up `test(gate)` change to
  make the recipe a glob, or to document that the default suite is the real gate.
- `openspec/specs/content-generation/spec.md` names `content/generators/stub.py` (does not exist)
  and `settings.py:366` (now 486) — pre-existing living-spec drift (W-C), a follow-up
  `docs(openspec)` fix.
- `openspec/config.yaml` says "Typer/Click CLI" — the CLI is Click only; owner's call whether to
  edit that file (outside the guide's lease).
- GPT's unverified item — the branch-protection statement at `docs/contributing.md:121` — cannot be
  proven from the repository (rulesets live on GitHub); the owner confirms or the sentence softens.

## 4. Catch-rate

Raised 20 (gpt 11, deepseek 3, glm 2, qwen 4) · verified 13 (gpt 11, deepseek 2) · acted 13 ·
discounted 7 (deepseek 1 UNVERIFIED; glm 2 already-true; qwen 4 wrong-tree). The coordinator's
call (3-6 prose findings, the normalised-titles challenge) was low: eleven real contradictions,
and no seat challenged the normalised titles.

**Verdict carried: ship after fixes → fixes applied → ship**, subject to the owner's read of
`design.md` §2 and §4 (the objection window stays open; amendments after merge are ordinary
`docs(contributing)` commits).
