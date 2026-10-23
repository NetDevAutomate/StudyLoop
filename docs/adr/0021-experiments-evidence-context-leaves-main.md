# ADR-0021: `experiments/evidence_context` leaves `main` for an archive branch

**Status:** Accepted, 2026-10-22 (decided by the owner at 19:15 BST on the coordinator's revised
recommendation; recorded and implemented the same evening) · **Date:** 2026-10-22 · **Deciders:**
Andy Taylor (owner), on a question the 2026-10-21 review's council pass 3 (ruling D8, five no-tool
seats: kimi-k3, gpt-6-astra, grok-4.6, deepseek-r1, mistral-large-3) had split 3–2 and the
coordinator had reserved for the owner. · **Change:** removal of `experiments/` from `main` in the
commit after this record; archive branch `archive/experiments-evidence-context` and annotated tag
`archive/experiments-evidence-context-2026-10-22`, both created before the removal.

The council record (`reviews/2026-10-21-full-repo-review/`, gitignored, owner's machine only) holds
the seat transcripts; everything this record relies on is restated here. Facts were read from the
tree at `65e29965`.

## Context

`experiments/evidence_context/` was the evidence-context research programme: versioned conversation
evidence and relationship-assisted retrieval, evaluated in isolation from the production
`sessions.db`. It entered the tree on 2026-09-05 (`c262c081`) and was last touched on 2026-09-06 by
`2a10a82c`, "Record MVP delivery rebaseline and preserve paused research plan". Its `README.md`
and `STAGES.md` open with the pause: *"The research implementation is paused in favour of a smaller
reliability release… All learning stages below remain preserved; they are not release-readiness
claims."* Nothing imported it, no packaging rule, mkdocs allowlist or CI job named it, and the one
inbound reference from the public tree is a single `file:line` citation in
`docs/architecture/session-memory/receipts/semantic-layer/lane-A.md`.

Council pass 3 asked whether a paused 443-file tree belongs in `main` (D8). Three seats (grok,
mistral, deepseek) said move it out: contributor ergonomics, and "`main` is the product". Two
(astra, kimi) said keep: a deliberate, documented pause seven weeks old, "zero runtime or gate
cost", one inbound reference, and "a tag nobody browses is deletion with extra steps". The
coordinator found the keep argument stronger *on the stated facts*, declined to delete the owner's
research on a council vote, and reserved the question for the owner with kimi's trigger for
flipping (no scheduled resumption in the first planning cycle after the reliability release).

Two of the stated facts were wrong, in the direction that flattered keeping, and were corrected
when the owner asked the question directly on 2026-10-22:

- **The gate cost is not zero.** The tree holds **183 Python files**. `ruff check .` and
  `ruff format --check .`, which `just lint`, the CI lint job and every gate script run, lint and
  format-check all of them. They are clean today; every future ruff pin bump would have to be
  satisfied by paused research code nobody is working on.
- **It carries a dead suite.** `pytest experiments/` collects **272 tests**; `testpaths` in
  `pyproject.toml` excludes the directory, so no gate runs them. The repository's own CI comment
  states the principle this violates: "a suite nothing runs cannot be evidence."

Two further facts bear on the decision. Fourteen of the tree's documents cite their evidence under
`studyloop-private/reviews/2026-09-06-stage*`; the owner retired that repository on 2026-10-22, so
the cited evidence is unreachable from any clone whichever way the question goes. And three of the
tree's observation JSON files account for 27 audited entries in `.secrets.baseline` (digests, not
secrets) that have to be carried along with it.

## Decision

`experiments/` is removed from `main`. Before the removal, the tree is preserved at its last
commit on `main` (`65e29965`) on the branch `archive/experiments-evidence-context`, whose head adds
only a marker `ARCHIVE-experiments-evidence-context.md`, and the annotated tag
`archive/experiments-evidence-context-2026-10-22` names that head immutably, following the
repository's existing `archive/<line>-<date>` convention. Neither ref is reachable from `main`, so
`git describe --tags` on `main` (which `scripts/check-release-consistency.py` uses to find the last
release) is unaffected.

The removal commit deletes the 443 tracked files, drops the three `experiments/…` entries from
`.secrets.baseline` and nothing else in it, and repoints the `lane-A.md` citation at the archive
branch. The archive branch must be pushed alongside `main`; a branch that exists on one machine is
the state the retired repository's clones are in now.

*Amendment, 2026-10-23 (owner decision, 11:10 BST): the archive refs are withdrawn; the removal
stands.* The owner chose not to publish a second ref for a paused tree. The branch
`archive/experiments-evidence-context` and the tag `archive/experiments-evidence-context-2026-10-22`
were deleted locally before either had been pushed (`git ls-remote origin` listed neither). Nothing
is lost by this: the branch pointed at `65e29965`, a commit on `main`, and its only unique content
was the 23-line marker file. The tree is preserved by `main`'s own history, which every clone
carries, and the restore is still one command against the last `main` commit that holds it:
`git checkout 6c9571c8 -- experiments/` (`git ls-tree -r --name-only 6c9571c8 -- experiments | wc -l`
prints 443). The push requirement in the paragraph above no longer applies, the `lane-A.md`
citation now names that commit, and the "delete without an archive ref" alternative below is the
shape the decision has taken: discoverability comes from this record rather than from a ref. The
two Verification commands below that name the refs were true on 2026-10-22 and no longer resolve.*

## Alternatives considered

- **(a) Keep in `main` with an expiry condition** (the coordinator's original recommendation):
  rejected once the gate cost and the dead suite were established. The expiry condition would have
  deferred a decision the facts already make.
- **Keep, but exclude the tree from ruff and add its tests to `testpaths`**: the second half makes
  272 unmaintained tests part of every gate; the first half hides lint debt rather than removing
  it. Both are more maintenance for a tree whose own README says it is not being worked on.
- **Delete without an archive ref**: history preserves the files, but only a named ref makes the
  restore a one-liner and makes the tree discoverable. Rejected; the ref costs nothing.
- **Move to a private repository**: the destination the brief named was retired by the owner
  before the decision; see `.gitignore`'s boundary comment and `AGENTS.md` §2.

## Consequences

- A contributor's checkout no longer carries 443 files of paused research, 183 Python files leave
  the lint path, and `main` holds no suite that nothing runs.
- Resuming the research is `git checkout archive/experiments-evidence-context -- experiments/`,
  then putting its tests under `testpaths` and re-adding the three `.secrets.baseline` entries. The
  branch marker says the same.
- The 14 citations to the retired repository leave `main` with the tree; they remain readable on
  the archive branch, and the evidence they name still exists only in the owner's local clones.
- Reversal is cheap and the reverse of reversal is not: this is the same asymmetry ADR-0019
  relied on, applied to a directory instead of a flag.

## Verification

- Archive refs: `git ls-tree -r --name-only archive/experiments-evidence-context -- experiments | wc -l`
  prints 443; `git merge-base --is-ancestor archive/experiments-evidence-context-2026-10-22 main`
  is false; `git describe --tags --abbrev=0` on `main` prints the last release tag.
- After the removal: `git ls-files experiments | wc -l` prints 0; `git grep -l studyloop-private`
  on `main` prints nothing; `uv run --group dev pre-commit run detect-secrets --all-files` passes
  with the baseline's `results` differing from the previous commit only by the three removed keys;
  the full default gate and `mkdocs build --strict` are green on the removal commit.
