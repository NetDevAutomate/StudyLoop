## ADDED Requirements

### Requirement: doctor names each active-but-unready study plan
`check_study_plans()` (`cli/_doctor.py`, beside `check_unknown_config_keys`)
SHALL be registered under the existing `config` category — the category set
is enumerated verbatim elsewhere in this spec and gains none here — and SHALL
report on the plans `PlanApplication.husks()` returns: active plans that are
not ready and therefore refuse every write (item 3 / D-C; deviation 12 kept).
It SHALL emit one `warn` row per husk with `name="study_plans"`,
`fix_auto=False` (the repair is a conversation with the architect, not a
script), a message naming the plan id, its title, the exact
`ReadinessView.blockers`, and the shared provenance sentence
(`husk_provenance`: `predates the readiness gate` only for a `created` before
`READINESS_GATE_DATE`, else `cannot tell how it got that way`, never `hand
edit`), and a `fix_hint` naming both exits: `studyloop plan repair <id>  (or:
studyloop plan status <id> paused)`. When every active plan is ready it SHALL
emit one `pass` row counting the active plans; when no plan is active it SHALL
emit one `info` row, not a warning. A draft is unready by nature and is never
reported. A plans directory that cannot be read SHALL be one `warn` row, not
a crash of doctor.

#### Scenario: Two husks, one ready active plan, one draft
- **WHEN** `check_study_plans()` runs over a ready active plan, a draft with
  no mission, a husk created before the gate date and a husk created after it
- **THEN** exactly two `warn` rows are returned, both `config` /
  `study_plans` / `fix_auto=False`; each names its plan id and title and
  both mission blockers; the older one says `predates the readiness gate`
  and the newer says `cannot tell how it got that way` and not `hand edit`;
  each `fix_hint` names `studyloop plan repair <id>` and `studyloop plan
  status <id> paused`; neither the ready plan nor the draft is named

#### Scenario: All active plans ready is one pass row; no plans is info
- **WHEN** `check_study_plans()` runs with one ready active plan, and again
  with no plans at all
- **THEN** the first returns one `pass` row saying `1 active plan` and
  `ready`; the second returns one `info` row

#### Scenario: The checker is registered
- **WHEN** `_get_registry()` is built
- **THEN** `("config", "check_study_plans")` is among its registered checkers
