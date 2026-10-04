# Documentation

<!-- facts: F9 F11 F16 -->

A page is public only when four things are true: the file exists under `docs/`, `mkdocs.yml`
un-excludes it, the `nav:` lists it, and `just docs` builds strictly with it in place. Everything
else in the repository -- ADRs, plans, agent instructions, receipts -- stays source-only on
purpose, and every claim a public page makes is checked by a test.

## Make a page public

1. Write `docs/<page>.md`. Start with the answer (see the checklist below), not the history.
2. Add `!/<page>.md` to the `exclude_docs` block in `mkdocs.yml`. That block is an allowlist: its
   first line is `**`, so a new file is excluded until named. Keep the comment above it true.
3. Add the page to `nav:` under the group it belongs to. A page outside the nav builds but is
   unreachable; a nav entry without a page fails the strict build.
4. Build. `--strict` turns every warning -- a missing nav page, a broken relative link, an
   unreadable file -- into a failure:

```bash
just docs
```

5. Link the page once from the page that owns the reader's previous step. The
   [router](contributing.md) links each guide page from the step it belongs to; do not add a
   second route to the same page.

## Keep it true: the drift tests

Documentation here is tested like code, with no subprocess and no network in the default tier.
Three files do it, all under `packages/studyloop/tests/`:

- `test_docs_drift.py` -- every fenced line beginning `studyloop …` on a page listed in its
  `_STUDYLOOP_EXAMPLE_DOCS` tuple must resolve against the real Click command tree (a renamed
  option or subcommand fails the page that still shows it); `--since` examples must parse; YAML
  blocks on the configuration pages may use only known keys; and five tests pin single sentences
  against the source they describe.
- `test_contributor_guide_drift.py` -- the twenty guide pages: fenced `just` recipes exist, fenced
  `pytest` paths exist, backticked repository paths exist, links and anchors resolve, the page has
  one H1, an answer-first block, a numbered list and no more than 150 lines, and any sentence
  about harness tiers, test markers, branch prefixes or commit types matches the source.
- `test_contributor_docs.py` -- the guide pages are allowlisted and in the nav, the cookbook links
  real collected examples, and the module guide keeps its proposal/execution boundary.

Run them together whenever you touch `docs/` or `mkdocs.yml`:

```bash
uv run --group dev pytest packages/studyloop/tests/test_docs_drift.py packages/studyloop/tests/test_contributor_docs.py -q
```

To pin a **new command example**: put it in a fenced block on a page that is in
`_STUDYLOOP_EXAMPLE_DOCS` (every guide page already is), and the Click-tree test picks it up with
no test code. To pin a **new sentence** (a tier, a count, a default): add one test beside the five
pinned-claim tests in `test_docs_drift.py` that reads the sentence and the source symbol and
compares them -- parse the sentence, never copy it into the test. A documented command you have
not run is a defect, not a draft.

## What stays out of the site, and why

`exclude_docs` starts with `**` so that `docs/adr/`, `docs/architecture/`, `openspec/`, `agents/`
and every audit, plan, receipt and handoff stay in the repository but off the public site. They
are written for the people changing the code, change without a learner-facing review, and often
describe intent rather than behaviour. A public page describes what the installed program does
today; if a statement belongs to a decision record, write the ADR and have the page link to the
behaviour instead. A public page that links an excluded file still builds: mkdocs only reports it
at `INFO` level and the link is dead on the site, so read the build log, not just its exit code.

## The house style: AuDHD writing rules

Every page in this guide is held to this checklist, by the drift test where a rule is mechanical
and by review where it is not. Check each item before you open the pull request:

1. **One job per page.** The title names it; a second job is a second page, linked once.
2. **Answer first.** The first block after the title is a paragraph of at most three sentences
   or a numbered list, and it tells the reader what to do or what is true. Context comes after.
3. **Numbered steps for anything done in order.** Bullets only for sets with no order.
4. **At most 150 lines.** If the page is longer, it has two jobs; split it.
5. **No "see elsewhere" loops.** Link the owning page once, at the point the reader needs it,
   and never send them to a page that sends them back.
6. **Define a term where it is used.** The first use of *adapter*, *tier*, *allowlist* or any
   repository word carries its one-line meaning; do not make the reader hold it from another page.
7. **One idea per paragraph, one command per fenced block**, with the expected result stated in
   the sentence before or after it.
8. **Say what is true now.** Proposed or future things are prose labelled *proposed*; never a
   fenced command that does not run today.
9. **Name the file.** A claim about the code names the path in backticks so the reader -- and the
   drift test -- can check it; a claim nobody can check is cut.
10. **Say what you ran.** Every command on the page was run by its author and its first lines of
    output were kept as evidence; a reader following the page gets the same result.
