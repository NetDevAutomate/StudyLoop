# Contributor-guide briefs — common part (read first, then your own file)

You are one agent of the `contributor-guide-v1` build. The plan is
`openspec/changes/contributor-guide-v1/design.md` (read §1-§7 in full; §2 is the page
inventory, §3 the **verified facts sheet**, §6 the drift test) and `tasks.md`. This file plus
your own brief is your whole context (memory was withheld deliberately); if something you need is
in neither, **report the gap** in your final report — never guess, never recall from memory.

## 0. Where you work

- Your worktree and branch are named in your brief. Every read-for-edit, every shell command
  (`working_dir`), every test run and every commit happens there.
- The main checkout `/Users/ataylor/code/personal/tools/studyloop` is **read-only reference**. It
  holds another session's uncommitted work. Never write there, never `git add`/`stash`/`checkout`
  there, never run tools there.
- Sandbox facts (verified 2026-10-04; do not re-diagnose): run
  `export TMPDIR="$(getconf DARWIN_USER_TEMP_DIR)"` before every test or gate (the default TMPDIR
  cannot host SQLite); prefix every `just`/`uv` command with `env -u VIRTUAL_ENV`; in a fresh
  worktree run `env -u VIRTUAL_ENV just sync-dev` first and prove the import resolves inside the
  worktree (`env -u VIRTUAL_ENV uv run python -c 'import studyloop; print(studyloop.__file__)'`
  prints a path under your worktree, else stop and report). The one pre-existing default-suite
  failure is `test_fresh_install_scope.py::…virgin_home` (tmux shim); any other red is yours.
- **Never run `just e2e`, `just testacc`, `just testuat`, or start a study session.**

## 1. Settled (flag a violation, do not re-argue)

- K1 Every command a page shows was run by you first and is receipted (§3 below) and pinned by
  `test_contributor_guide_drift.py`. A command that fails is not documented.
- K2 `mkdocs.yml` is an allowlist; only A0/A1 edit it, `test_docs_drift.py`,
  `test_contributor_guide_drift.py` and `CHANGELOG.md`. Writers never do.
- K3 No file moves. The seed pages keep their paths; `docs/contributing.md` keeps every H2 in
  design.md §3 F10 as an anchor.
- K4 Nothing registry-shaped exists. Pages 19-20 say "proposal" / "design stage" in paragraph 1;
  **no fenced `studyloop module …` or `studyloop drill …` line anywhere** (the Click-tree drift test
  fails it) — proposed commands are prose, labelled proposed.
- K5 Facts come from design.md §3 (cite `F<n>` in the page's top HTML comment) or from a receipt
  you produced. Every commit sha on a page is one of F14 or has a `git log -1 --format='%h %s'`
  receipt. Two council seats fabricated history; that failure is why this rule exists.
- K6 AuDHD-friendly: one job per page, the answer or a numbered list before the first H2, ≥ 1
  numbered list, ≤ 150 lines (router ≤ 200), no "see elsewhere" loops — link the owning page once.
- K7 Branch/commit/PR grammar is design.md §4; your own commits follow it:
  `docs(contributing): <page stem> — <one line>`.

## 2. Commits — restart rule

This host restarted three times today and killed every running agent; uncommitted work was lost.
**One page = one commit** (page + its receipt lines together), through pre-commit (runs at commit
time; never `--no-verify`, never `SKIP=`). Never hold more than ~15 minutes of work uncommitted.
Stage exact paths. Before each commit: `env -u VIRTUAL_ENV just docs` (strict) green and
`env -u VIRTUAL_ENV uv run --group dev pytest packages/studyloop/tests/test_contributor_guide_drift.py -q -k <page-stem>`
green; `test_docs_drift.py` green at the end.

## 3. Receipts

`openspec/changes/contributor-guide-v1/evidence/<your id>/commands.txt`, appended per command,
exactly:

```
$ <command as the page shows it>
exit=<code>  sha=<git rev-parse --short HEAD>  utc=<YYYY-MM-DDTHH:MMZ>
<first five lines of output, or "(no output)">

```

A fenced command on your page with no receipt is a defect the assembler refuses.

## 4. Stop and report when

A §3 fact contradicts what you find in the tree; a page needs a command the repo lacks; a sibling's
page must change for yours to be true; `just docs` fails on a file you do not own; a merge
conflict. Report, do not improvise.

## 5. Final report (what the coordinator reads)

Verbatim: `git log --oneline <scaffold sha>..HEAD`; `git diff --stat <scaffold sha>..HEAD`; the
pytest summary line for the drift test on your pages and for `test_docs_drift.py`; the `just docs`
result line; receipt line count; the facts (`F<n>`) you cited per page; gaps and contradictions
found; `git status --short` run in the MAIN checkout (proving you wrote nothing there).
