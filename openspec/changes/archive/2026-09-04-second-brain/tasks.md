# Implementation Tasks

Three lanes, each on its own branch and worktree, each with a disjoint file set
enforced by `packages/studyloop/tests/fixtures/lane_ownership.yaml`. Lane **m7**
(core) and lane **m9** (process artefacts) ran in parallel; lane **m8** (xTiles
stage 1) started once both had merged into the integration branch.

Every item was red-first: a failing test on concrete data, then the code, then
`env -u VIRTUAL_ENV just preflight` as the per-item gate, with docs and the
changelog landing in the same commit as the behaviour they describe. Each item
names the evidence subdirectory that holds its `00-dod.md`, `01-red.txt`,
`02-green.txt`, `03-gate.txt` and `05-docs.diff`; the roots are
`reviews/2026-09-03-second-brain/evidence/m7/`, `…/m9/` and `…/m8/`.

Reconciled 2026-09-04 before archiving, per the review ruling
(`reviews/2026-09-04-second-brain-review/ARBITRATION.md` Q5): ticks record what
shipped in 0.2.0, strikes record what was cut, and the per-lane verifier items
are replaced by the review that actually happened.

## Lane m7 — core (`lane/m7-second-brain-core`)

- [x] **Foundation commit.** Repoint the lane-ownership guard's merge base to an
      ordered tuple of integration branches with an env override, map lanes
      m7/m8/m9, add the `live_obsidian` marker and deselect it by default in
      both `pyproject.toml` files, and add the vault-isolation fixture plus the
      session-finish hook that fails the run if the real vault changed.
      _Evidence: `00-foundation/`._
- [x] **Protocol, config and the null path.** `SecondBrain` protocol with its
      exact-method guard, `SecondBrainConfig`, `NullBackend`, the xTiles
      stage-1 object, `brain status` and `brain publish --plan`, and the
      optionality tests (`sys.modules`, directory-tree snapshot, CLI output).
      _Evidence: `T1/`._
- [x] **Heading constants.** Extract the plan-Markdown heading constants in
      `planning/markdown.py` so the projection renderer reads them instead of
      re-deriving the same strings a second time. _Evidence: `T3a/`._
- [x] **Obsidian backend.** Plan and Today projections, the atomic
      vault-boundary writer with the ownership marker and content hash,
      backlinks behind a lazy import with a warn-once fallback, and due-card
      extraction shared with the review service. ~~The opt-in CLI adapter with
      its probe and fallback~~ — built, reviewed and **withdrawn before
      release** (design D4); its four config keys (`use_cli`, `vault_name`,
      `template`, `daily_note`) are refused with an error naming them (D12).
      _Evidence: `T2/`._
- [x] **Templates as package data.** Ship the Obsidian templates under
      `studyloop/data/templates/obsidian/`, add the drift guard that keeps them
      in step with the renderer, assert they carry no ownership marker, and
      implement `brain template`. _Evidence: `T3/`._
- [x] **Full command group and integration points.** The rest of the `brain`
      group (`pull`, `enable`), the `config init` follow-up, the doctor check,
      the once-only wind-down offer, and the regenerated agent manifest.
      ~~`daily_note`~~ — cut with the adapter; never shipped. _Evidence: `T4/`._
- [x] **Obsidian half of the guide.** `docs/second-brain.md`, the touched pages,
      the mkdocs entry, and the docs-drift guards that make a stale sentence a
      red test. _Evidence: `T6a/`._
- [x] **Verification.** ~~Independent per-lane verifier in a clean worktree~~ —
      replaced by the P2 review council on the merged diff (SIGNOFF-P2): a
      four-family independent review of the shipped layer, arbitrated in
      `reviews/2026-09-04-second-brain-review/ARBITRATION.md`, with the static
      checks (no module-level provider import, no `Path.home()` in the package,
      vault untouched by the suite) carried by always-on tests instead of a
      one-off verifier.
- [x] **Sign-off and merge** into the integration branch; shipped as `v0.2.0`.

## Lane m9 — process artefacts (`lane/m9-second-brain-spec`)

- [x] **ADR-0010.** Record that second brains are projections and that the plan
      Markdown is the source of truth, with the rejected alternatives
      (two-way sync, an xTiles client now, writing into `AgentMemory/`, an
      environment-variable provider override, a web-UI button), and add the
      index row in `docs/adr/README.md`. Clause 1 amended 2026-09-04 to the
      rule the code obeys (`studyloop plan …` is the plan's only writer).
      _Evidence: `T7/`._
- [x] **Contract page.** `docs/architecture/second-brain.md`: the ten clauses
      with the check that proves each one, plus the `.gitignore` exception that
      makes the page trackable under the `docs/architecture/*` deny rule.
      _Evidence: `T7/`._
- [x] **OpenSpec change.** This directory: proposal, design with the D1–D13
      decision table and the alternatives, the new `second-brain` capability
      spec, and the deltas to `configuration-and-secrets` and `cli-surface`.
      _Evidence: `T7/`._
- [x] **Gates.** `just spec-check`, `just docs`, `just lint`, `just typecheck`,
      the lane-ownership guard on this branch, and the hygiene grep proving no
      absolute path, account name or commit hash reached a public file.
      _Evidence: `T7/`._
- [x] **Sign-off and merge** into the integration branch — via the P2 council
      on the merged diff (SIGNOFF-P2), not a per-lane verifier.

## Lane m8 — xTiles stage 1 (`lane/m8-xtiles-stage1`)

- [x] **The shared wind-down skill.** One skill body, self-gated on
      `provider: xtiles` plus a connected `xtiles` MCP server, installed into
      every detected harness by `studyloop install agents`, with the harness
      wrappers, the agent-instruction paragraphs and a regenerated manifest.
      _Evidence: `T5/`._
- [x] **xTiles half of the guide.** The provider section of
      `docs/second-brain.md`, the three prompts, and the sources rows.
      Reworded post-run per ARBITRATION Q2/N1–N4/N6 (planner tile not task;
      no board-view promise; skip the Review task when nothing is due).
      _Evidence: `T6b/`._
- [x] **Owner prompt run.** Run 2026-09-04 by the owner in Kiro CLI 2.21.0
      against a real xTiles Plus account — not Claude Code, and the docs say
      so. P1/P1b and P3 wrote what they describe; P2 created the project but
      not the board or the visible page structure it promised. Filled
      checklist and redacted transcript:
      `reviews/2026-09-03-second-brain/evidence/m8/xtiles-prompts/`.
- [x] **Verification.** ~~Preflight, docs-drift guards and hygiene grep rerun
      by an independent verifier~~ — replaced by the P2 council on the merged
      diff (SIGNOFF-P2).
- [x] **Sign-off**, integration gate, review council, and owner merge and tag
      (`v0.2.0`, 2026-09-04).
