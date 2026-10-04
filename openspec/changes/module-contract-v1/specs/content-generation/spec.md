## ADDED Requirements

### Requirement: PracticeDeck carries the module-contract identity and mentor-side fields
`studyloop.content.schemas.PracticeDeck` SHALL accept six additive fields and no others
(`extra: forbid` unchanged): `id` on the deck and on each task — a slug matching
`^[a-z0-9][a-z0-9-]{0,62}$`, optional so every deck written before the contract still
validates, and when present unique across the tasks of a deck; `solution`, `scaffolding`
(one of `guided`, `hinted`, `unaided`, `exam`) and `mentorNotes` on the task; and
`verification.cleanupCommand`. `timeoutSeconds` SHALL apply to each phase (setup, check,
cleanup) separately. The schema SHALL NOT couple `solution` to `scaffolding`; that is a
conformance rule (MC010), not a validation rule.

#### Scenario: the proposal's example deck validates
- **GIVEN** the §5.3 example deck from `openspec/changes/module-contract-v1/proposal.md`
- **WHEN** it is loaded through `studyloop.learning.practice.load_practice_deck`
- **THEN** it validates and every new field round-trips through `model_dump(by_alias=True)`

#### Scenario: a pre-contract deck still validates
- **GIVEN** a deck with only `title` and one task carrying `verification.kind: command`
- **WHEN** it is loaded
- **THEN** it validates with `id` absent on the deck and the task

#### Scenario: duplicate task ids are rejected and named
- **GIVEN** a deck whose two tasks both carry `id: pods-basics`
- **WHEN** it is loaded
- **THEN** validation fails and the error names `pods-basics` as the duplicate

#### Scenario: a malformed id is rejected
- **GIVEN** a task id of `Pods Basics`, `-x`, or 64 characters
- **WHEN** the deck is loaded
- **THEN** validation fails on the id pattern

#### Scenario: unknown fields are still forbidden
- **GIVEN** a task carrying a field the schema does not declare
- **WHEN** the deck is loaded
- **THEN** validation fails with "Extra inputs are not permitted"
