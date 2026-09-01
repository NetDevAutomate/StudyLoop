# ADR-0007 — Dev-only vendored assets live in git, not in the wheel

Status: **Accepted** (2026-09-01)

## Context

`studyloop web --dev` swaps xterm.js for a ghostty-web canvas renderer. Ghostty
was evaluated and deliberately **not** promoted to production (OSC 52 clipboard
gap, stalled upstream release cadence), so it is a developer tool only — but its
vendored assets were shipping to every user, and its `.wasm` had dragged Git LFS
into the repository.

Three facts framed the decision.

**The wheel shipped 1.66 MB nobody uses.** `[tool.hatch.build.targets.wheel]`
declared only `packages = ["src/studyloop"]`, so hatchling took everything under
the package directory. Seven ghostty files totalling 1,743,013 bytes reached every
install, for a code path no user can reach.

**LFS was managing a 423 KB file.** `.gitattributes` carried a blanket
`*.wasm filter=lfs`, added in `bbef893` for the in-browser Kokoro TTS engine's
22.8 MB `ort-wasm-simd-threaded.jsep.wasm`. That engine was deleted in `3d1e18b`
(2026-08-23); the rule outlived it by nine days and its only remaining catch was
`ghostty-vt-0.4.0.wasm` at 423 KB — in a repository whose largest tracked file is
a 5.3 MB GIF sitting happily in plain git. GitHub warns at 50 MB. The LFS object
had never been uploaded, so `actions/checkout` failed on every job requesting
`lfs: true`: `test (3.12)`, `test (3.13)` and the docs `build`, none of which ran
a single test.

**There were two ghostty implementations.** A registry path (`dev_engines.py`)
and a deprecated inline `dev_renderer` path (`app.py`), the latter shipping a
byte-identical second copy of the 624 KB bundle plus a bootstrap script. The
bootstrap was the *only* runtime consumer of the standalone wasm — the registry
bundle embeds the same wasm inline as a base64 data URL.

## Decision

**Dev-only vendored assets are tracked in git and excluded from the wheel.**

1. Deleted the deprecated inline `dev_renderer` path, the `--dev-renderer` flag,
   the duplicate `*.umd.js`, the bootstrap script, and the standalone wasm.
2. Removed Git LFS entirely — `.gitattributes` deleted, `lfs: true` removed from
   `ci.yml` and both `docs.yml` jobs.
3. Moved the surviving assets to `static/vendor/dev/` and excluded that
   directory from the wheel.
4. `resolve_dev_engine()` now refuses to start dev mode when the assets are
   absent, naming the reason.

### Why a directory and not a filename glob

The exclusion targets a **directory**, not `**/ghostty-*`. This repository has
twice been damaged by name-based rules that outlived their intent: the blanket
`*.wasm` above, and a bare `lib/` in `.gitignore` that silently untracked two
production SPA modules (`chunk-text.js`, `timer-thresholds.js`) for the whole
project history, so a fresh clone shipped a broken app while every local gate
passed. A glob would silently ship the *next* dev-only asset. A directory whose
name states the contract cannot drift.

### Why not a branch, submodule, or download-at-setup

The requirement was that dev mode works across machines from a checkout.

- **Long-lived dev branch** — rots. The 55 ghostty tests drive
  `_playwright_helpers.py` and `e2e/_env.py`, both of which change often. CI
  triggers on main, so the branch would never run. And StudyLoop is a global
  `uv tool` editable install hardcoding the main-tree src path, so worktrees are
  not viable and switching means swapping the whole checkout.
- **Submodule** — makes "across machines" *worse*: an extra clone step and a
  second repository to keep in step, for one 668 KB directory.
- **Git LFS** — the wrong tool at this size, as above.
- **Download at dev-setup** — trades a tracked file for a network dependency and
  a URL that can 404, and breaks offline work.

## Consequences

The wheel no longer carries any `vendor/dev/` file. `--dev` works from any
checkout on any machine; from a wheel install it fails with an explicit message
rather than serving a page whose terminal never initialises. All 55 ghostty tests
keep running on main against the harness they depend on.

`tests/test_dev_asset_packaging.py` enforces the contract **both ways**: the
wheel must not contain the assets, and the repo must. A one-sided assertion would
also pass if someone deleted them — which is exactly how the `js/lib` breakage
reached a release.

`git ls-files` is used for the tracked-ness assertion, never `git status`:
status lists only *changed* files, so its silence proves nothing about whether a
file is tracked. That mistake produced three false "file does not exist" findings
during the 0.1.0 review.

Historical commits keep their LFS pointers, so checking out a pre-0.1.0 commit
would still want objects that were never uploaded. CI is unaffected: `ci.yml`
uses the default `fetch-depth: 1` and no workflow requests LFS any more.
