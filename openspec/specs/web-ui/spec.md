## Purpose

Serve a local-first, no-build-step web dashboard (Alpine.js + HTMX,
FastAPI backend, `index.html` ~3.4k lines + `components.js` modules) for
starting study sessions, chatting live with the agent, reviewing generated
flashcards/quizzes, browsing course source material, tracking mastery, and
managing LLM provider credentials.

## Requirements

### Requirement: The PWA owns all chat-surface rendering
The server SHALL NOT send server-rendered HTML for ACP chat bubbles; it
forwards only raw ACP `session/update` events over the session WebSocket.
Markdown rendering (`marked`), sanitization (`DOMPurify`), and syntax
highlighting (`hljs`) all happen client-side.

#### Scenario: Agent response contains a script tag payload
- **WHEN** an agent-authored chat message contains
  `<script>`/`onerror=`/`javascript:` content
- **THEN** the marked → DOMPurify → hljs pipeline strips the executable
  payload before the message is inserted into the DOM (verified against a
  jsdom simulation with these three payload classes)

### Requirement: Explorer content routes are read-only and traversal-guarded
`GET /api/explorer/tree`, `.../courses/{id}/lessons`, and
`.../lesson/{id}/content` (`web/routes/explorer.py`) SHALL never write to
`content.base_path`, SHALL resolve every path with
`resolve().is_relative_to(base)`, and SHALL restrict readable suffixes to
`.md`, `.markdown`, `.txt`.

#### Scenario: Lesson ID crafted to escape the content base
- **WHEN** `GET /api/explorer/lesson/{lesson_id}/content` is called with a
  `lesson_id` containing `../` segments
- **THEN** the traversal guard rejects the resolved path before any file
  read occurs

### Requirement: Course Explorer tree is cached by a visible-source fingerprint
`GET /api/explorer/tree` SHALL cache the built provider/course tree on
`app.state` keyed by `_tree_fingerprint(base)`, which stats visible
providers/courses/source files while skipping dot-directories and
generated output subdirectories. Adding or deleting a nested course
invalidates the cache; writing a generated deck does not.

#### Scenario: A generated flashcard deck is written mid-session
- **WHEN** a new flashcard JSON file is written under an existing course's
  output directory
- **THEN** the Explorer tree cache is unaffected (the fingerprint ignores
  output subdirectories), and no unnecessary tree rebuild occurs

### Requirement: Explorer full-text search is a derived, rebuildable cache
`GET /api/explorer/search` SHALL query a separate SQLite FTS5 database
(`explorer_fts.db`, porter unicode61 tokenizer) that is lazily built and
incrementally refreshed on search, independent of `sessions.db`'s
migration system. Deleting `explorer_fts.db` SHALL NOT require a
migration to recover — it rebuilds on the next search call.

#### Scenario: explorer_fts.db is deleted while the server is running
- **WHEN** `explorer_fts.db` is deleted from disk and a search request
  arrives
- **THEN** `_run_fts_search` rebuilds the index from `content.base_path`
  before answering the query, with no migration step involved

### Requirement: Struggle marking writes lesson provenance for later scoped generation
`POST /api/history/struggling-topics` SHALL write `source_course`,
`source_section`, `source_publisher`, and `created_by='web'` onto
`study_progress` (migration v22), using the same `record_progress()` /
`get_struggling_topics()` helpers the agent session path uses, so the
Generate panel's "topic I'm struggling on" scope can resolve back to the
specific lesson.

#### Scenario: User marks a lesson as struggling from Course Explorer
- **WHEN** a user clicks "mark struggling" while reading a lesson in the
  Explorer panel
- **THEN** the write includes the lesson's course/section/publisher, and a
  subsequent Generate-panel request scoped to "struggling topics" can
  target that specific lesson rather than only a generic topic string

### Requirement: Generation progress streams over a per-job WebSocket
`POST /api/content/generate` SHALL return `202 {job_id, plan}` and start
`run_job` as a background asyncio task; `WS /api/content/generate/ws?job_id=...`
SHALL stream `started`, `task_complete` (per source×kind), and `all_done`
frames so a client can reconnect and resubscribe to a job in progress
without losing events already queued for it.

#### Scenario: Client disconnects and reopens the progress WebSocket mid-job
- **WHEN** the browser tab reloads while a generation job is still running
- **THEN** reopening the WS with the same `job_id` resumes receiving
  `task_complete`/`all_done` frames from the per-job queue rather than
  missing events emitted during the gap

### Requirement: Review list mode-splits Flashcards and Quizzes from one shared component
The `reviewApp('flashcards' | 'quiz')` Alpine factory SHALL be
instantiated once per mode; `filteredCourses` gates the list on the
matching card-type count before applying the search filter, and
`groupedCourses` groups by the API's `publisher` field with collapsible
headers. `name` (not `publisher`) SHALL be the identity key for
`/api/cards`, config lookups, and the SM-2 review DB.

#### Scenario: Same course name exists under two publishers
- **WHEN** two distinct publisher-scoped course directories happen to
  share a display `name`
- **THEN** review/SM-2 state keys on `name`, so the two are treated as the
  same reviewable course even though `publisher` differs (a known
  identity-key choice, not a bug)

### Requirement: Settings → LLM Providers only persists verified credentials
The Settings panel SHALL call `GET /api/content/providers` to render one
row per provider by `auth_kind`, and SHALL only call
`POST/DELETE /api/content/secrets` to store a credential after
`POST /api/content/providers/<slug>/test` succeeds (api_key: live auth
call; Bedrock: AWS-cred check; Ollama: real generation call).

#### Scenario: Test-and-save with an invalid API key
- **WHEN** a user submits an invalid API key and clicks Test & Save
- **THEN** the live verification call fails and the key is never written
  to `secrets.bin`
