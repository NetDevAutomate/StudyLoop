## Purpose

Turn source markdown into validated flashcard/quiz JSON via a pluggable
provider abstraction (Stub, Ollama, Bedrock, OpenAI-compatible,
Anthropic-compatible), triggered from the CLI or the web Generate panel,
with a singleton guarding against concurrent generation jobs.

## Requirements

### Requirement: Generation is single-flight per process
The system SHALL guard content generation with an `active_gen`
singleton (`content/active_gen.py`) so only one job runs at a time.
`POST /api/content/generate` SHALL return HTTP 409 with
`GenerationAlreadyActiveError` when a job is already running.

#### Scenario: Second generate request while a job is active
- **WHEN** a generation job is in progress and another
  `POST /api/content/generate` request arrives
- **THEN** the server responds 409 without starting a second job

### Requirement: Generator selection is a registry lookup, not new code
The system SHALL resolve a `CardGenerator` via `get_generator(config)`
(`content/generators/__init__.py`) against a `ProviderProfile` registry
(`content/generators/provider_profiles.py`) covering Stub, Ollama,
Bedrock, and two generic HTTP adapters — OpenAI Chat Completions
(`openai_compat.py`) and Anthropic Messages (`anthropic_compat.py`) — that
serve multiple provider registry rows (OpenAI, OpenRouter, Gemini,
Anthropic) without provider-specific adapter code.

#### Scenario: Adding a new OpenAI-compatible provider
- **WHEN** a new provider exposes an OpenAI Chat Completions-compatible
  endpoint
- **THEN** it is added as a `ProviderProfile` registry row referencing the
  existing `openai_compat` adapter; no new adapter class is required

### Requirement: Stub generator produces deterministic output for tests
The system SHALL provide `content/generators/stub.py` as a
network-free generator returning deterministic flashcard/quiz content, used
by default in tests not marked `live_provider`.

#### Scenario: Test suite run without live_provider marker
- **WHEN** `pytest -m 'not integration and not e2e and not live_kiro and
  not live_provider'` runs a test that exercises card generation
- **THEN** the Stub generator is used and no network call is made

### Requirement: Credentials resolve encrypted-store-first
The system SHALL resolve provider credentials via
`secrets.get_secret(slug)` (`secrets.py`) — a Fernet-encrypted store at
`~/.config/studyloop/secrets.bin` with 0600/0700 permissions, HKDF key
derivation, and atomic writes — before falling back to a project-root
`.env` loaded via `python-dotenv`. Secrets are written to the store only
after `POST /api/content/providers/<slug>/test` performs a live
verification call.

#### Scenario: Settings panel saves a new API key
- **WHEN** a user submits an API key in the Settings → LLM Providers panel
- **THEN** the server performs a live auth-verification call for that
  provider before writing the key to the encrypted store; a failed
  verification SHALL NOT persist the key

### Requirement: Read root and write root for generated decks can diverge
CLI-driven generation SHALL write under
`content.base_path/<course>/{flashcards,quizzes}/`; web-driven generation
with a `publisher` supplied SHALL write under
`content.base_path/<publisher>/<course>/{flashcards,quizzes}/`. The
review surface SHALL read via `resolve_study_dirs()`
(`settings.py:366`), which uses `review.directories` when explicitly set
and otherwise falls back to `content.base_path`, and
`review_loader.discover_directories()` walks both directory layouts.

#### Scenario: `review.directories` present but the `review:` key value is not a mapping
- **WHEN** `config.yaml` contains a bare `review:` key with a non-dict
  value (or no `directories` sub-key)
- **THEN** `resolve_study_dirs()`'s `raw.get("review", {}).get("directories")`
  call raises `AttributeError` on a non-dict `review:` value (confirmed
  still present as of `61a15fc`; distinct from the topic-loader crash class
  that `_topic_from_raw` already fixed in `9f033fa`)

### Requirement: content.study_paths must be a list, not a bare scalar
The `content.study_paths` setting SHALL be a YAML list of path strings.
As of `61a15fc` the loader does not validate this shape: a bare string
value is iterated character-by-character, producing one single-character
`Path` per character rather than raising a clear configuration error.

#### Scenario: study_paths configured as a bare string
- **WHEN** `content.study_paths: /Users/x/Notes` (a scalar, not a list) is
  present in `config.yaml`
- **THEN** the loader iterates the string and produces one `Path` object
  per character instead of a single path or a validation error
