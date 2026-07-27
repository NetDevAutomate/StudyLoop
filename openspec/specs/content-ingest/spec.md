## Purpose

Discover configured study sources, split PDFs into per-chapter files,
plan and preview content ingest workflows, convert markdown to PDF with
mermaid rendering, maintain a course-centric storage layout with
slugified directories and metadata, and build an incremental SQLite
content index over providers/courses/lessons/artefacts. This capability
covers the pipeline from raw source material to indexed course
structure; it does NOT cover quiz/flashcard generation (content-generation
spec), the web Course Explorer surface (web-ui spec), or spaced
repetition scheduling (spaced-repetition-review spec).

## Requirements

### Requirement: Discovery walks configured source roots filtering by extension, size, and skip patterns
The system SHALL discover syncable study materials via
`content/discovery.py::discover_materials()`, accepting a list of source
root paths and recursively collecting files whose suffix is in
`SYNCABLE_EXTENSIONS` (`.md`, `.pdf`, `.txt`), whose size exceeds
`MIN_FILE_SIZE` (100 bytes), whose filename is not in `SKIP_FILENAMES`,
and whose path parts do not intersect `SKIP_PATTERNS`. Duplicate files
(by resolved path) are deduplicated across roots.

#### Scenario: CLI discover without explicit source arguments
- **WHEN** `studyloop content discover` is invoked with no positional
  args
- **THEN** `_configured_study_sources()` (`cli/_content.py`) resolves
  source roots from `settings.topics[*].obsidian_path` plus
  `content.study_paths`, deduplicates them, and falls back to
  `~/Obsidian/Personal/Study` when both are empty

#### Scenario: File below MIN_FILE_SIZE is excluded
- **WHEN** a `.md` file under a source root has fewer than 100 bytes
- **THEN** `_should_skip_path()` returns True and the file does not
  appear in the returned `DiscoveredMaterial` list

### Requirement: PDF splitting uses TOC bookmarks or explicit page ranges
`content/splitter.py::split_pdf_by_chapters()` SHALL split a PDF into
per-chapter files at a configurable TOC depth level (default 1), naming
outputs `{book_name}_chapter_{NN}_{sanitized_title}.pdf`. When the PDF
has no TOC, `split_pdf_by_ranges()` SHALL accept a comma-separated
range string (e.g. `"1-30,31-60"`) and produce
`{book_name}_part_{NN}.pdf` files. Both functions create the output
directory and return the list of written paths.

#### Scenario: PDF with TOC split at level 1
- **WHEN** `studyloop content split source.pdf -o ./chapters` is run on
  a PDF that has TOC bookmarks
- **THEN** `split_pdf_by_chapters` extracts level-1 entries, writes one
  PDF per chapter to `./chapters/`, and rebuilds per-chunk TOC metadata
  inside each output file

#### Scenario: PDF without TOC raises ValueError
- **WHEN** `split_pdf_by_chapters` is called on a PDF with no bookmarks
- **THEN** a `ValueError` is raised with a message indicating no
  bookmarks/TOC are present

#### Scenario: Explicit page ranges for a PDF without TOC
- **WHEN** `studyloop content split source.pdf --ranges "1-30,31-60"`
  is invoked
- **THEN** `split_pdf_by_ranges` writes two part files covering pages
  1–30 and 31–60 respectively

### Requirement: Ingest planning is dry-run-only and uses content hashing to classify actions
`studyloop content ingest` SHALL reject non-dry-run invocations with a
`ClickException` stating only `--dry-run` is currently supported.
`content/workflow.py::build_ingest_plan()` SHALL classify each
discovered material as `create` (no prior metadata entry), `update`
(SHA-256 hash changed), or `skip` (hash unchanged), deriving the course
slug from the explicit `--course` option or falling back to the source
root directory name via `storage.slugify()`.

#### Scenario: Ingest without --dry-run flag
- **WHEN** `studyloop content ingest /some/path` is run without
  `--dry-run`
- **THEN** a `ClickException` is raised with message containing "Only
  'studyloop content ingest --dry-run' is currently supported"

#### Scenario: New source file classified as create
- **WHEN** `build_ingest_plan` encounters a discovered material whose
  path has no entry in the course's `metadata.json` `sources` list
- **THEN** the plan item's `action` field is `"create"`

#### Scenario: Unchanged source classified as skip
- **WHEN** the SHA-256 hash of a discovered material matches the stored
  hash in metadata
- **THEN** the plan item's `action` field is `"skip"`

### Requirement: Course storage uses a fixed subdirectory layout with slugified names
`content/storage.py::get_course_dir()` SHALL create the course directory
and its standard subdirectories (`chapters`, `audio`, `flashcards`,
`quizzes`, `practice`, `video`, `slides`) under `content.base_path`.
`slugify()` SHALL produce a lowercase, alphanumeric-and-dash slug
truncated to 60 characters, used as the directory name.

#### Scenario: First access to a new course
- **WHEN** `get_course_dir(base_path, "Advanced Pandas!")` is called
- **THEN** the directory `{base_path}/advanced-pandas/` is created with
  all seven subdirectories, and the path is returned

#### Scenario: Slug truncation
- **WHEN** `slugify()` receives a title longer than 60 characters after
  normalisation
- **THEN** the returned slug is truncated to at most 60 characters with
  trailing dashes stripped

