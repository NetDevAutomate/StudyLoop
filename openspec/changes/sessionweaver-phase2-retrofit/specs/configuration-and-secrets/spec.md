## ADDED Requirements

### Requirement: A freshly generated studyloop config classifies memory scope explicitly
`studyloop.settings.generate_default_config()` SHALL include a `memory:`
block setting `default_scope: unclassified`, with the same work/personal
guidance comment convention this file already uses for other optional
sections. The runtime default read from an existing file that omits the
key SHALL remain unset, unaffected by this requirement.

#### Scenario: Fresh studyloop install generates a classified default
- **WHEN** `studyloop setup` (or any path that calls
  `generate_default_config()`) writes a new `config.yaml`
- **THEN** the written file contains `memory.default_scope: unclassified`

#### Scenario: An existing file omitting the key is unaffected
- **GIVEN** an existing `config.yaml` with no `memory` section
- **WHEN** settings are loaded
- **THEN** the runtime default scope resolves to unset, exactly as before
  this requirement, and no file is rewritten as a side effect of reading it

### Requirement: A freshly generated agent-session-tools config classifies memory scope explicitly
`agent_session_tools.config_loader.ensure_config_dir()` SHALL write
`DEFAULT_CONFIG` with `memory.default_scope` set to `"unclassified"` when
it creates a new `config.yaml`. `DEFAULT_CONFIG`'s in-memory fallback used
for a key missing from an existing file SHALL remain unaffected by this
requirement.

#### Scenario: ensure_config_dir creates a fresh config file
- **GIVEN** no `config.yaml` exists at the resolved config path
- **WHEN** `ensure_config_dir()` runs
- **THEN** the created file contains `memory: {default_scope:
  unclassified, projects: {}}`

#### Scenario: An existing file without the key is not rewritten
- **GIVEN** an existing `config.yaml` with no `memory` section
- **WHEN** `load_config()` reads it
- **THEN** the resolved `default_scope` is `None`, matching the documented
  runtime default, and `ensure_config_dir()` does not rewrite the existing
  file
