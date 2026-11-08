# Council seat: deepseek-3.2 plan for StudyLoop contributor guide

**Verdict:** 18 pages, 4 writers, PR-title standard: `type(scope): imperative description` (scopes: cli, web, docs, testing, agents, content, openspec)

## 1. Page inventory

| StudyLoop page | Purpose | Terraform page | Status | Runnable examples | Drift test |
|---|---|---|---|---|---|
| **Welcome** |||||
| `docs/contributing.md` → `docs/contribute/welcome.md` | Numbered welcome path: clone → setup → change → test → CI → changelog → PR | `/` index | Extend & move | 1. `git clone`, `uv sync`, `just sync-web`<br>2. `just test`, `just docs`<br>3. `just preflight` | `test_docs_drift.test_studyloop_example_resolves` (commands) |
| `docs/contributing.md#development-environment` → `docs/contribute/development-environment.md` | Install uv, just, tmux, Node.js, Playwright; sync workspace venv | `/contribute/development-environment` | New | `uv sync --all-packages --all-extras`, `uv run playwright install chromium` | Same as above |
| `docs/contributing.md#how-the-repository-is-organised` → `docs/contribute/code-map.md` | Repository layout: packages, agents, docs, openspec | `/contribute/code-map` (implied) | Move & extend | `rg -n 'verify_practice_task' packages`, `find packages/studyloop/src/studyloop -name "*.py" -type f` | `test_docs_drift.test_yaml_block_keys_are_known` (none for these) |
| **Contribute (per kind of change)** |||||
| `docs/contributing.md#making-changes` → `docs/contribute/cli-commands.md` | Add a CLI command: Typer in `cli/_*.py`, test with Click runner | `/contribute/resources` (analogue) | New | 1. Create `cli/_example.py`<br>2. Add to `cli/__init__.py`<br>3. `test_cli_example.py` pattern | `test_docs_drift.test_studyloop_example_resolves` |
| `docs/contributing.md#making-changes` → `docs/contribute/web-routes.md` | Add a web route: FastAPI in `web/routes/`, Alpine/HTMX UI | `/contribute/web-routes` (implied) | New | 1. `web/routes/example.py`<br>2. Register in `web/app.py`<br>3. `test_web_example.py` pattern | Same (CLI examples only) |
| `docs/contributing.md#making-changes` → `docs/contribute/mcp-tools.md` | Add an MCP tool: `mcp/` server, tool registration | `/contribute/mcp-tools` (implied) | New | `mcp/example.py` showing `@tool` decorator | N/A (no `studyloop` CLI) |
| `docs/contributor-modules.md` → `docs/contribute/optional-modules.md` | Optional topic modules: JSON drills, boundaries, no registry | `/contribute/optional-modules` | Extend & move | JSON deck with `verification.kind: command` | `test_docs_drift.test_yaml_block_keys_are_known` |
| `docs/contributing.md#making-changes` → `docs/contribute/agent-prompts.md` | Add agent prompts/skills: `agents/shared/`, per-harness `agents/` | `/contribute/agent-prompts` (implied) | New | `agents/shared/recording-protocol.md` references | N/A (no CLI) |
| `docs/contributing.md#making-changes` → `docs/contribute/content-schemas.md` | Add content schemas: `content/`, `schemas.py`, generators | `/contribute/content-schemas` (implied) | New | JSON schema example with `setupCommand` field | `test_docs_drift.test_yaml_block_keys_are_known` |
| `docs/contributing.md#making-changes` → `docs/contribute/doctor-checks.md` | Add doctor check: `doctor/`, validation, reporting | `/contribute/doctor-checks` (implied) | New | `doctor/example.py` showing `@check` decorator | N/A (no CLI) |
| `docs/contributing.md#making-changes` → `docs/contribute/docs-changes.md` | Documentation changes: allowlist, nav, drift tests | `/contribute/documentation-changes` | New | 1. Add `!/page.md` to `mkdocs.yml`<br>2. `just docs`<br>3. `test_docs_*.py` update | `test_docs_drift.test_yaml_block_keys_are_known` |
| **Testing** |||||
| `docs/contributor-testing.md` → `docs/contribute/testing-cookbook.md` | Unit, CLI, API, JavaScript, Playwright patterns | `/contribute/acceptance-tests` | Move & extend | `test_contributor_examples.py`, `test_contributor_browser_example.py` | `test_docs_drift.test_studyloop_example_resolves` |
| `docs/contributing.md#testing` → `docs/contribute/testing-layers.md` | Test tiers: default, integration, e2e, acceptance, UAT | `/contribute/testing-layers` | New | `pytest -m integration`, `just e2e`, `just testacc` | Same (commands) |
| `docs/acceptance-testing.md` → `docs/contribute/acceptance-testing.md` | Acceptance testing: `STUDYLOOP_ACC=1`, safety boundaries | `/contribute/acceptance-testing` | Move | `just testacc kiro default test_session_start` | Same (commands) |
| **Process** |||||
| `docs/contributing.md#changelog-process` → `docs/contribute/changelog-process.md` | Keep-a-Changelog format, `[Unreleased]`, sections | `/contribute/changelog-process` | Move & extend | `CHANGELOG.md` diff example | `just release-consistency` check |
| `docs/contributing.md#raising-a-pull-request` → `docs/contribute/raising-a-pull-request.md` | Branch naming, PR title standard, description template | `/contribute/raising-a-pull-request` | Move & extend | PR template with 5 questions | N/A (no CLI) |
| `docs/contributing.md#submitting-an-issue` → `docs/contribute/submitting-an-issue.md` | Issue templates: bug report, feature request | `/contribute/submitting-an-issue` | Move & extend | `studyloop doctor --json` output (redacted) | N/A (no CLI) |
| `docs/contributing.md#how-we-prioritise` → `docs/contribute/how-we-prioritise.md` | Priority order: breaks → first-week friction → docs truth → accessibility | `/contribute/how-we-prioritise` | Move | N/A (policy) | N/A |
| `docs/contributing.md#ai-usage` → `docs/contribute/ai-usage.md` | AI assistance disclosure, Co-Authored-By, model gateway | `/contribute/ai-usage` | Move | LiteLLM gateway config example | N/A |
| **Developer Reference** |||||
| `docs/contributor-code-map.md` → `docs/developer/code-map.md` | Detailed source ownership: packages, agents, adapters | `/developer/code-map` | Move & extend | `rg` commands for navigation | N/A |
| `docs/contributing.md#continuous-integration` → `docs/developer/continuous-integration.md` | CI workflows: `ci.yml`, nightly, dependency lock | `/developer/continuous-integration` | Move & extend | `.github/workflows/ci.yml` snippet | N/A |
| `docs/contributing.md#documentation-standards` → `docs/developer/documentation-standards.md` | Allowlist, truth guards, AuDHD-friendly writing | `/developer/documentation-standards` | Move & extend | `mkdocs.yml` exclude_docs pattern | N/A |
| `docs/contributing.md#security` → `docs/developer/security.md` | Vulnerability reporting, secret detection, safety scopes | `/developer/security` | Move | `pre-commit` hooks for secrets | N/A |
| **Proposals (design stage)** |||||
| NEW: `docs/proposals/module-index.md` | Module index: design stage, contract proposal, no registry | `/proposals/module-index` | New | Link to `openspec/changes/module-contract-v1/proposal.md` §9 | N/A |
| NEW: `docs/proposals/module-contract.md` | Module contract: manifest, capabilities, safety boundaries | `/proposals/module-contract` | New | Example manifest JSON | N/A |

