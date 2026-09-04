## ADDED Requirements

### Requirement: The brain group is lazily registered and every command has --json
`studyloop.cli.__init__` SHALL register `"brain": "studyloop.cli._brain:brain_group"`
in `lazy_subcommands`; `brain status`, `publish`, `pull`, `enable` and
`template` SHALL each accept `--json`; `studyloop.cli._brain` SHALL import
`studyloop.second_brain` only inside command bodies.

#### Scenario: Help without a backend import
- **WHEN** `studyloop brain --help` runs
- **THEN** it exits 0 and `studyloop.second_brain.obsidian` is not imported
