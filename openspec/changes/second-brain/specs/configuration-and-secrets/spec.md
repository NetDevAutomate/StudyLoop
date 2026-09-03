## ADDED Requirements

### Requirement: The second_brain section is parsed into SecondBrainConfig with one-line errors
`studyloop.settings.load_settings()` SHALL parse an optional top-level
`second_brain` mapping into `SecondBrainConfig(provider, vault_path, folder,
backlinks, use_cli, vault_name, template, daily_note)`, defaulting `provider`
to `none` and `use_cli` to `auto`; a provider outside `none|obsidian|xtiles`,
a `use_cli` outside `auto|on|off` (YAML booleans map to `on`/`off`), a
non-boolean flag, or a folder that is absolute or contains `..` SHALL raise
`ConfigError` with a one-line message; the key SHALL count as known for the
unknown-key report.

#### Scenario: Misspelled provider
- **WHEN** `config.yaml` contains `second_brain: {provider: obsidan}`
- **THEN** `studyloop brain status` prints one `ConfigError` line naming the
  allowed values and exits 1 without a traceback
