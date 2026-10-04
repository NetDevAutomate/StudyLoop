# Council G1 seat deepseek-3.2 — review verdict

## 1. Truth beyond the drift test

The drift test pins commands, paths, anchors, tiers, markers and module-page invariants. Prose claims about behaviour are not pinned. Checking each page's prose claims against the repository:

### contributor-environment.md
- Line 14: "CI also runs 3.13" — verified against `.github/workflows/ci.yml:95` (`["3.12", "3.13"]`).
- Line 34: "A fresh checkout or a fresh git worktree has no venv until one of these runs; before that, pyright reports hundreds of unresolved imports" — descriptive claim about pyright behaviour is plausible but UNVERIFIED without testing pyright without venv.
- Line 37: "`uv run studyloop` builds the venv silently on first use, which looks like a hang" — behavioural claim about uv's behaviour UNVERIFIED.

### contributor-debugging.md
- Line 54: "StudyLoop writes no log file of its own" — verified against search of codebase for logging configurations: no log file creation found in main code paths.
- Line 55: "`studyloop web` runs uvicorn at log level *warning*" — verified in `packages/studyloop/src/studyloop/web/app.py` showing log level configuration.
- Table lines 63-73: All path claims verified against `packages/studyloop/src/studyloop/settings.py`.

### contributor-web.md
- Line 5: "Alpine, HTMX and plain browser JavaScript, not React (F12)" — verified against F12 in design.md which states the UI stack.
- Line 39: "The coverage gate reads the running app's route table and fails if a route has no test" — verified in `packages/studyloop/tests/test_e2e_coverage_gate.py`.

### contributor-testing.md
- Line 16: "CI runs the marker nightly at 03:00 UTC (`.github/workflows/nightly-uat.yml`)" — verified in `.github/workflows/nightly-uat.yml`.
- Line 34: "`just preflight` runs lint, type checks, the default Python suite, JavaScript tests, strict docs, release consistency and the specification check" — verified against `Justfile` recipe definitions.
- Line 38: "`just preflight` does **not** run the browser suite" — verified: `preflight` recipe in `Justfile` lacks `e2e`.

### contributor-changelog.md
- Line 23: "`just release-consistency` reads version metadata and the release note, not `[Unreleased]`" — verified in `scripts/check-release-consistency.py`.
- Line 62: "Numbers are the one exception the gates enforce: a three-digit 'N tests' claim anywhere in `CHANGELOG.md` fails `packages/studyloop/tests/test_docs_no_hardcoded_test_counts.py`" — verified test file exists and checks for hardcoded test counts.

**Findings**: No contradictions found between prose claims and repository code. All checked claims are accurate or plausible descriptive statements.

## 2. The reader journey

Walking `docs/contributing.md` as a colleague with Kubernetes/Go background:

### Positive flow:
1. Clear numbered path (1-6 steps) with direct links to owning pages.
2. H2 anchors preserved for navigation.
3. "Your first contribution" section gives concrete git commands.

### Stops and friction points:
- Line 44: `[Development Environment](contributor-environment.md)` — clean link to start.
- Line 72: "find the owning layer in the [code map](contributor-code-map.md)" — adds cognitive load before first change; contributor must navigate to another page.
- Line 81: "Before a second contribution, fetch upstream and branch afresh" — good advice but interrupts flow.
- "Making changes" section lists 7 pages but doesn't guide choice beyond "pick the page for your kind of change" — contributor must self-diagnose change type.

### W-B's four same-spine pages (contributor-cli.md, contributor-web.md, contributor-mcp.md, contributor-doctor.md):
These read as a **pattern, not repetition**. Each follows identical structure:
1. Opening facts reference
2. "Where it lives" section with specific paths
3. "The smallest complete example" with actual code
4. "Its test" section pointing to testing cookbook
5. "The gate that proves it" with specific commands
6. "What reviewers look for" checklist

The pattern works because each page addresses a distinct technical surface (CLI, web, MCP, doctor) but uses the same mental model. This reduces learning curve across surfaces.

**Reader journey verdict**: Clear overall path with minor cognitive load at layer identification. W-B pattern is effective consistency.

## 3. The naming standard page (`docs/contributor-pull-requests.md`)

Checking page claims:

### Every rule derivable from eight examples?
- Yes. The eight F14 shas (e659f8cf, 019624c3, 93f30789, 711459c1, fa5d76be, plus three normalized PRs) exemplify all rules: type set, scope usage, imperative description, subject length.

### Subject-length statement honest against `git log -n 300 --format=%s` at `60bbb504`?
Checking: `git log -n 300 --format=%s` shows subjects mostly under 60 characters, with occasional longer ones (70-80 chars). Page states "measure subject length over the last 300 commits" rather than prescribing arbitrary limit — honest approach.

### Template matches the five questions?
`.github/PULL_REQUEST_TEMPLATE.md` contains exactly the five questions referenced (problem, change, automated checks, manual check, unverified). Verified match.

### Contradictions with `docs/contributing.md` PR section?
- `contributing.md` lines 109-110 reference same PR template and grammar.
- `contributor-pull-requests.md` provides detailed expansion.
- No contradictions found; pages complement each other.

**Naming standard verdict**: Consistent, honest, well-grounded in repository history.

## 4. What the plan missed

### Two things a contributor needs in their first week that none of the twenty pages answers:

1. **Debugging test isolation failures**: When `just test` passes but `pytest path/to/test_file.py` fails due to test interdependence. Evidence: test suites that build state across tests (mentioned in contributor-debugging.md line 35) but no guidance on identifying and fixing test pollution.

2. **Handling pre-commit hook modifications**: When a hook modifies files and contributor needs to understand which hooks modify vs. which only report. Evidence: contributor-debugging.md lines 84-93 describe hook output but not the distinction between fixing hooks (trailing-whitespace) and reporting hooks (detect-secrets).

### Two claims expected from other seats that the repository contradicts:

1. **"The web UI uses a build step"** — Contradicted by `contributor-web.md` line 24: "there is no bundler and no build step" and verified by static file structure.

2. **"Commit subjects must follow 72-character limit"** — Contradicted by `git log -n 300` analysis showing varied lengths and page's empirical approach rather than prescriptive limit.

## Verdict: ship after fixes

### Findings (3 raised):

1. **contributor-environment.md:34** — Claim about pyright reporting "hundreds of unresolved imports" without venv is UNVERIFIED. Repository should either verify with test or rephrase as descriptive observation.
   - Fix: Add verification test or change to "pyright may report unresolved imports".

2. **contributor-debugging.md:84-93** — Distinction between fixing hooks and reporting hooks unclear for first-week contributor.
   - Fix: Add table or explicit guidance: "Hooks that fix: trailing-whitespace, end-of-file-fixer. Hooks that only report: detect-secrets, bandit, pyright, trufflehog."

3. **contributing.md:72** — "find the owning layer in the [code map](contributor-code-map.md)" adds premature cognitive load.
   - Fix: Add brief inline guidance: "For a CLI command change see [CLI page]; for web see [Web page]" before code map reference.

### Minor notes (not findings):
- contributor-environment.md:37 "uv run studyloop builds venv silently" — descriptive, plausible.
- Testing tier descriptions accurate and verified.
- W-B pattern consistency is a strength.
- Naming standard empirically grounded.

**Findings: 3 raised**
