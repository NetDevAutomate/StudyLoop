## Purpose

Discover, load, validate, and persist user configuration from a single
YAML file (`~/.config/studyloop/config.yaml`); store and resolve provider
API keys through an encrypted local secrets store with environment-variable
fallback; and expose both surfaces via CLI commands (`studyloop setup`,
`studyloop config show`, `studyloop topics`).

## Requirements

### Requirement: Configuration is discovered from a single path with env override
The system SHALL resolve the active config path via `get_config_path()`
(`settings.py`): if `STUDYLOOP_CONFIG` is set in the environment, that
path is used; otherwise `~/.config/studyloop/config.yaml` is the default.
`load_raw_config()` returns an empty dict when the file does not exist
rather than raising.

#### Scenario: STUDYLOOP_CONFIG points to a custom location
- **WHEN** the environment variable `STUDYLOOP_CONFIG` is set to
  `/tmp/test-config.yaml`
- **THEN** `get_config_path()` returns `/tmp/test-config.yaml`
- **AND** `load_raw_config()` reads from that path

#### Scenario: No config file exists yet
- **WHEN** the resolved config path does not exist on disk
- **THEN** `load_raw_config()` returns `{}` and `load_settings()` returns
  a `Settings` instance populated entirely from dataclass defaults

### Requirement: Dotted top-level keys are expanded to nested mappings before consumers read them
`load_raw_config()` SHALL call `_expand_dotted_keys()` (`settings.py`)
to normalise flat YAML keys like `tts.backend: openvox` into nested
mappings (`tts: {backend: openvox}`). On conflict between a dotted key
and an explicit nested mapping at the same path, the nested mapping
SHALL win — the dotted key is dropped rather than overwriting it.

#### Scenario: User config uses flat dotted form for tts.backend
- **WHEN** `config.yaml` contains a top-level key `tts.backend: openvox`
  and no nested `tts:` mapping
- **THEN** `load_raw_config()` returns `{"tts": {"backend": "openvox"}}`

#### Scenario: Both dotted and nested forms conflict
- **WHEN** `config.yaml` contains both `tts: {backend: kokoro}` and a
  top-level `tts.backend: openvox`
- **THEN** the nested value `kokoro` wins; the dotted key is discarded

### Requirement: Scalar config values are coerced to lists where the schema expects a list
`load_settings()` and `resolve_study_dirs()` (`settings.py`) SHALL
coerce a bare-string value to a single-element list for
`content.study_paths` and `review.directories`, preventing per-character
iteration over a path string. The `topics` key likewise accepts a bare
string entry (e.g. `topics: [Python]`) and parses it via
`_topic_from_raw()` into a `TopicConfig` with a generated slug.

#### Scenario: study_paths is a single string in config.yaml
- **WHEN** `content.study_paths` is set to `"~/Obsidian/Personal/Study"`
  (a scalar, not a YAML list)
- **THEN** `load_settings().content.study_paths` is a one-element list
  containing that expanded path, not a list of individual characters

#### Scenario: topics entry is a bare string
- **WHEN** the `topics` list contains a bare string `"Python"` instead of
  a mapping with `name:`
- **THEN** `_topic_from_raw()` returns a `TopicConfig` with
  `name="Python"`, `slug="python"`, and a default `obsidian_path`

### Requirement: Topics are capped at MAX_ACTIVE_TOPICS entries
`load_settings()` SHALL load at most `MAX_ACTIVE_TOPICS` (3) topic
entries from the `topics` list in `config.yaml`, silently ignoring any
entries beyond that limit. The constant is defined at module level in
`settings.py`.

#### Scenario: Config lists five topics
- **WHEN** `config.yaml` contains five entries under `topics:`
- **THEN** `load_settings().topics` contains only the first three

### Requirement: Secrets are stored in a Fernet-encrypted local file with env-var fallback
`secrets.py` SHALL persist provider API keys in
`~/.config/studyloop/secrets.bin` as a Fernet token (AES-128-CBC +
HMAC-SHA256) over a JSON payload. The 32-byte random seed lives at
`~/.config/studyloop/.secrets-key` (mode 0600) and is derived through
HKDF-SHA256 into the Fernet key. Resolution order in `get_secret()`:
encrypted store first, then the mapped OS environment variable (e.g.
`OPENAI_API_KEY` for provider `"openai"`), then `None`.

