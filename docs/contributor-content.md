# Content Schemas and Pipeline

<!-- facts: F7 F16 -->

Generated study material is JSON on disk, and `packages/studyloop/src/studyloop/content/schemas.py`
is the only place that says what that JSON may contain. Change the schema first, make the schema
tests fail and pass, then follow the change through the generators and the write path with
`just test-content`.

## The contract: `content/schemas.py`

1. Three deck models -- `FlashcardDeck`, `QuizDeck`, `PracticeDeck` -- and their items are
   Pydantic models with `model_config = {"extra": "forbid"}`. An unknown key is a validation error,
   not a silently dropped field; that is what lets a generator trust what it wrote.
2. Field names are **camelCase on disk** and snake_case in Python. The alias bridges them:
   `is_correct: bool = Field(alias="isCorrect")`, `answer_options`, `successCriteria`,
   `setupCommand`. Models that take aliased input also set `"populate_by_name": True`, so tests
   can build them with either spelling. `write_json()` always dumps `by_alias=True`.
3. Each deck writes itself: `FlashcardDeck.write_json(directory, slug)` lands at
   `<slug>-flashcards.json`, quizzes at `<slug>-quiz.json`, practice at `<slug>-practice.json`.
   The suffixes are the globs the read side (`review_loader.py`) looks for; do not change one
   without the other.
4. `flashcard_deck_json_schema()` and friends hand the same model to a provider as a JSON schema,
   so a schema change changes what the model is asked to produce.

Add a field with an alias and a default; `extra: forbid` means a field you add is accepted
nowhere until every generator and fixture that builds the model knows it. Prove the change in
`packages/studyloop/tests/test_content_schemas.py` (rejection tests sit beside the parse tests):

```bash
uv run --group dev pytest packages/studyloop/tests/test_content_schemas.py -q
```

## The generation pipeline

- `content/generators/__init__.py` -- the `CardGenerator` Protocol and `get_generator(config)`,
  which selects a backend by `settings.card_generator.backend`. Every backend raises
  `CardGenerationError`; callers show its message and never see an HTTP or Pydantic exception.
- `content/generators/ollama.py`, `bedrock.py`, `openai_compat.py`, `anthropic_compat.py` -- the
  backends. The two `_compat` adapters are generic; a new OpenAI- or Anthropic-compatible provider
  is a `ProviderProfile` row in `content/generators/provider_profiles.py`, not a new class.
- `content/generators/prompts.py` -- the prompt templates; `runner.py` -- the thread pool that
  generates several sources at once.
- `content/job.py` -- one web generation job: builds tasks, runs the generator, writes decks under
  the right root, emits progress; `content/active_gen.py` -- the single-flight guard behind the
  web panel's HTTP 409.
- The deterministic generator used by the tests is **not packaged**: it is
  `packages/studyloop/tests/_content_generator.py` (`DeterministicTestGenerator`), injected at the
  Protocol seam. No default-tier test reaches a network.

## Where decks are read and written

The `content-generation` spec (`openspec/specs/content-generation/spec.md`) fixes the roots:

1. CLI generation writes under `content.base_path/<course>/{flashcards,quizzes,practice}/`
   (`content/storage.py::get_course_dir`).
2. Web generation with a `publisher` writes under
   `content.base_path/<publisher>/<course>/...` (`content/job.py::_course_output_dir`); with no
   publisher it falls back to the CLI layout.
3. The review surface reads through `settings.resolve_study_dirs()` -- `review.directories` when
   set, else `content.base_path` -- and `review_loader.discover_directories()` walks both layouts.

So a change to a write path must be checked against the read path in the same pull request, and
tests write only under `tmp_path`: the autouse fixtures in `packages/studyloop/tests/conftest.py`
fail any test that touches the real config directory or vault.

## Prove the change

`just test-content` runs the nine content suites (CLI, generators, runner, stub, job runner, scope,
storage, storage merge, workflow) in the default tier:

```bash
just test-content
```

It does not include `test_content_schemas.py`; run that one explicitly, as above. Tests marked
`live_provider` call a real model and are deselected by default (F7) -- never make a default-tier
test depend on one. If your change touches the Generate panel's routes or JavaScript, follow
[A Web Route and UI](contributor-web.md) as well.
