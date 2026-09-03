# Implementation Tasks

Three lanes, each on its own branch and worktree, each with a disjoint file set
enforced by `packages/studyloop/tests/fixtures/lane_ownership.yaml`. Lane **m7**
(core) and lane **m9** (process artefacts) run in parallel; lane **m8** (xTiles
stage 1) starts once both have merged into the integration branch.

Every item is red-first: a failing test on concrete data, then the code, then
`env -u VIRTUAL_ENV just preflight` as the per-item gate, with docs and the
changelog landing in the same commit as the behaviour they describe. Each item
names the evidence subdirectory that holds its `00-dod.md`, `01-red.txt`,
`02-green.txt`, `03-gate.txt` and `05-docs.diff`; the roots are
`reviews/2026-09-03-second-brain/evidence/m7/`, `…/m9/` and `…/m8/`.

## Lane m7 — core (`lane/m7-second-brain-core`)

- [ ] **Foundation commit.** Repoint the lane-ownership guard's merge base to an
      ordered tuple of integration branches with an env override, map lanes
      m7/m8/m9, add the `live_obsidian` marker and deselect it by default in
      both `pyproject.toml` files, and add the vault-isolation fixture plus the
      session-finish hook that fails the run if the real vault changed.
      _Evidence: `00-foundation/`._
- [ ] **Protocol, config and the null path.** `SecondBrain` protocol with its
      exact-method guard, `SecondBrainConfig`, `NullBackend`, the xTiles
      stage-1 object, `brain status` and `brain publish --plan`, and the
      optionality tests (`sys.modules`, directory-tree snapshot, CLI output).
      _Evidence: `T1/`._
- [ ] **Heading constants.** Extract the plan-Markdown heading constants in
      `planning/markdown.py` so the projection renderer reads them instead of
      re-deriving the same strings a second time. _Evidence: `T3a/`._
- [ ] **Obsidian backend.** Plan and Today projections, the atomic
      vault-boundary writer with the ownership marker and content hash,
      backlinks behind a lazy import with a warn-once fallback, the opt-in CLI
      adapter with its probe and fallback, and due-card extraction shared with
      the review service. _Evidence: `T2/`._
- [ ] **Templates as package data.** Ship the Obsidian templates under
      `studyloop/data/templates/obsidian/`, add the drift guard that keeps them
      in step with the renderer, assert they carry no ownership marker, and
      implement `brain template`. _Evidence: `T3/`._
- [ ] **Full command group and integration points.** The rest of the `brain`
      group (`pull`, `enable`), the `config init` follow-up, the doctor check,
      the once-only wind-down offer, and the regenerated agent manifest.
      _Evidence: `T4/`._
- [ ] **Obsidian half of the guide.** `docs/second-brain.md`, the touched pages,
      the mkdocs entry, and the docs-drift guards that make a stale sentence a
      red test. _Evidence: `T6a/`._
- [ ] **Lane verification.** Independent verifier in a clean worktree: every
      gate rerun plus the lane-specific static checks (no module-level provider
      import, no `Path.home()` in the package, no MCP import, no publish call
      site outside the CLI, real vault and config directory byte-identical
      before and after the suite). _Evidence: `SIGNOFF-M7/`._
- [ ] **Sign-off and merge** into the integration branch.

## Lane m9 — process artefacts (`lane/m9-second-brain-spec`)

- [ ] **ADR-0010.** Record that second brains are projections and that the plan
      Markdown is the source of truth, with the rejected alternatives
      (two-way sync, an xTiles client now, writing into `AgentMemory/`, an
      environment-variable provider override, a web-UI button), and add the
      index row in `docs/adr/README.md`. _Evidence: `T7/`._
- [ ] **Contract page.** `docs/architecture/second-brain.md`: the ten clauses
      with the check that proves each one, plus the `.gitignore` exception that
      makes the page trackable under the `docs/architecture/*` deny rule.
      _Evidence: `T7/`._
- [ ] **OpenSpec change.** This directory: proposal, design with the D1–D13
      decision table and the alternatives, the new `second-brain` capability
      spec, and the deltas to `configuration-and-secrets` and `cli-surface`.
      _Evidence: `T7/`._
- [ ] **Gates.** `just spec-check`, `just docs`, `just lint`, `just typecheck`,
      the lane-ownership guard on this branch, and the hygiene grep proving no
      absolute path, account name or commit hash reached a public file.
      _Evidence: `T7/`._
- [ ] **Sign-off and merge** into the integration branch.

## Lane m8 — xTiles stage 1 (`lane/m8-xtiles-stage1`)

- [ ] **The shared wind-down skill.** One skill body, self-gated on
      `provider: xtiles` plus a connected `xtiles` MCP server, installed into
      every detected harness by `studyloop install agents` (two installer rows),
      with the harness wrappers, the agent-instruction paragraphs and a
      regenerated manifest. _Evidence: `T5/`._
- [ ] **xTiles half of the guide.** The provider section of
      `docs/second-brain.md`, the three prompts, and the sources rows.
      _Evidence: `T6b/`._
- [ ] **Owner prompt run.** The owner runs the three prompts end to end against
      a real xTiles board and records what came back, because stage 1 is a
      prompt contract and only a human can judge whether it reads well.
      _Evidence: `T5/`._
- [ ] **Lane verification.** Preflight, the docs-drift guards and the hygiene
      grep, rerun by an independent verifier. _Evidence: `SIGNOFF-M8/`._
- [ ] **Sign-off**, integration gate, review council, and owner merge and tag.
