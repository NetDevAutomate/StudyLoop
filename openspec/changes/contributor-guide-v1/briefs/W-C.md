# Brief W-C — make a change, part B, and the developer reference (five pages)

Read `00-common.md`, then `design.md` §2 (your rows), §3 (F2, F4, F5, F9, F11, F12 especially),
§4.1 (scopes — `contributor-conventions.md` owns code-level naming), §6, and the Terraform pages
you mirror (fetch: Add a New AWS Service, Documentation Changes, Naming Standards, and the
Developer Reference index) for *shape* only.

| | |
| --- | --- |
| Branch | `feat/contributor-guide-c` from the scaffold sha given in your dispatch |
| Worktree | `/Users/ataylor/code/personal/tools/studyloop-wt/contributor-guide-c` |
| Owns | `docs/contributor-harnesses-agents.md`, `docs/contributor-content.md`, `docs/contributor-documentation.md`, `docs/contributor-code-map.md` (extend), `docs/contributor-conventions.md`, `evidence/W-C/` |
| Forbidden | every other `docs/` file, `mkdocs.yml`, `CHANGELOG.md`, any test or `src/` file |

## Pages

1. **`contributor-harnesses-agents.md`** — the six harnesses with the tiers from F4 (4 core, 2
   preview), what an adapter is (`adapters/*.py`, `registry.py`), what an agent definition is
   (`agents/<harness>/` for five of them; F5: Grok reuses Codex and `agents/grok/` must not exist —
   cite the parity test), `agents/shared/` protocols and the four recording writers named in
   `docs/contributing.md:170-175`, how to change a prompt safely (parity tests), and **why
   additions are declined** (F2) with the seven things a proposal must define.
2. **`contributor-content.md`** — `content/schemas.py` (Pydantic, `extra: forbid`, aliases), the
   generation pipeline and providers under `content/`, where decks are read and written (read the
   `content-generation` spec in `openspec/specs/` for the read/write-root rule), `just test-content`.
3. **`contributor-documentation.md`** — how a page becomes public (F9 allowlist + nav, strict
   build), the drift tests (F11) and how to add a pinned example, what stays out of the site (ADRs,
   plans, agent instructions) and why, **and the AuDHD writing rules as a numbered checklist**
   (one job, answer first, numbered steps, ≤ 150 lines, no "see elsewhere" loops, define a term where
   it is used) — this section is the house style every other page is held to.
4. **`contributor-code-map.md`** (extend, keep its H2s) — tighten to: which layer owns what, the
   request flow for one CLI command and one web route, and a table "a change of kind X lands in
   Y" pointing at the eight Make-a-change / Testing pages by §2 path. Keep F12.
5. **`contributor-conventions.md`** — code-level naming (modules, test files `test_<area>_*.py`,
   fixtures, the scope vocabulary in §4.1 as it maps to directories), OpenSpec changes
   (`openspec/changes/<id>/` with proposal/design/tasks/specs; `just spec-check`; a docs-only change
   declares `skip_specs: true` in `.openspec.yaml` — cite `openspec/changes/contributor-guide-v1/.openspec.yaml`),
   ADRs (`docs/adr/`, the index table in `docs/adr/README.md`, excluded from the site).

## Report

Common §5 plus: the exact harness/tier sentence you used (the assembler's F check reads it).
