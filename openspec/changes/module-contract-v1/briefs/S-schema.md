# Lane S — schema + ownership guard

Read `00-common.md` first. Then `proposal.md` §5.3 (the six fields and the example deck), §6
(MC014 — ids slug-valid and unique), and `design.md` §2–§4.

| | |
| --- | --- |
| Branch | `feat/module-schema` |
| Worktree | `/Users/ataylor/code/personal/tools/studyloop-wt/module-schema` |
| Base | `git rev-parse HEAD` at start — record it as `Base: <sha>` in your first commit body |
| Merge position | **first and alone**, before any other lane; your merge unblocks Bruno's conversion |
| DoD items | 1 (schema), 6 (docs — S3, **not in this wave**: the docs lease is held) |
| Wave-0 scope | S1, S2 only. Stop after S2 and report. S3 is scheduled by the coordinator. |

## Owned globs (repo-relative)

- `packages/studyloop/src/studyloop/content/schemas.py`
- `packages/studyloop/tests/test_module_schema.py` (new)
- `packages/studyloop/tests/_lane_ownership.py`
- `packages/studyloop/tests/test_lane_ownership.py`
- `packages/studyloop/tests/fixtures/lane_ownership.yaml` (exists — extend it)
- `openspec/changes/module-contract-v1/evidence/S/**`
- Later, S3 only (not now): `docs/module-contract.md`, `.github/PULL_REQUEST_TEMPLATE/module.md`,
  `mkdocs.yml` nav entry, `CHANGELOG.md`, `packages/studyloop/tests/test_docs_drift.py`.

## Forbidden

Everything under `src/studyloop/modules/`, `cli/`, `web/`, `session/`, `learning/`, `doctor/`;
any `docs/` file in this wave; any file of the other session (see common §0).

## S1 — re-key the lane-ownership guard (one commit, gate G)

Today `tests/_lane_ownership.py` maps a branch to a lane with `_LANE_BRANCH_RE =
re.compile(r"^lane/m(\d+)-")` and `fixtures/lane_ownership.yaml` maps lanes to globs. Add an
explicit branch→lane map to the YAML (`feat/module-schema`→`S`, `feat/module-conformance`→`C`,
`feat/module-runner`→`R`, `feat/module-mentor-delivery`→`T`, `feat/module-web-labs`→`W`) with
each lane's owned globs **exactly as `design.md` §2 lists them** (fnmatch, repo-relative), and
teach `lane_id_from_branch` to consult the map before the legacy regex. Keep, unchanged in
behaviour: the legacy `lane/m<n>-` entries, the "malformed `lane/` name is an error not a skip"
rule, fnmatch, `shared`, and "unmapped branch is logged, not failed". Read
`test_lane_ownership.py` first: every existing test must still pass untouched; add tests for
the five new branches, for a `feat/` branch not in the map (unmapped → logged), and for a
mapped lane editing another lane's file (fails). Verification: `env -u VIRTUAL_ENV uv run
pytest packages/studyloop/tests/test_lane_ownership.py -q` all green; then gate G.

## S2 — the six §5.3 fields (one commit, gate G, red kept)

Add to `content/schemas.py`, keeping `extra: forbid` and `populate_by_name` exactly as they are:

- `PracticeDeck.id` and `PracticeTask.id`: slug (`^[a-z0-9][a-z0-9-]{0,62}$`), **optional**
  (`str | None = None`) so every existing deck still validates; when present, task ids are
  unique within the deck (validate at deck level; the error names the duplicate).
- `PracticeTask.solution: str = ""`, `PracticeTask.mentor_notes: str = Field("", alias="mentorNotes")`,
  `PracticeTask.scaffolding: Literal["guided","hinted","unaided","exam"] | None = None`.
- `PracticeVerification.cleanup_command: str = Field("", alias="cleanupCommand")`.
- Follow the proposal's exact JSON names; check `proposal.md` §5.3 for any constraint I have
  omitted (e.g. whether `solution` requires `scaffolding` — if the proposal says so, that is
  MC010's job in the conformance lane, **not** the schema's; the schema stays permissive
  except for the id rules).

**Red first:** write `tests/test_module_schema.py` *before* touching `schemas.py`; its first
test loads the proposal's §5.3 example deck (copy it into the test as a literal) through
`studyloop.learning.practice.load_practice_deck`. Run it; it must fail with
`Extra inputs are not permitted` naming the new fields. Save that transcript as
`evidence/S/example-deck-extra-forbidden.red.txt`. Then implement, then the remaining tests:
each field round-trips through `model_dump(by_alias=True)`; missing `id` is accepted;
duplicate task ids rejected; malformed id (`"Pods Basics"`, `"-x"`, 64+ chars) rejected; a
pre-existing deck shape (title + one task with `verification.kind: command`) still validates.
Verification: the new file green, the whole default suite green, gate G.

## Report (in addition to common §6)

- The exact `lane_ownership.yaml` diff, so the coordinator can check it against `design.md` §2.
- Confirmation that no `docs/` path was touched (S3 waits for the lease).