### Requirement: Metadata is persisted atomically per course directory
`content/storage.py::save_course_metadata()` SHALL write
`metadata.json` atomically via write-to-tempfile-then-rename within the
course directory. `load_course_metadata()` SHALL return an empty dict
when the file is missing or contains invalid JSON rather than raising.

#### Scenario: Concurrent crash during metadata write
- **WHEN** the process crashes after writing the temp file but before
  rename
- **THEN** the original `metadata.json` remains intact (the temp file
  is orphaned but the course directory is not corrupted)

### Requirement: Content index provides incremental SQLite-backed refresh over provider/course/lesson/artefact hierarchy
`content/index.py::ContentIndex` SHALL maintain a SQLite database
(`content_index.db`) at `content_base(settings)` with tables
`providers`, `courses`, `lessons`, and `artefacts`. `refresh()` SHALL
walk `content.base_path/<provider>/<course>/` directories, index all
`.md` files as lessons and all `*.flashcards.json` / `*.quiz.json` as
artefacts, storing mtime for incremental change detection. `get_tree()`
SHALL return a nested dict keyed by provider → course → lessons +
artefacts.

#### Scenario: CLI index refresh after adding a new course
- **WHEN** `studyloop content index` is run after a new course
  directory with markdown files appears under a provider
- **THEN** `refresh()` inserts rows into `courses` and `lessons` and
  `IndexStats` reports the correct lesson count

#### Scenario: get_tree returns provider-keyed hierarchy
- **WHEN** `ContentIndex.get_tree()` is called after refresh
- **THEN** the returned dict has shape
  `{"providers": {"<name>": {"courses": {"<slug>": {"title", "path",
  "lessons": [...], "artefacts": [...]}}}}}}`

### Requirement: Markdown-to-PDF conversion strips frontmatter, converts wikilinks, and pre-renders mermaid diagrams
`content/markdown_converter.py::convert_markdown_to_pdf()` SHALL strip
YAML frontmatter, convert Obsidian `[[wikilinks]]` to plain text via
regex, render mermaid code blocks to PNG using `mmdc`, and invoke
`pandoc --pdf-engine=typst` (with fallback to default engine on
failure). `check_prerequisites()` SHALL return the names of any missing
tools (`pandoc`, `mmdc`, `typst`).

#### Scenario: Markdown with mermaid diagrams
- **WHEN** `convert_markdown_to_pdf` processes a file containing
  ` ```mermaid` code blocks
- **THEN** each mermaid block is rendered to a numbered PNG via `mmdc`
  and replaced with a markdown image reference before pandoc conversion

#### Scenario: mmdc not installed
- **WHEN** `check_prerequisites()` is called and `mmdc` is not on PATH
- **THEN** the returned list includes
  `"mmdc (@mermaid-js/mermaid-cli)"`

### Requirement: Scope resolution translates user-facing requests into source file lists with path-traversal protection
`content/scope.py::resolve_scope()` SHALL accept a `ScopeRequest`
(kinds: `course`, `section`, `topic_struggles`) and return a non-empty
list of `ResolvedSource` objects or raise `ScopeResolutionError`.
`resolve_content_path()` SHALL reject absolute paths and `..` traversal
segments, and verify the resolved path remains within
`content.base_path`. Output subdirectories (`flashcards/`, `quizzes/`)
are excluded from source iteration to prevent re-feeding generated
content.

#### Scenario: Course scope resolves all lesson files
- **WHEN** `resolve_scope` is called with `kind="course"` for a course
  directory containing 5 markdown files
- **THEN** 5 `ResolvedSource` objects are returned, one per file, each
  with a slugified `identifier` and the file's full text as
  `markdown_text`

#### Scenario: Path traversal attempt is rejected
- **WHEN** a `ScopeRequest` contains `course="../../etc"` or an
  absolute path segment
- **THEN** `resolve_content_path()` raises `ScopeResolutionError`
  before any filesystem access outside `content.base_path`

#### Scenario: Output subdirs excluded from source iteration
- **WHEN** `_iter_source_files()` walks a course directory containing a
  `flashcards/` subdirectory with `.md` files inside it
- **THEN** those files are excluded from the returned list

### Requirement: Syllabus state is managed via atomic JSON with episode chunking and priority-based next-chunk selection
`content/syllabus.py` SHALL persist `SyllabusState` (book name,
notebook ID, chunk list with per-chunk status) to a JSON file via
`write_state()` using write-to-temp-then-fsync-then-rename.
`get_next_chunk()` SHALL select the next chunk by priority:
`GENERATING` (resume interrupted) > `FAILED` (retry) > `PENDING`
(new). `parse_syllabus_response()` SHALL parse the LLM episode format
and raise `SyllabusParseError` when any chapters remain unassigned.

#### Scenario: Interrupted generation resumes at the in-progress chunk
- **WHEN** `get_next_chunk()` is called on a state with one chunk in
  `GENERATING` status and two in `PENDING`
- **THEN** the `GENERATING` chunk is returned (not the first `PENDING`)

#### Scenario: LLM response missing chapters raises parse error
- **WHEN** `parse_syllabus_response()` is called with a response that
  assigns only chapters 1–3 but the source map contains chapters 1–5
- **THEN** `SyllabusParseError` is raised naming the missing chapters
