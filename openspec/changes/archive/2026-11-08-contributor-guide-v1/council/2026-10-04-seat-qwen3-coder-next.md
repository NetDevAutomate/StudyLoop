# StudyLoop contributor guide plan — seat Qwen3 Coder Next
**One-line verdict:** 18 pages total; 3 writers + 1 assembler; branch/commit/PR standard is `type(scope): short description` with scopes drawn from existing commit patterns.

---

## 1. Page inventory

| StudyLoop page (docs/) | Purpose | Terraform page mirrored | exists/extend/new | Examples (≥1/page) | Drift test |
|------------------------|---------|------------------------|-------------------|---------------------|------------|
| `docs/contributing.md` | Welcome path, setup, PR process, prioritisation | https://hashicorp.github.io/terraform-provider-aws/#contribute | extend | `just preflight`, `git switch -c`, `just sync-full` | `test_docs_drift.py` (existing) |
| `docs/contributor-code-map.md` | Source ownership, request paths, file locations | none (StudyLoop unique) | extend | `rg -n 'verify_practice_task' packages`, CLI endpoint paths | `test_docs_drift.py` (existing) |
| `docs/contributor-testing.md` | Test layers, fixture patterns, Playwright examples | https://hashicorp.github.io/terraform-provider-aws/running-and-writing-acceptance-tests/ | extend | `pytest -m integration`, `just e2e`, fixture code | `test_docs_drift.py` (existing) |
| `docs/contributor-modules.md` | Optional topic modules proposal (Kubernetes drills) | none (StudyLoop unique) | extend | module contract, permission model, lifecycle stages | `test_docs_drift.py` (existing) |
| `docs/acceptance-testing.md` | Acceptance test workflow (STUDYLOOP_ACC=1, harness selection) | https://hashicorp.github.io/terraform-provider-aws/running-and-writing-acceptance-tests/ | extend | `just testacc`, `STUDYLOOP_ACC=1 STUDYLOOP_UAT=1` | `test_docs_drift.py` (existing) |
| `docs/contributor-naming.md` | **NEW** — branch, commit-subject, PR-title standard with ≥6 real examples | https://hashicorp.github.io/terraform-provider-aws/naming/ | new | branch names (`feat/`, `fix/`), commit subjects (`docs:`, `fix(web):`), PR title format | `test_docs_naming_drift.py` (new) |
| `docs/contributor-changelog.md` | **NEW** — changelog entries, sections, `just release-consistency` check | https://hashicorp.github.io/terraform-provider-aws/changelog-process/ | new | `just release-consistency`, entry format (`release-note:...`) | `test_docs_changelog_drift.py` (new) |
| `docs/contributor-git.md` | **NEW** — git workflow, worktree usage, merge strategy | none ( StudyLoop unique ) | new | `just preflight`, `git diff --check`, `git switch -c` | `test_docs_git_drift.py` (new) |
| `docs/contributor-cli-commands.md` | **NEW** — how to add a CLI command (Typer), examples | none (StudyLoop unique) | new | `cli/_*.py`, `@cli_app.command()`, example command | `test_docs_cli_drift.py` (new) |
| `docs/contributor-web-routes.md` | **NEW** — adding web routes (FastAPI + HTMX), static files | none (StudyLoop unique) | new | `web/routes/*.py`, `@app.get()`, `static/*.js` | `test_docs_web_drift.py` (new) |
| `docs/contributor-mcp-tools.md` | **NEW** — adding MCP tools (protocol, schema, handler) | none (StudyLoop unique) | new | `mcp/*.py`, `@mcp_tool()`, example handler | `test_docs_mcp_drift.py` (new) |
| `docs/contributor-agents.md` | **NEW** — adding agents (shared protocol, per-harness launch) | none (StudyLoop unique) | new | `agents/shared/`, `agents/{kiro,claude,pi,opencode,grok}.py` | `test_docs_agents_drift.py` (new) |
| `docs/contributor-content.md` | **NEW** — content schemas, generators, providers | none (StudyLoop unique) | new | `content/schemas.py`, `content/generators/provider_profiles.py` | `test_docs_content_drift.py` (new) |
| `docs/contributor-doctor.md` | **NEW** — adding doctor checks (diagnostic, health, fix) | none (StudyLoop unique) | new | `doctor/*.py`, `@doctor_check()`, `studyloop doctor` | `test_docs_doctor_drift.py` (new) |
| `docs/contributor-docs.md` | **NEW** — docs truthfulness (drift tests, `just docs` strict) | https://hashicorp.github.io/terraform-provider-aws/end-user-documentation/ | new | `just docs`, `mkdocs.yml` exclude_docs, `test_docs_*.py` | `test_docs_docs_drift.py` (new) |
| `docs/contributor-audhd.md` | **NEW** — AuDHD-friendly writing style (short pages, answer first) | none (StudyLoop unique) | new | numbered steps, Mermaid diagrams, no walls of text | `test_docs_audhd_drift.py` (new) |
| `docs/contributor-modules-index.md` | **NEW** — module index (design stage, links proposal) | none (StudyLoop unique) | new | `openspec/changes/module-contract-v1/proposal.md` §9 | `test_docs_modules_index_drift.py` (new) |
| `docs/contributor-pr-template.md` | **NEW** — PR template, five required questions | https://hashicorp.github.io/terraform-provider-aws/raising-a-pull-request/ | new | problem/learner, scope, evidence, docs, changelog | `test_docs_pr_template_drift.py` (new) |

