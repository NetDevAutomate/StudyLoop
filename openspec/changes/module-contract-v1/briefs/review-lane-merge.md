# Lane-merge review brief (one independent seat) — module contract v1

Used before each of the S, C, T and W merges (`design.md` §7 "Review cadence"). R's merge
review is council M1 and uses its own brief. The coordinator fills the **Inputs** block per
lane; everything else is fixed.

## Inputs (filled per review)

- Lane: `<S|C|T|W>` · branch `feat/module-<lane>` · worktree `/Users/ataylor/code/personal/tools/studyloop-wt/module-<lane>`
- Base sha: `<sha>` · lane commits: `<sha list>`
- Lane brief: `openspec/changes/module-contract-v1/briefs/<lane file>` and `briefs/00-common.md`
- Evidence directory: `openspec/changes/module-contract-v1/evidence/<lane>/`
- Gate transcript tail (pasted by the coordinator, from the lane's report):
  `<pre-commit result per commit; just preflight summary>`
- Coordinator's own call, written BEFORE dispatch (for `council/catch-rate.md`): `<text>`

## What the seat does

Read, in this order: the lane brief and the common brief; `proposal.md` sections the lane
brief names; the full diff `git diff <base>..<tip>` in the lane worktree (read-only — run no
git write command, edit no file); every file under the evidence directory; the tests the diff
adds. Fetch nothing from the network. Then answer the four questions, countably, in ≤ 900 words,
written to the single output file the dispatch names (`council/<date>-review-<lane>-<model>.md`).

## The four questions

1. **Red first.** For every behaviour the diff adds, name the test that covers it and the
   evidence file showing that test failing before the change. List any behaviour with no test,
   and any test with no red transcript — those are findings, not notes.
2. **Ownership.** List every file in `git diff --stat <base>..<tip>` and mark it owned / shared /
   outside the lane's owned globs. Anything outside is a finding, with the line in the lane
   brief it violates.
3. **Scope.** Anything the diff does that the proposal does not ask for — especially anything
   registry-shaped (C8), any new runtime dependency, any `pragma: allowlist`, `--no-verify`,
   `SKIP=`, or edit to `.pre-commit-config.yaml` / `.secrets.baseline` / a hook.
4. **The next lane.** The two things in this diff most likely to break the lane that merges
   next (names, types, import paths, fixture shapes it will depend on), with the exact
   symbol and file.

Close with: **verdict** (`merge` / `merge after fixes` / `do not merge`), the findings as a
numbered list each with `file:line` and the one-line fix, and a single line
`Findings: N raised`. Mark anything you could not verify UNVERIFIED. Do not restate the diff.

## What the coordinator does with the answer

Verifies every finding against the tree before acting; records raised / verified / acted /
discounted in `council/catch-rate.md`; applies verified fixes in the lane worktree as a
further commit through gate G (or hands them back to the lane agent), then merges with a
merge commit on `main`. A `do not merge` verdict with a verified design-level finding is a
"when needed" trigger for a full council.