#### Scenario: Key exists in encrypted store
- **WHEN** `set_secret("openai", "sk-abc...")` was previously called
- **AND** `OPENAI_API_KEY` is also set in the environment
- **THEN** `get_secret("openai")` returns the encrypted-store value, not
  the environment variable

#### Scenario: Encrypted store is empty but env var is set
- **WHEN** no `"openai"` entry exists in `secrets.bin`
- **AND** the environment variable `OPENAI_API_KEY` is set to `"sk-env"`
- **THEN** `get_secret("openai")` returns `"sk-env"`

#### Scenario: Corrupt secrets store does not block the application
- **WHEN** `secrets.bin` is unreadable or fails decryption
- **THEN** `get_secret()` logs a warning and falls through to the
  environment variable rather than raising an exception

### Requirement: Provider credentials are verified before persistence via test_provider_auth
`test_provider_auth()` (`secrets.py`) SHALL verify a credential before
the caller stores it: for API-key providers (`openai`, `anthropic`,
`openrouter`, `gemini`) it performs a cheap HTTP `GET /v1/models` (or
equivalent); for `bedrock` it delegates to
`provider_auth.test_bedrock_bearer()` which issues a minimal
`converse(maxTokens=1)` call; for `ollama` it delegates to
`provider_auth.test_ollama_generate()` which runs a real generation and
validates schema output. A `(bool, str)` tuple is returned.

#### Scenario: Valid OpenAI key tested
- **WHEN** `test_provider_auth("openai", "sk-valid...")` is called
- **THEN** an HTTP GET to `https://api.openai.com/v1/models` with a
  `Bearer` header is performed and `(True, "Authentication successful…")`
  is returned on HTTP 200

#### Scenario: Ollama test runs a real generation
- **WHEN** `test_provider_auth("ollama", base_url="http://localhost:11434")`
  is called
- **THEN** `test_ollama_generate()` discovers installed models via
  `/api/tags`, generates a flashcard deck from a test source, and returns
  `(True, ...)` only if the output is a schema-valid non-empty deck

### Requirement: The setup wizard writes merged config non-destructively
`studyloop setup` (`cli/_setup.py`) SHALL guide the user through 5
prompted steps (materials path, AI assistant, NotebookLM, Obsidian vault,
write), load any existing `config.yaml`, merge new answers over existing
keys (with nested-dict sub-merge for `content`, `notebooklm`, and
`obsidian` sections), and write the result via `yaml.dump`. Existing
keys not covered by the wizard are preserved.

#### Scenario: Running setup on a machine with existing config
- **WHEN** `config.yaml` already contains `sync_remote: myhost` and the
  user runs `studyloop setup`
- **THEN** after the wizard completes, `sync_remote: myhost` is still
  present in the written file alongside the new wizard answers

### Requirement: studyloop config show and studyloop topics display loaded configuration
`studyloop config show` (`cli/_config.py`) SHALL render a Rich table of
core settings (obsidian_base, session_db, state_dir, knowledge bridging,
NotebookLM, sync_remote) with path-existence indicators, followed by a
topics table (name, slug, path, notebook, tags). `studyloop topics`
(`cli/_sync.py:topics`) SHALL list each configured topic's slug,
display name, and obsidian paths with existence markers.

#### Scenario: User runs studyloop config show with two topics configured
- **WHEN** `config.yaml` contains two topics and the user runs
  `studyloop config show`
- **THEN** both topics appear in the topics table with their name, slug,
  obsidian_path (green if the path exists, red if not), notebook_id
  prefix, and tags

#### Scenario: User runs studyloop topics with no topics configured
- **WHEN** `config.yaml` has no `topics:` key
- **THEN** `studyloop topics` produces no output (empty `get_topics()`
  list)

### Requirement: Legacy config directory is migrated on first access
`_maybe_migrate_legacy_config()` (`settings.py`) SHALL copy
`~/.config/studyctl/` to `~/.config/studyloop/` on first access within
a process, only when the legacy directory exists and the new directory
does not. The legacy directory is left in place. The migration is
skippable via `STUDYLOOP_SKIP_LEGACY_MIGRATION` environment variable.

#### Scenario: Fresh install on a machine with old studyctl config
- **WHEN** `~/.config/studyctl/` exists and `~/.config/studyloop/` does
  not
- **THEN** the first call to `load_raw_config()` copies the tree to
  `~/.config/studyloop/` and subsequent loads read from the new location

#### Scenario: Both directories already exist
- **WHEN** both `~/.config/studyctl/` and `~/.config/studyloop/` exist
- **THEN** no migration occurs — the new directory is authoritative