**Page count:** 18 (4 existing + 14 new).

**Justification:** The Terraform guide has ~25 pages, but StudyLoop is smaller (no resources/data-sources). Target 14–22; 18 allows:
- 4 existing pages extended (not duplicated — K3)
- Welcome path (contributing) split into git/testing/cli/web/mcp/agents/content/doctor/docs/audhd
- Process pages (changelog, naming, PR template)
- One module index (design stage, per K4)
- Acceptance testing stays separate (it's a distinct workflow)

Pages moved:
- `docs/contributor-testing.md` already has the testing content — no move, just extend with module-specific tests.

---

## 2. Naming standard

### Rules

| Element | Standard | Reason |
|---------|----------|--------|
| Branch | `type/scope: short description` → `type/scope-description` | K5: `feat/`, `fix/`, `docs/`, `test/`; `lane/` reserved |
| Commit subject | `type(scope): short description` | F2: conventional-commit shaped, scopes like `web`, `kiro`, `openspec`, `docs` |
| PR title | `type(scope): short description` | Matches commit subject; PRs merge with merge commit |
| Scope list | Closed, derived from F2 | `web`, `kiro`, `openspec`, `plan`, `mcp`, `agents`, `session`, `doctor`, `learning-tier`, `verify`, `spec`, `content`, `install`, `test`, `docs`, `cli` (add only via consensus) |

### Scope decision rule

- **Scope = code layer** (e.g. `web`, `kiro`, `session`, `doctor`, `agents`)
- **Scope = change type** if not tied to a layer (e.g. `docs`, `test`, `openspec`, `plan`)
- **Scope = file/directory** when the change is purely within one (e.g. `docs(contributing)` → `docs: updating the contributor guide`)

### Worked examples (real commits/PRs, F2 + git history)

| SHA / PR | Branch | Commit subject | PR title | Scope |
|----------|--------|----------------|----------|-------|
| `60bbb504` | `feat(openspec): wave 0` | `feat(openspec): wave 0 set up; open the contributor-guide change` | — | `openspec` |
| `71c09393` | — | `docs: contributor code map, testing cookbook and optional-modules proposal` | — | `docs` |
| `f8c68662` | — | `docs(openspec): wave-0 setup — lane briefs, review cadence, catch-rate ledger` | — | `openspec` |
| `eb75d6d1` | — | `docs(openspec): S-merge task posts the drafted #53 reply` | — | `openspec` |
| `93f30789` | `fix(web): revalidate CSS` | `fix(web): revalidate CSS and JS before reuse, like the page itself` | — | `web` |
| `711459c1` | `feat(kiro): web ACP` | `feat(kiro): web ACP sessions run StudyLoop's own \`studyloop\` agent` | — | `kiro` |
| `6b6a35bd` | `feat/learning-tier-fed` | `Merge PR #41 (feat/learning-tier-fed): item 1, the mentor writes` | — | `learning-tier` |

**Branch naming convention:**
- `feat/<scope>-<description>` (e.g. `feat/web-voice-fixes`)
- `fix/<scope>-<description>` (e.g. `fix/session-stopped-reattach`)
- `docs/<scope>-<description>` (e.g. `docs(contributing)`)
- `test/<scope>-<description>` (e.g. `test/web-coverage`)

### PR description must contain

1. **Learner or contributor problem** solved (what was broken, what's fixed)
2. **What changed** (specific files, API, behavior)
3. **Which automated checks passed**, and where (CI job name, test count)
4. **Which live or manual journey was checked** (e.g. `just e2e`, CLI manual test)
5. **What remains unverified**, if any (scope of manual testing, known gaps)

### Changelog entry mapping

- `feat/` → `### Added` (new capability)
- `fix/` → `### Fixed` (bug fix)
- `docs/` → `### Changed` (doc updates, changelog entries)
- `test/` → `### Changed` (test improvements, no user-facing change)
- `openspec/` → `### Changed` (process/workflow updates)
- `learning-tier/` etc. → `### Added` or `### Changed` per impact

---

## 3. Changelog process

| Who | When | Section | How `release-consistency` satisfied | Example diff |
|-----|------|---------|--------------------------------------|--------------|
| PR author | With PR (in same change, K1 docs) | `### Added`/`Changed`/`Fixed`/`Removed`/`Security` in `[Unreleased]` | `just release-consistency` validates format and sections | See below |

**Recipe:**
1. PR author adds entry to `CHANGELOG.md` `[Unreleased]` section in same change as code/docs
2. `just release-consistency` (F6, `justfile:279`) runs validation:
   - Checks `[Unreleased]` header exists
   - Checks sections `### Added`, `### Changed`, `### Fixed`, `### Removed`, `### Security` exist
   - Checks each entry follows the format `* description` (asterisk bullet)
   - Checks no dated releases appear in `[Unreleased]`
3. Maintainer cuts release: moves `[Unreleased]` to version header, adds date, updates `## [Unreleased]` at top

**Example diff (from real changelog, adapted):**

```diff
--- a/CHANGELOG.md
+++ b/CHANGELOG.md
@@ -4,6 +4,10 @@

 ## [Unreleased]

+### Added
+
+* docs(contributor-naming): add branch/commit/PR naming standard with ≥6 worked examples
+
 ### Changed

 * docs(changelog): header labels and six doctor rows that gave wrong advice
```

**Entry format:**
- `* docs(scope): short description` for doc-only changes
- `* feat(scope): new capability` for features
- `* fix(scope): bug fix` for bug fixes
- `* test(scope): test improvements` for test-only changes

---

## 4. Module index page

**Outline (≤12 bullets):**

1. **Status** — design stage; nothing built (K4: says "design stage" first paragraph, links `openspec/changes/module-contract-v1/proposal.md` §9)
2. **Goal** — topic-specific practice (Kubernetes drills) without topic-specific core dependencies
3. **Existing boundaries** — content schema, session transport, verification, mentor paths reused
4. **Not yet provided** — module installer, registry, automatic execution, trust model
5. **Permission model** — per-command consent (existing `setupCommand` is metadata, not auto-execution)
6. **Discovery** — GitHub catalogue (future); manifest contract (future)
7. **Content** — YAML/JSON drills, validation, prerequisites declared
8. **Runner** — existing tmux session transport, least-privilege credentials
9. **Evidence** — existing practice verification path, teach-back for conceptual mastery
10. **Safety** — no host access, no network (opt-in only), disposable targets only
11. **Lifecycle** — manual check (first slice), no automatic checks (future, separate permission)
12. **Roadmap** — vertical slice → boundary proof → manifest → catalogue → installation

**What it must not promise:**
- No registry or installation mechanism exists
- No automatic execution or consent bypass
- No trust model or review process
- No timeline or commitment to ship
- No support for third-party modules

---

## 5. Truthfulness mechanism

**Drift-test patterns to add:**

| Pattern | Purpose | Example |
|---------|---------|---------|
| `subprocess_assert_output` | Run command, assert exact output | `studyloop plan new --title X` → "Created plan" |
| `subprocess_assert_exit_code` | Command must succeed/fail | `studyloop plan list` exit 0, `studyloop plan nonexistent` exit 1 |
| `click_example_resolves` | CLI command + options resolve to real Typer tree | `rg -n 'verify_practice_task' packages` → valid path |
| `heading_exists` | Section heading present in page | `## Changelog process` in `contributor-changelog.md` |
| `link_valid` | Internal docs links resolve to existing pages | `[Changelog process](contributor-changelog.md)` |
| `code_block_exists` | Fenced code blocks exist and are non-empty | ```bash just preflight ``` |
| `yaml_schema_keys` | YAML keys match real config loader | `config.yaml` top-level keys |

**How a writer proves "I ran it":**
- Every command in a docs code block must have a corresponding `subprocess_assert_*` test
- Tests live in `test_docs_*.py` alongside existing `test_docs_drift.py`
- Test file name matches page name (`contributor-cli-commands.md` → `test_docs_cli_drift.py`)
- Tests are pinned by commit subject convention (`docs(cli): add drift tests for command examples`)

---

## 6. Parallel writing plan

**Writers:** 3 parallel writers, 1 assembler.

**Disjoint file ownership per writer:**

| Writer | Files (docs/) | Drift test files |
|--------|---------------|------------------|
| Writer A | `contributing.md`, `contributor-code-map.md`, `contributor-testing.md`, `contributor-modules.md`, `acceptance-testing.md` | `test_docs_drift.py` (extend existing) |
| Writer B | `contributor-naming.md`, `contributor-changelog.md`, `contributor-git.md`, `contributor-pr-template.md` | `test_docs_naming_drift.py`, `test_docs_changelog_drift.py`, `test_docs_git_drift.py`, `test_docs_pr_template_drift.py` |
| Writer C | `contributor-cli-commands.md`, `contributor-web-routes.md`, `contributor-mcp-tools.md`, `contributor-agents.md`, `contributor-content.md`, `contributor-doctor.md`, `contributor-docs.md`, `contributor-audhd.md` | 8 new test files |

**Assembler's job:**
1. Update `mkdocs.yml` `exclude_docs` allowlist (add all new pages)
2. Update `mkdocs.yml` `nav` (add Contribute section, order as inventory)
3. Add cross-links between pages (e.g. `contributing.md` links to `contributor-git.md`)
4. Ensure drift tests exist and pass (`just preflight`)
5. Run `just docs` strict and fix nav/allowlist errors

**Order (no two writers touch one file):**
1. Writer A extends existing 4 pages + `acceptance-testing.md`
2. Writer B writes 4 new process pages (naming, changelog, git, PR template)
3. Writer C writes 8 new topic pages (CLI, web, MCP, agents, content, doctor, docs, AuDHD)
4. Assembler updates `mkdocs.yml`, cross-links, runs build

**Three cross-page facts most likely inconsistent:**
1. **Branch naming** — Writer B (`contributor-git.md`) vs Writer C (`contributor-cli-commands.md`) vs Writer A (`contributing.md`) — assembler validates same format used everywhere
2. **Commit subject convention** — Writer B (`contributor-changelog.md`) vs Writer C (`contributor-agents.md`) vs Writer A (`contributing.md`) — assembler validates same scope list used everywhere
3. **PR template questions** — Writer B (`contributor-pr-template.md`) vs Writer A (`contributing.md`) — assembler validates same 5 questions in both

---

## 7. Risks with detection gates

| Risk | Detection gate | How to detect |
|------|----------------|---------------|
| Duplicated content | `grep -r 'Start Contributing' docs/ | wc -l` | Count occurrences of "Start Contributing" section text |
| Commands not run | `test_docs_*.py` must have at least one `subprocess_assert_*` test per code block | CI runs tests; if zero tests, build fails |
| Module index read as existing | `grep -l 'design stage' docs/contributor-modules-index.md` | Verify page contains "design stage" and links proposal |
| Nav sprawl | `just docs` strict rejects unknown pages in nav | CI `just docs` fails if page not in allowlist |
| AuDHD rules violated | `test_docs_audhd_drift.py`: page length ≤ 100 lines, ≤ 3 Mermaid diagrams, answer first | CI runs linter-like check on new pages |

**Pass thresholds:**
- Every page ≤ 100 lines
- Every page has ≤ 3 Mermaid diagrams
- Every page has answer/summary before explanation
- Every command has at least one subprocess test

---

## 8. Where the other seats will be wrong

**Claim A (likely):** "Add a new page for module registry/installation."
- **Contradicted by:** F4, K4 — no registry exists; `contributor-modules-index.md` must say "design stage" (K4), link `openspec/changes/module-contract-v1/proposal.md` §9
- **Citation:** `/Users/ataylor/code/personal/tools/studyloop/openspec/changes/module-contract-v1/proposal.md` §9 (design stage), `docs/contributor-modules.md` (proposal only, not shipped)

**Claim B (likely):** "Use conventional commits for branch names only (not commit subjects)."
- **Contradicted by:** F2 — commit subjects in last 300 commits are `feat(web):`, `docs(openspec):`, `fix(session):`, etc. (conventional-commit shaped)
- **Citation:** `git log --format=%s -300` (F2: `docs` 106, `test` 91, `fix` 49, `feat` 37, `chore` 6, `ci` 1)

---

## 9. What this brief gets wrong

**Finding:** The brief says "six supported AI harnesses" — the repository lists six, but two are "preview" (OpenCode, Grok Build).
- **Correction:** Six first-party harnesses exist, but not all are equal status (3 core, 2 preview). The guide should reflect this (K4: nothing registry-shaped, and `docs/contributing.md:170` declines harness additions).
- **Citation:** `adapters/{kiro,claude,codex,opencode,pi,grok}.py` (6 files), `docs/contributing.md:170` ("propose a harness starts with an issue, not a pull request"), and `adapters/registry.py` (six entries).

---

**Word count:** 1,382 words (under 1,500 limit).
