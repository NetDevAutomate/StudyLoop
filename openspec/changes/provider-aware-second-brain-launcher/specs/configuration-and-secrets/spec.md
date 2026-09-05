## ADDED Requirements

### Requirement: `mutate_raw_config()` serializes and atomically replaces validated configuration
`studyloop.settings.mutate_raw_config()` SHALL acquire one process-visible lock
before rereading the active YAML file, apply one mutation to that current mapping,
validate the resulting configuration, and atomically replace the destination with
a sibling temporary file. It SHALL preserve unrelated keys and existing file mode,
use mode `0600` for a new file, flush file data before replacement, and remove the
temporary file after every failure. `write_raw_config()` and every Second Brain
configuration command SHALL use this single mutation owner.

#### Scenario: Two serialized writers update different keys
- **GIVEN** two configuration mutations target different keys
- **WHEN** both writers contend for the same active configuration file
- **THEN** the second writer rereads after acquiring the lock
- **AND** the final file contains both changes and all unrelated keys

#### Scenario: Atomic replacement fails
- **GIVEN** an existing configuration file with mode `0600`
- **WHEN** replacement fails after the sibling temporary file is written
- **THEN** the destination remains byte-identical with mode `0600`
- **AND** no temporary file remains

#### Scenario: Mutated configuration is invalid
- **GIVEN** a mutator produces an invalid configuration mapping
- **WHEN** `mutate_raw_config()` validates it
- **THEN** the mutation fails before replacement
- **AND** the existing destination remains unchanged

#### Scenario: Successful writes preserve restrictive permissions
- **GIVEN** one existing configuration file has a restrictive mode and another destination does not exist
- **WHEN** each destination is successfully mutated
- **THEN** the existing file retains its prior mode
- **AND** the newly created file has mode `0600`

## MODIFIED Requirements

### Requirement: The second_brain section is parsed into SecondBrainConfig with one-line errors
`studyloop.settings.load_settings()` SHALL parse an optional top-level
`second_brain` mapping into `SecondBrainConfig(provider, vault_path, folder,
backlinks, xtiles_destination_url)`, defaulting `provider` to `none` and the
destination to absent. A provider outside `none|obsidian|xtiles`, a non-boolean
`backlinks`, or a folder that is absolute or contains `..` SHALL raise
`ConfigError` with a one-line message. Any retired key `use_cli`, `vault_name`,
`template`, or `daily_note` SHALL also raise and name the key.
`xtiles_destination_url`, when present, SHALL be at most 2,048 characters and
SHALL be an HTTPS URL on exactly `xtiles.app` or `app.xtiles.app`, with no
userinfo, non-default port, query, fragment, Unicode or IDNA-lookalike hostname,
and with a non-home path. Validation errors and logs SHALL NOT include the
complete URL. The destination value SHALL NOT change provider selection, and
`second_brain` SHALL remain a known key for the unknown-key report.

#### Scenario: Misspelled provider
- **GIVEN** `config.yaml` contains `second_brain: {provider: obsidan}`
- **WHEN** `studyloop brain status` loads configuration
- **THEN** it prints one `ConfigError` line naming the allowed values
- **AND** it exits 1 without a traceback

#### Scenario: Valid destination is retained without selecting xTiles
- **GIVEN** `second_brain.provider` is `none`
- **AND** `xtiles_destination_url` is `https://xtiles.app/project/abc`
- **WHEN** settings are loaded
- **THEN** the destination is available on `SecondBrainConfig`
- **AND** the provider remains `none`

#### Scenario: Unsafe destination is rejected without disclosure
- **GIVEN** an xTiles destination uses HTTP, credentials, a non-default port, an unreviewed host, a home path, query, fragment, Unicode hostname, or more than 2,048 characters
- **WHEN** settings are loaded or the destination command validates the value
- **THEN** a one-line `ConfigError` is raised before any write
- **AND** the complete URL is absent from the error and logs
