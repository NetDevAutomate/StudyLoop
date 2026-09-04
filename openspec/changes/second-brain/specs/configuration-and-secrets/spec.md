## ADDED Requirements

### Requirement: The second_brain section is parsed into SecondBrainConfig with one-line errors
`studyloop.settings.load_settings()` SHALL parse an optional top-level
`second_brain` mapping into `SecondBrainConfig(provider, vault_path, folder,
backlinks)`, defaulting `provider` to `none`; a provider outside
`none|obsidian|xtiles`, a non-boolean `backlinks`, or a folder that is absolute or
contains `..` SHALL raise `ConfigError` with a one-line message; any of the retired
keys `use_cli`, `vault_name`, `template` or `daily_note` SHALL also raise, naming
the key; and `second_brain` SHALL count as a known key for the unknown-key report.

#### Scenario: Misspelled provider
- **WHEN** `config.yaml` contains `second_brain: {provider: obsidan}`
- **THEN** `studyloop brain status` prints one `ConfigError` line naming the
  allowed values and exits 1 without a traceback
