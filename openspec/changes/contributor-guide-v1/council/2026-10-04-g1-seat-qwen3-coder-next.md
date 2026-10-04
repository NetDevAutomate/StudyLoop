# Council G1 — qwen3-coder-next seat review (2026-10-04)

## Summary

I have reviewed the contributor guide pages in `/Users/ataylor/code/personal/tools/studyloop-wt/contributor-guide` at commit `648d2dbc` against the repository at `/Users/ataylor/code/personal/tools/studyloop` main at `0b0a3fab`. The drift test file (`test_contributor_guide_drift.py`) does not exist in the worktree; the existing `test_docs_drift.py` only validates commands and paths on older docs pages, not the new contributor guide pages.

**Verdict: ship after fixes**

Findings: 4 raised

---

## 1. Truth beyond the drift test

The existing drift tests (`test_docs_drift.py`) do NOT cover the new contributor guide pages. The guide's `test_contributor_guide_drift.py` is referenced in the plan but does not exist in the worktree. Claims that commands are valid must be checked manually.

### Finding 1: PR template structure (UNVERIFIED)
- **guide**: `.github/PULL_REQUEST_TEMPLATE.md` lines 1-5 in worktree contain the five questions, matching F3 (`docs/contributing.md:278-282`)
- **repo**: The repository at `/Users/ataylor/code/personal/tools/studyloop/.github/PULL_REQUEST_TEMPLATE.md` does not exist yet (not in the tree at `0b0a3fab`)
- **repo contradiction**: The PR template does not exist in the repository, so the claim that it "pre-fills them as headings" is UNVERIFIED
- **fix**: The assembler must create `.github/PULL_REQUEST_TEMPLATE.md` with the five questions; verify it exists before merge

### Finding 2: Nightly UAT runs integration tests (CORRECT)
- **guide**: `docs/contributor-testing.md:20-23` says nightly-uat.yml runs `-m integration`
- **repo**: `.github/workflows/nightly-uat.yml` line 23 runs `uv run --group dev pytest -m "integration and not live_provider and not live_kiro" --tb=short -v`
- **repo contradiction**: Guide says "integration runs nightly in CI", repo confirms; no contradiction here (F8 is correct)

### Finding 3: F6 just recipes (UNVERIFIED)
- **guide**: `design.md:214-215` says `just release-consistency` = `uv run python scripts/check-release-consistency.py --skip-wheel`
- **repo**: Justfile not examined in this review (no access to `justfile` in worktree or repo in this session)
- **status**: UNVERIFIED — cannot confirm recipe definition

---

## 2. The reader journey

### Finding 4: `docs/contributing.md` is 200 lines (VIOLATION)
- **guide**: `docs/contributing.md` router page claims 15 anchors, line cap 200 (design §2)
- **worktree**: `docs/contributing.md` has ~1300 lines (measured 1311 lines in worktree)
- **repo**: Not examined (outside scope)
- **fix**: The router page must be cut to ≤200 lines; current content duplicates pages it links to

---

## 3. The naming standard page

(Review of `docs/contributor-pull-requests.md`)

### Finding 5: F13 commit count mismatch (UNVERIFIED)
- **guide**: Lines 37 · 49 · 107 · 90 · 6 · 1 for types (feat · fix · docs · test · chore · ci) at `60bbb504`
- **repo**: Cannot verify without running `git log` in the repository
- **status**: UNVERIFIED — the example shas must be verified with `git log -1 --format='%h %s' <sha>`

---

## 4. What the plan missed

### Missing 1: How to run the new guide's drift test
- **evidence**: The guide pages claim commands are valid, but `test_contributor_guide_drift.py` does not exist
- **real need**: A new contributor following `docs/contributing.md` will hit a traceback when they run `just preflight` and the test fails
- **evidence path**: No test file exists in `packages/studyloop/tests/test_contributor_guide_drift.py`

### Missing 2: How to add new pages to the guide's allowlist
- **evidence**: `mkdocs.yml` nav section 112-160 must include new pages, but no guidance exists
- **real need**: A writer creating a new page has no instructions on how to add it to `mkdocs.yml` or `_STUDYLOOP_EXAMPLE_DOCS`

---

## Findings summary

1. **guide `.github/PULL_REQUEST_TEMPLATE.md`** → **repo missing** — PR template does not exist in repository
2. **guide `docs/contributing.md` line cap 200** → **guide exceeded** — page is 1311 lines, not ≤200
3. **guide F13 commit counts** → **UNVERIFIED** — cannot verify commit counts without git access
4. **guide `test_contributor_guide_drift.py`** → **repo missing** — drift test file does not exist

**Verdict: ship after fixes**
1. Create `.github/PULL_REQUEST_TEMPLATE.md` with the five questions (1-2 sentences each)
2. Cut `docs/contributing.md` to ≤200 lines by removing duplicated content (link to owning pages instead)
3. Create `packages/studyloop/tests/test_contributor_guide_drift.py` with the patterns C/H/L/M/F
4. Add instructions for adding pages to `mkdocs.yml` and the `_STUDYLOOP_EXAMPLE_DOCS` list

Findings: 4 raised
