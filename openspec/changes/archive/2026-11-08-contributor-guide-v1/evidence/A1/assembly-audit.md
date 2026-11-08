# A1 assembly audit — 2026-10-04

Merged into `feat/contributor-guide` (scaffold `f2e1c70e`): `feat/contributor-guide-a` (W-A, 6
commits), `-b` (W-B, 4), `-c` (W-C, 5), `-d` (W-D, 6); four merge commits, no conflicts; the merged
diff touches only `docs/**`, `.github/PULL_REQUEST_TEMPLATE.md` and `evidence/W-*/commands.txt`.

- Stubs: `grep -l GUIDE-STUB docs/*.md` → none.
- Receipts: every fenced bash/sh/console command on the 19 `docs/contributing.md` +
  `docs/contributor-*.md` pages appears verbatim in a writer's `commands.txt` (35 + 16 + 11 + 8 = 70
  receipts). `docs/acceptance-testing.md`'s six pre-existing fenced commands are NOT receipted by
  policy (K1 forbids running `just testacc`); the drift test resolves them structurally and exempts
  that page from the structure checks by design (`test_contributor_guide_drift.py` line ≈138).
- PR page history: all nine shas re-run with `git log -1` — nine commits; the three PR shas are
  shown normalised per design.md §4 (the real merge subjects carry no type), `60bbb504` is the
  300-commit count anchor, the other five match their real subjects verbatim.
- H2 duplicate scan: the only repeated H2s are the five-step spine W-B's four pages share by
  design (`Where it lives` … `What reviewers look for`); no topic is explained on two pages.
- Typer: zero mentions in the guide (the CLI is Click; the planning brief was wrong, caught by
  W-B and W-C).
- `test_contributor_guide_drift.py`: 118 passed. Docs suites (`test_docs_drift`,
  `test_contributor_docs`, `test_docs_harness_contract`, `test_docs_harness_tier_contract`,
  `test_docs_architecture_contract`): 484 passed, 3 skipped (pre-existing YAML-block skips).
- `just docs` strict: built.
- `just preflight`: see `preflight.txt` beside this file (run detached after this commit).

Accepted deviations (not defects): W-B could not fence `uv run studyloop doctor` without putting the
owner's real config into a receipt — `doctor --help` is fenced instead and the exit-1-on-a-fresh-HOME
behaviour is stated in prose (W-A receipted exit=1 honestly); `just test-web` is a fixed file list,
stated on the web page as-is (follow-up: make the recipe a glob); the conventions page's note that
nothing in the tree reads `skip_specs: true` is true of the tree — the external `openspec` CLI reads
it (validation passed only after it was added) — wording tightened by A1 below.
