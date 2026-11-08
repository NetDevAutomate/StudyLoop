# Brief W-D — prove it, and the proposals (six pages, two light)

Read `00-common.md`, then `design.md` §2 (your rows **and the 12-bullet module-index outline**),
§3 (F7, F8, F11 especially), §6 (pattern M binds pages 19-20), and the Terraform pages you mirror
(fetch: Unit Tests, Acceptance Tests, Submit an Issue, How We Prioritize, AI Usage) for *shape*.
Also read `openspec/changes/module-contract-v1/proposal.md` §1, §5, §9 and
`docs/contributor-modules.md` as it stands.

| | |
| --- | --- |
| Branch | `feat/contributor-guide-d` from the scaffold sha given in your dispatch |
| Worktree | `/Users/ataylor/code/personal/tools/studyloop-wt/contributor-guide-d` |
| Owns | `docs/contributor-testing.md` (extend), `docs/acceptance-testing.md` (cross-links only), `docs/contributor-issues-prioritisation.md`, `docs/contributor-ai.md`, `docs/contributor-modules.md` (extend), `docs/contributor-module-index.md`, `evidence/W-D/` |
| Forbidden | every other `docs/` file, `mkdocs.yml`, `CHANGELOG.md`, any test or `src/` file |

## Pages

1. **`contributor-testing.md`** (extend, keep its H2s and the collected examples
   `test_contributor_docs.py::test_cookbook_links_to_real_collected_examples` pins — read that test
   first) — open with a numbered "choose the tier" decision (default / integration / e2e /
   acceptance / UAT: F7, F8, who runs each and where, nightly integration in CI, acceptance never),
   then the existing patterns. Say `just e2e` is maintainer-run, one per machine.
2. **`acceptance-testing.md`** — add only a two-line intro link to the cookbook and the PR page; no
   other change (it already meets K6 and has its own tests).
3. **`contributor-issues-prioritisation.md`** — what to attach to a bug (`uv run studyloop doctor`
   output, redacted — run it and show how to redact), what a feature proposal must say (link the
   harness rule in `contributing.md#making-changes`), lifecycle, then the maintainers' priority order
   (read `docs/contributing.md:300-309` and keep its substance).
4. **`contributor-ai.md`** — disclose AI assistance under PR question 2, own the result (tests,
   receipts), the LiteLLM-gateway option as `docs/contributing.md:310-344` describes it (verify every
   command there before repeating it; replace any you cannot run).
5. **`contributor-modules.md`** (extend) — keep it a proposal page: first paragraph says
   "proposal", links `openspec/changes/module-contract-v1/proposal.md`; align its vocabulary with the
   council-amended proposal (modules declare / core executes; one `PracticeDeck` format; the Labs
   entry; browser checks v1.1; view-only credential v2) and link page 20. **No fenced proposed
   commands.** `test_contributor_docs.py::test_module_guide_preserves_proposal_and_execution_boundaries`
   must stay green — read it first.
6. **`contributor-module-index.md`** — the 12 bullets of design.md §2 in that order, "design stage"
   in paragraph 1, the §9 link, the must-not-promise list honoured, ≤ 100 lines. Pattern M fails
   any fenced `studyloop module`/`studyloop drill` line and the phrases `is available`, `install it`,
   `the index lists`.

## Report

Common §5 plus: confirmation that both `test_contributor_docs.py` tests above are green, and the
exact first paragraph of page 20.
