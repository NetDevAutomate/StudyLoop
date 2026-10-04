# Council G1 — review the finished contributor guide (2026-10-04)

You are one of four independent review seats. Answer every numbered question, countably, in
order, in ≤ 1,000 words, written to the single file named in your dispatch and nothing else.
Read-only everywhere: run no git write command, no `uv`/`just`/`pytest` (a gate run is in progress
in the worktree), fetch nothing from the network, touch nothing under `~/.kiro`. Every finding
carries `file:line` in the guide AND the `file:line` in the repository that contradicts it; a
claim you could not check is marked UNVERIFIED and is not a finding.

## What you are reviewing

The twenty-page guide as assembled on `feat/contributor-guide` at `648d2dbc`, in the worktree
`/Users/ataylor/code/personal/tools/studyloop-wt/contributor-guide`:

- the pages: `docs/contributing.md` (the numbered router) and the eighteen `docs/contributor-*.md`
  pages, plus `docs/acceptance-testing.md` (pre-existing, two lines added) and
  `.github/PULL_REQUEST_TEMPLATE.md`; the nav is `mkdocs.yml` lines 112-160;
- the plan they were written to: `openspec/changes/contributor-guide-v1/design.md` (§2 inventory
  and nav, §3 the verified facts sheet F1–F16, §4 the naming standard, §6 the drift test) and
  `council/2026-10-04-plan-arbitration.md` (why those decisions);
- the truth mechanism: `packages/studyloop/tests/test_contributor_guide_drift.py` (what is pinned
  by test) and the writers' receipts `openspec/changes/contributor-guide-v1/evidence/W-*/commands.txt`
  (what was run) and `evidence/A1/assembly-audit.md` (what the assembler checked and accepted).

The repository itself is the arbiter of truth: `/Users/ataylor/code/personal/tools/studyloop`
(main at `0b0a3fab`+) or the same files in the worktree.

## Settled — flag a violation, do not re-argue

- S1. Twenty flat pages, no file moves, the router keeps its fifteen H2 anchors; the Terraform
  grouping lives in nav. (Plan arbitration D1–D2.)
- S2. `type(scope): description` with closed types and open scope; PR titles obey it; the three
  real PRs are shown **normalised** and labelled as such because today's merge subjects carry no
  type. (D4.) Only the eight F14 shas are admitted as examples.
- S3. The module contract and module index are proposals; the index page says "design stage" in
  paragraph 1; no fenced `studyloop module …`/`studyloop drill …` line anywhere. (K4, pattern M.)
- S4. Every fenced command was run by its writer and receipted; `just e2e`, `just testacc`,
  `just testuat` and `uv run studyloop doctor` (reads the owner's real config) are never executed
  by a writer and are resolved structurally instead. Receipts may show exit=1 where that is the
  honest result.
- S5. AuDHD house style (contributor-documentation.md's checklist): one job per page, answer first,
  numbered steps, ≤ 150 lines (router 200, cookbook 220), no "see elsewhere" loops.

## Questions — answer every one, in order

1. **Truth beyond the drift test.** The test pins commands, paths, anchors, tiers, markers and the
   module-page invariants. It does NOT pin prose claims about behaviour. Read every page's prose
   claims about what a command, gate, hook, test tier or file *does* and check each against the
   code or the justfile. List every claim the repository contradicts (`guide file:line` →
   `repo file:line`). Prioritise the environment, debugging, web, testing and changelog pages.
2. **The reader journey.** Walk `docs/contributing.md` as the colleague with a Kubernetes/Go
   background would: from a fresh clone to an opened PR, following only the links. Where would they
   stop — a step that assumes context, a link that lands mid-page, a loop ("see X" → "see Y" →
   back), a page that explains two jobs, a wall of text? Name each with `file:line`. Then say
   whether W-B's four same-spine pages read as a pattern (good) or as repetition (bad), and why.
3. **The naming standard page** (`docs/contributor-pull-requests.md`): is every rule derivable from
   the eight examples, is the subject-length statement honest against `git log -n 300
   --format=%s` at `60bbb504`, does the template match the five questions, and does the page
   contradict `docs/contributing.md`'s PR section anywhere?
4. **What the plan missed.** Two things a contributor needs in their first week that none of the
   twenty pages answers, with the evidence that they are real needs (a failing path you can name,
   not a preference). Then the two claims you expect the other seats to make that the repository
   contradicts.

Close with: `Verdict: ship | ship after fixes | rework`, the findings as a numbered list each with
`guide file:line`, `repo file:line`, and a one-line fix, then `Findings: N raised`.
