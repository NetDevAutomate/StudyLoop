# Raising a Pull Request

<!-- facts: F1 F3 F13 F14 -->

Branch as `<type>/<short-slug>`, write every commit subject and the PR title as
`<type>(<scope>): <imperative description>`, and answer the five questions in the description.
This page is the naming standard: the grammar, the closed set of types the history actually uses,
eight real commits as examples, and what the reviewer and the merge then do.

## 1. The grammar

```text
<type>(<scope>): <imperative description>        # commit subject AND pull-request title
<type>: <imperative description>                 # cross-cutting: scope omitted
```

1. **type** — a closed set of six, the ones the history uses: `feat` `fix` `docs` `test` `chore`
   `ci`. Over the 300 commits at `60bbb504` they appear 37 · 49 · 107 · 90 · 6 · 1 times, plus four
   merge commits (F13). Adding a type is a change to this page.
2. **scope** — open: the smallest stable subsystem the change lands in (`web`, `mcp`, `doctor`,
   `agents`, `plan`, `now`, `session`, `openspec`, …). `docs(openspec)` for change records and
   specs; `docs(contributing)` for this guide. Omit it only when the change is genuinely
   cross-cutting — 286 of the last 300 subjects carry a scope.
3. **description** — imperative, states the *outcome* ("give the voice probe a budget"), no
   trailing period. A red-first commit may read `test(scope): RED — …` (example 5); a PR title may not.
4. **Length — the honest limit.** Measured over the 300 subjects at `60bbb504`: median 85
   characters, mean 90, longest 163; 71 % fit in 100 and 88 % fit in 120, but only 24 % fit in 72.
   So: aim under 100, treat 120 as the ceiling, and do not expect a 72-character rule here — the
   history does not keep one and this page will not claim it.

Merge commits are the maintainer's and sit outside the grammar: the three PR merges read
`Merge PR #NN (branch): subject` (F13), and six older local merges read lowercase "merge:".

## 2. Branch names

Name the branch `<type>/<short-slug>` with type one of `feat`, `fix`, `docs`, `test` — for example
`docs/first-contribution` or `fix/ws-drained-pull-future`. `lane/` is reserved for the maintainers'
remediation lanes and carries an ownership test that only makes sense there (F1). Outside
contributors branch in their fork and open the PR against `main`; review comments are addressed on
the same branch.

## 3. Eight real examples

Every sha below is in the history; run the line yourself and compare:

```bash
git log -1 --format='%h %s' e659f8cf
```

Five ordinary subjects:

| sha | subject | what makes it right |
| --- | --- | --- |
| `e659f8cf` | `fix(web): give the voice health probe a budget a healthy host fits in` | type + scope, imperative, names the outcome not the diff |
| `019624c3` | `fix(mcp): record_teachback refuses blank concept/topic and names its failure honestly` | the subject is the behaviour a reviewer can test |
| `93f30789` | `fix(web): revalidate CSS and JS before reuse, like the page itself` | the analogy explains the rule in six words |
| `711459c1` | ``feat(kiro): web ACP sessions run StudyLoop's own `studyloop` agent`` | `feat` for a new capability; scope is the harness it lands in |
| `fa5d76be` | `test(now): RED — a plan-related active primary carries a warm-up first move on its own material (rubric 3c (e1))` | a red-first commit, labelled RED; long but every word is the assertion |

Three merged PRs, whose titles carried no type (F13), shown **normalised** to the grammar:

| merge sha | PR | normalised title |
| --- | --- | --- |
| `2883588f` | #40 | `fix(web): read a done pull future on every WS pump exit` |
| `6b6a35bd` | #41 | `feat(learning-tier): the mentor writes learning events` |
| `8d31f1ec` | #42 | `fix(gate): give the coverage self-test its own timeout` |

Want another example on this page? Run `git log -1 --format='%h %s' <sha>`, paste the output
into the receipt file first, then into the page — never from memory.

## 4. The description answers five questions

`.github/PULL_REQUEST_TEMPLATE.md` pre-fills them as headings; keep the headings, write under
each, delete nothing (F3):

1. What learner or contributor problem does this solve?
2. What changed? — include the `[Unreleased]` bullet you added, or "no changelog entry" and why,
   and whether an AI assistant helped (the [AI usage page](contributor-ai.md) says how).
3. Which automated checks passed, and where? — name the gates and the evidence paths.
4. Which live or manual journey did you check yourself? — for a web change, `uv run studyloop web`
   (port 8567, loopback only unless `--bind`; open the printed sign-in address) is the app you walk.
5. What remains unverified?

Automated green and a manual check are separate claims; state both. "Nothing" under 5 is fine when
it is true.

## 5. Before you open it

- `just preflight` green (lint, typecheck, test, test-js, docs, release-consistency, spec-check),
  `git diff --check` clean, no conflict markers (a repository test scans for them).
- The changelog bullet is written: one per user-visible change, `feat`→Added, `fix`→Fixed,
  behaviour change→Changed, removal→Removed, security→Security; `test`, `docs`, `chore`, `ci`
  normally none — the [changelog page](contributor-changelog.md) has the table.
- One problem per PR. Small PRs are reviewed faster and reverted more safely.

## 6. What a reviewer checks

1. The subject and title follow the grammar above; the branch prefix is one of the four.
2. Every claim in the description against the code — `file:line` references are checked, not
   trusted; a test that would not fail on revert is sent back.
3. The changelog bullet matches question 2 and reads in the learner's words.
4. Docs changed in the same PR when behaviour did; `just docs` is strict and the drift tests pin
   commands and paths, so a stale command fails — a stale sentence is the reviewer's to catch.
5. Nothing private: no learner transcripts, keys or full local configuration in code, fixtures or
   screenshots.

## 7. How a merge happens

The maintainer merges, so far always with a **merge commit** whose subject is
`Merge PR #NN (branch): subject` (F1, F13); the branch's commits are kept as they were. Merged work
ships in the next release, when the maintainer dates your `[Unreleased]` bullet. A PR may also be
closed without merging; the reason is written on it.