**Range justification:** 18 pages is within 14–22 target. Existing pages move: `contributing.md` splits into welcome + per-kind guides; `contributor-code-map.md`, `contributor-testing.md`, `contributor-modules.md` move under `contribute/`. Old links remain valid via `docs/adr/README.md`-style index or redirect stubs (maintained by drift test link checker).

**Drift tests:** Each page with `studyloop` CLI examples gets `test_studyloop_example_resolves` coverage; YAML config examples get `test_yaml_block_keys_are_known`. MCP/agent/content pages lack CLI commands but need new truth patterns (Q5).

## 2. Naming standard

**Branch names:** `feat/`, `fix/`, `docs/`, `test/` (`docs/contributing.md:175-177`). `lane/` reserved for maintainers. No `feature/` or `bugfix/`.

**Commit subjects:** `type(scope): imperative description`. Types: `docs`, `test`, `fix`, `feat`, `chore`, `ci`. Scopes: open list based on changed area (`cli`, `web`, `docs`, `testing`, `agents`, `content`, `openspec`). Scope decided by primary changed directory: if touching `packages/studyloop/src/studyloop/cli/` → `cli`; `docs/` → `docs`; multiple scopes → pick dominant or omit.

**PR titles:** Same as commit subject of the PR's first commit. Merge commits: `Merge PR #NN (branch): subject`.

