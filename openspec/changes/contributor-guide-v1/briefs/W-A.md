# Brief W-A — welcome and the exit (five pages + the PR template)

Read `00-common.md`, then `design.md` §2 (your rows), §3 (all), §4 (the naming standard — you
write the page that states it), §6, and the Terraform pages you mirror (fetch: Welcome index,
Development Environment, Debugging, Changelog Process, Raising a Pull Request).

| | |
| --- | --- |
| Branch | `feat/contributor-guide-a` from the scaffold sha given in your dispatch |
| Worktree | `/Users/ataylor/code/personal/tools/studyloop-wt/contributor-guide-a` |
| Owns | `docs/contributing.md`, `docs/contributor-environment.md`, `docs/contributor-debugging.md`, `docs/contributor-changelog.md`, `docs/contributor-pull-requests.md`, `.github/PULL_REQUEST_TEMPLATE.md` (new), `evidence/W-A/` |
| Forbidden | every other `docs/` file, `mkdocs.yml`, `CHANGELOG.md`, any test file |

Order (one commit each): environment → debugging → changelog → pull-requests (+ template) →
contributing (last, because it links all four and every sibling page by its §2 path).

## Pages

1. **`contributor-environment.md`** — install uv, just, tmux, Node (for `just test-js`), Playwright
   Chromium; `just sync-dev` vs `sync-full`; prove the import; the TMPDIR/sqlite sandbox note as a
   "if you run agents" aside. Every command run and receipted; `uv run studyloop --version` and
   `uv run studyloop doctor` are the smoke checks.
2. **`contributor-debugging.md`** — the five-step frame (reproduce → isolate → read the error →
   check assumptions → trace), where logs and session state live (find and cite the real paths from
   the tree), running one test with `-x -vv`, reading a pre-commit failure, the e2e lock message.
3. **`contributor-changelog.md`** — design.md §4.1 "PR → changelog" and the arbitration's D5:
   contributor writes the `[Unreleased]` entry in the PR; sections; learner-terms wording; what
   `just release-consistency` really checks (F6) with the `--release`-only caveat; one example diff.
4. **`contributor-pull-requests.md`** — §4 verbatim in spirit: grammar, closed types with F13
   counts, open scope rule, branch names (F1), the eight F14 examples each with sha · subject · why
   it is right, the three normalised PR titles, the five questions (F3), the changelog mapping, what
   a reviewer checks, how a merge happens (merge commit). Measure subject length over
   `git log -n 300 --format=%s` and state the honest limit. `.github/PULL_REQUEST_TEMPLATE.md`:
   the five questions as headings with one-line prompts, nothing else.
5. **`contributing.md`** — rewrite as the numbered router: an answer-first paragraph, then the
   numbered path (environment → first change → test → gate → changelog → PR), each step 1-3
   sentences plus the link to the owning page. **Every H2 in F10 stays, in order, as an H2**, each
   reduced to its answer and a link; nothing restated. Keep `#your-first-contribution` as a real
   section (root `CONTRIBUTING.md` links it). ≤ 200 lines.

## Report

Common §5 plus: the measured subject-length figure; the receipt for every sha on the PR page.
