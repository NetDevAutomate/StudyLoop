# Brief A0 — scaffold (runs first, alone)

Read `00-common.md` first, then `design.md` §2 (inventory and nav block), §3 F9-F11, §6 (the
drift test — this is your main deliverable), §5 (ownership) and `tasks.md` §1.

| | |
| --- | --- |
| Branch | `feat/contributor-guide` |
| Worktree | `/Users/ataylor/code/personal/tools/studyloop-wt/contributor-guide` (exists, at main `32254451`) |
| Owns | the 15 **new** page stubs; `mkdocs.yml`; `packages/studyloop/tests/test_contributor_guide_drift.py` (new); the `_STUDYLOOP_EXAMPLE_DOCS` tuple in `packages/studyloop/tests/test_docs_drift.py`; `openspec/changes/contributor-guide-v1/evidence/A0/` |
| Forbidden | the four seed pages' bodies and `acceptance-testing.md` (writers own them); `CHANGELOG.md`; any `src/` file |

## A0.1 Stubs (one commit)

For every page marked **new** in design.md §2 (pages 2-10, 13-16, 18, 20 — fifteen files), create
`docs/<stem>.md` containing exactly: `# <nav title from §2>`, a blank line, the page's "one job"
sentence from §2 as one paragraph, a blank line, `<!-- GUIDE-STUB -->`. Edit `mkdocs.yml`: add a
`!/<stem>.md` allowlist line per stub (keep the existing order; put them after `!/acceptance-testing.md`),
and replace the Contribute block (currently lines 112-117, plus the top-level
`- Acceptance Testing: acceptance-testing.md` line) with the nav block in §2 verbatim. Verify
`env -u VIRTUAL_ENV just docs` strict passes with the stubs and that `ls docs/contributor-*.md`
lists 19 files (+ `acceptance-testing.md` = 20 pages). Commit: `docs(contributing): scaffold the
twenty-page guide — stubs, allowlist, nav`.

## A0.2 The drift test (one commit, red first)

`packages/studyloop/tests/test_contributor_guide_drift.py`, default tier, no network, following
the conventions of `test_docs_drift.py` (read it first: `DOCS_DIR`, `_iter_fenced_lines`, the
parametrize-by-location style, the plain-English module docstring explaining each test). Implement
design.md §6 exactly: a module-level `GUIDE_PAGES: tuple[tuple[str, str, int], ...]` of
`(stem, group, line_cap)` for the 20 pages (cap 150; `contributing` 200); then
**C** (fenced `just <recipe>` resolves to a recipe name parsed from `justfile`; fenced
`uv run --group dev pytest <path>` paths exist; backticked repo paths exist; and the bounded
allowlist executed with `subprocess.run` under a `tmp_path` `HOME`/`TMPDIR`, exit 0 asserted:
`uv run studyloop --version`, `uv run studyloop --help`, `uv run studyloop doctor --help`,
`git log -1 --format='%h %s' <sha>` for each F14 sha — nothing else executes);
**H** (first non-heading block is ≤ 3 sentences or a numbered list; ≥ 1 numbered list; one H1;
line cap; no `<!-- GUIDE-STUB -->`); **L** (local links and `#anchors` resolve; the router's H2
set equals F10 exactly); **M** (page 20: "design stage" in paragraph 1, a link containing
`module-contract-v1/proposal.md`, no fenced `studyloop module`/`studyloop drill` line, none of
`is available`, `install it`, `the index lists`; page 19: "proposal" in paragraph 1);
**F** (harness names/tiers read from `studyloop.harnesses.CORE_HARNESSES`/`PREVIEW_HARNESSES`;
markers read from `pyproject.toml` addopts; branch prefixes `feat fix docs test` — asserted on
every page that mentions them). Add the 16 new/extended page names to `_STUDYLOOP_EXAMPLE_DOCS`
in `test_docs_drift.py` (that is the only edit there).

Verify, in this order, and save transcripts under `evidence/A0/` with the command on line 1:
(1) `red.txt` — the new test fails on every stub (H: marker present, no numbered list) and on
nothing else; (2) `existing-green.txt` — `test_docs_drift.py`, `test_contributor_docs.py`,
`test_docs_harness_tier_contract.py` all pass with the stubs (the stubs contain no fenced
commands, so the Click-tree test is unaffected); (3) `just docs` strict passes. Commit:
`test(docs): contributor-guide drift test — red on the fifteen stubs`. Then run
`env -u VIRTUAL_ENV just preflight` once and paste its summary into your report (the `test` step
will show the new test's reds — that is expected and must be the ONLY red beyond the known
virgin-HOME failure).

## Report

Common §5 plus: the scaffold sha (`git rev-parse --short HEAD`) — the writers branch from it; the
exact `GUIDE_PAGES` tuple; which of the five patterns each page is subject to; the preflight
summary.