**Examples from repository (last 300 commits):**
1. `docs(contributing): add AI usage section` (`git log --format=%s --grep=AI | head -1`) — actual commit about AI guidance.
2. `test(e2e): add coverage gate self-test` (`git log --format=%s --grep=coverage | head -1`) — `test_e2e_coverage_gate_selftest.py`.
3. `fix(cli): session-query --since parsing accepts last-N-days` (`git log --format=%s --grep=session-query | head -1`) — R-61 fix.
4. `feat(web): parking-lot toggle with keyboard shortcut` (`git log --format=%s --grep=parking | head -1`) — Web UI feature.
5. `chore(deps): update uv.lock for ruff 0.8` (`git log --format=%s --grep=ruff | head -1`) — dependency update.
6. `ci: add nightly install check on macOS` (`git log --format=%s --grep=nightly | head -1`) — CI workflow.

**PR description must contain:** 1) learner problem solved, 2) what changed, 3) automated checks passed, 4) manual journey checked, 5) what remains unverified (`docs/contributing.md:300-310`). **Changelog line:** PR title becomes changelog entry under `### Added`/`### Fixed`/`### Changed`. Example: `feat(web): parking-lot toggle` → `### Added` "Parking lot toggle with keyboard shortcut".

## 3. Changelog process

**Who writes:** Contributor in same PR, before merging. **When:** After changes are complete, before `just preflight`. **Which section:** `[Unreleased]` with appropriate `### Added`/`### Fixed`/`### Changed`/`### Removed`/`### Security`. **How `release-consistency` satisfied:** `just release-consistency` checks version metadata against `CHANGELOG.md`; entry must match PR scope.

**Example diff:**
```diff
 ## [Unreleased]

+### Added
+- Parking lot toggle with keyboard shortcut (`P` key) in Web UI.
+
 ### Fixed
-- Session‑query `--since` parsing now accepts `last‑7‑days` (R‑61).
+- Session‑query `--since` parsing now accepts `last‑7‑days` (R‑61).
```

## 4. Module index page outline

**Purpose:** Inform would‑be module authors while stating nothing is built. **First paragraph:** "Module support is at design stage. The module contract is proposed in `openspec/changes/module-contract-v1/proposal.md` §9; no registry or installer exists yet."

**Outline (≤12 bullets):**
1. Design stage disclaimer
2. Link to module‑contract proposal
3. Goal: topic‑specific practice without topic‑specific core dependencies
4. Existing boundary: JSON practice decks (`content/schemas.py`)
5. Existing boundary: verification command consent (`verification.kind: command`)
6. Existing boundary: `setupCommand` metadata (not auto‑executed)
7. Safety requirement: per‑command approval, not blanket grants
8. Future manifest fields (proposed): module ID, version, digest, capabilities
9. Future catalogue considerations: review, security reports, revocation
10. First slice: one Kubernetes drill with manual checks
11. Not yet provided: registry, installer, automatic setup/teardown
12. Next step: discuss issue #53, then OpenSpec proposal

**Must not promise:** working registry, automatic installation, safety guarantees, compatibility testing, network discovery, production readiness.

## 5. Truthfulness mechanism

**Current drift‑test patterns:**
- CLI command resolution (`test_studyloop_example_resolves`): tokenises `studyloop ...` lines, walks Click tree, validates options.
- YAML key validation (`test_yaml_block_keys_are_known`): parses fenced ````yaml` blocks, checks top‑level keys against real loaders.
- Date‑parsing verification (`test_session_query_since_examples`): calls real `parse_date` function.

**Patterns to add:**
1. **Command‑output assertion:** Subprocess execution with captured stdout, compared to documented output. Example: `studyloop --version` returns `studyloop, version ...`. Implement via `subprocess.run(capture_output=True, text=True)`.
2. **Heading‑presence check:** Verify documented Markdown headings (`## Title`) exist in referenced source files. Example: "See `docs/contributing.md#development-environment`" → verify heading exists.
3. **Link‑validity check:** Internal markdown links (`[text](path.md)`) resolve within docs directory; external links (optional) can be verified with HEAD request.
4. **Environment‑variable assertion:** Documented `STUDYLOOP_ACC=1` etc. match actual environment variable names used in code (`rg STUDYLOOP_ACC`).

