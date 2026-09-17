## ADDED Requirements

### Requirement: update_study_plan revises the mission through the one gate
`update_study_plan` SHALL expose `why: str | None`, `success: list[str] | None`,
`constraints: list[str] | None` and `out_of_scope: list[str] | None` beside its
existing fields (item 3b, design §3b), forwarded unchanged onto the same one
`RevisePlan` — so the schema's property set is exactly `plan_id, title, topics,
target_date, energy_floor, review_cadence_days, notes, milestones, status,
why, success, constraints, out_of_scope`, and an omitted mission field SHALL
reach the seam as `None` ("leave as is"), never as `""` or `[]`. The seam SHALL
strip `why`, treat each list as a whole-list replacement stripped of blanks,
and refuse a bare string where a list belongs as `InvalidField` (`invalid: …`)
before any write. The resulting document is judged by the single readiness
gate exactly as for every other field: on an active plan a write that leaves
any blocker standing is `not_ready: …` and nothing is saved; a write that
clears every blocker in one call is saved once. With this, every blocker
`readiness()` can name — mission `why`, success criteria, milestones — is
repairable with the tool the architect already holds, so `plan repair` is a
repair rather than dictation.

#### Scenario: Mission fields reach the seam on one intent
- **WHEN** `update_study_plan("decorators", why="Own the nightly pipeline",
  success=["Deploy unaided"], constraints=["Evenings only"],
  out_of_scope=["Spark"])` is called
- **THEN** exactly one `RevisePlan` is applied carrying those four values and
  `None` for every other field, and the response is the seam's
  `PlanDetail.to_json_dict()`

#### Scenario: Omitted mission fields are None
- **WHEN** `update_study_plan("decorators", notes="Only this.")` is called
- **THEN** the applied intent's `why`, `success`, `constraints` and
  `out_of_scope` are all `None`

#### Scenario: Partial mission repair on a husk is refused; the whole repair lands once
- **WHEN** `update_study_plan("husk", why="…")` is called on an active plan with
  no mission, and then `update_study_plan("husk", why="…", success=["…"])`
- **THEN** the first is `not_ready: … No observable success criteria.` with the
  document unchanged, and the second saves once, leaves the plan `active`
  and `ready`, and `list_study_plans` no longer reports it as a husk
