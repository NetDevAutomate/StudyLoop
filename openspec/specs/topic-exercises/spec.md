# topic-exercises Specification

## Purpose

Retain StudyLoop's three-format exercise pipeline as an explicitly gated
developer preview while its value is evaluated against the mentor's existing
Socratic workflow. The implementation remains testable and available for
experimentation without appearing in the supported learner surface.

## Requirements

### Requirement: Exercise surfaces are absent by default

StudyLoop SHALL NOT expose topic exercises in its production CLI command
inventory, MCP tool inventory, or web API route inventory. Absence SHALL be
structural: the CLI resolves `exercise` as an unknown command, MCP
`tools/list` contains no `exercise_*` names, and the FastAPI application
contains no `/api/exercises` routes. The implementation SHALL NOT register
these surfaces and then reject calls at runtime.

#### Scenario: Learner uses the normal CLI
- **WHEN** the learner runs `studyloop --help` or `studyloop exercise list`
  without the root `--dev` flag
- **THEN** `exercise` is absent from the command list and direct invocation is
  rejected as an unknown command

#### Scenario: Assistant connects to the normal MCP server
- **WHEN** an MCP client starts `studyloop-mcp` without `--dev` and calls
  `tools/list`
- **THEN** none of `exercise_list`, `exercise_get`, `exercise_create`,
  `exercise_import`, or `exercise_review` is present

#### Scenario: Learner starts the normal web application
- **WHEN** the app is created without `dev_mode` / `studyloop web --dev`
- **THEN** no route whose path starts with `/api/exercises` is registered

### Requirement: One explicit development gate enables each surface

StudyLoop SHALL expose the retained exercise implementation only after an
explicit development opt-in at the process boundary: `studyloop --dev
exercise …` for CLI commands, `studyloop-mcp --dev` for MCP tools, and
`studyloop web --dev` for HTTP routes. The development surface SHALL retain
the same answer-withholding and review contracts as before gating.

#### Scenario: Developer opts into the CLI preview
- **WHEN** a developer invokes `studyloop --dev exercise --help`
- **THEN** the exercise command group and its author/review subcommands are
  available

#### Scenario: Developer opts into the MCP preview
- **WHEN** the MCP server command includes `--dev`
- **THEN** all five `exercise_*` tools are registered and discoverable

#### Scenario: Developer opts into the web preview
- **WHEN** the web app is created with `dev_mode=True`
- **THEN** the exercise API lifecycle is available under `/api/exercises`

### Requirement: Generated MCP configuration states the preview opt-in

The MCP config writer SHALL accept a `dev` setting. When true, it SHALL append
`--dev` to the generated server command for both generic and OpenCode config
formats; when false or omitted, it SHALL generate the production command with
no development flag. Custom adapter configuration MAY opt in with
`mcp.dev: true`.

#### Scenario: Generic MCP config opts in
- **WHEN** configuration is generated with `dev=True`
- **THEN** the server entry's `args` array includes `--dev`

#### Scenario: OpenCode MCP config opts in
- **WHEN** OpenCode configuration is generated with `dev=True`
- **THEN** the command array ends with `--dev`

### Requirement: Documentation does not present exercises as supported

The topic-exercise guide, CLI reference, and agent protocol SHALL label the
capability as a developer preview, explain that its value alongside Socratic
mentoring is unproven, and use only the gated CLI/MCP examples. Documentation
MAY state that the capability can be reconsidered if learner demand emerges.

#### Scenario: Learner reads exercise documentation
- **WHEN** the exercise guide or agent protocol is opened
- **THEN** the development-only status and exact opt-in commands appear before
  operational instructions