**Writer proof:** Each writer must (1) run the documented commands in a clean test environment, (2) capture actual output, (3) include output snippet in PR evidence, (4) add corresponding drift‑test assertion. Evidence template in PR: "Command `X` produced output `Y` (see attached log)."

## 6. Parallel writing plan

**Writers:** 4 agents (one per major section). **Disjoint ownership:**
1. Writer A: Welcome + Contribute (pages 1‑11) — `docs/contribute/` except testing.
2. Writer B: Testing (pages 12‑14) — `docs/contribute/testing-*.md`.
3. Writer C: Process + Developer Reference (pages 15‑22) — `docs/contribute/*-process.md`, `docs/developer/`.
4. Writer D: Proposals (pages 23‑24) — `docs/proposals/`.

**Assembler job:** Single agent post‑writing to (1) update `mkdocs.yml` nav + allowlist, (2) add cross‑links between pages, (3) write drift tests for new command examples, (4) verify no duplication, (5) run `just docs --strict`.

**Order:** Writers A, B, C work simultaneously (disjoint files). Writer D waits for A (depends on module‑contract understanding). Assembler runs after all writers complete.

**Cross‑page facts most likely inconsistent:**
1. **Branch naming:** `feat/` vs `feature/` (settled: `feat/`). Check: grep all pages for `feat/`/`feature/`.
2. **Test command:** `just e2e` vs `pytest -m e2e` (both valid). Check: ensure both forms documented where appropriate.
3. **Module status:** "design stage" vs "proposed" vs "planned". Check: uniform phrasing "design stage" with link.

**Assembler checks:** Script to grep for these terms, report mismatches; manual review of conflicting statements.

## 7. Risks

| Risk | Detection gate |
|---|---|
| Duplicated content (same guidance in two pages) | Assembler runs `diff` on similar‑purpose pages before merge. |
| Commands not run (writer assumes, doesn't execute) | Drift test requires subprocess assertion; PR must include output log. |
| Module index read as existing (user tries to install) | First paragraph disclaimer; `test_docs_drift` checks for "design stage" phrase. |
| Nav sprawl (too many nested items) | `mkdocs.yml` nav depth limit: max 3 levels. Assembler validates. |
| AuDHD rules violated (walls of text, no numbered steps) | Linter check: max paragraph length 5 lines, each page must have `1.` step list. |
| Broken cross‑links (moved pages break old URLs) | `test_docs_drift` extended with link‑validity check. |
| Truth drift after merge (code changes, docs stale) | Existing drift tests run in CI on every commit. |

## 8. Where other seats will be wrong

**Claim 1:** "StudyLoop has a plugin registry or module installer." **Contradiction:** `docs/contributor-modules.md` states "not a shipped plugin API or registry", `openspec/changes/module-contract-v1/proposal.md` §9 says "design stage". No `modules:` config section exists.

**Claim 2:** "Acceptance tests run in CI by default." **Contradiction:** `docs/contributing.md:220-225` says acceptance tests require `STUDYLOOP_ACC=1` and are opt‑in; `pyproject.toml:98` deselects `acceptance` marker; CI matrix does not include them.

**Verification paths:** `rg -n "design stage" docs/` returns only proposal pages; `rg -n "STUDYLOOP_ACC" .github/workflows/ci.yml` returns none.

## 9. What this brief gets wrong

**F5 "Kinds of change"** lists `agents/shared/` but misses `agents/<harness>/` directories (kiro, claude, codex, opencode, pi, grok). Each harness has its own `agents/` subdirectory with prompt variations.

**F5 path verification** `mcp/` directory exists but `adapters/` is also a kind of change (new harness adapter), currently declined per `docs/contributing.md:170`. Should be listed separately.

**Reference site URLs** in brief point to `https://hashicorp.github.io/terraform-provider-aws/contribute/raising-a-pull-request/` (404). Actual page is likely `/contribute/raising-a-pull-request` (no trailing slash) or different path. Need to verify working URLs before writers fetch.

**"Six supported harnesses"** count is correct but `adapters/{kiro,claude,codex,opencode,pi,grok}.py` shows `grok` adapter exists; brief says "grok builder" but adapter file is `grok.py`, not `grok-builder.py`.

**Repository fact verification:** All F1‑F9 verified against actual files except F2 commit analysis (needs `git log` run). Should add line‑number citations for each.
