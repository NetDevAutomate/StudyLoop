# Troubleshooting

## Install Checks

Run the lightweight self-test first:

```bash
studyloop self-test
studyloop self-test --json
```

Then run the deeper environment checks:

```bash
studyloop doctor
studyloop doctor --json
```

`studyloop self-test` is safe immediately after installation. It does not run
`doctor --fix`, start services, contact providers, or write agent files.

## uv Environment Drift

When a local checkout behaves differently from CI, resync the lean development
profile and rerun the core gates:

```bash
just sync-dev
just lint
just typecheck
just test
```

Use `just sync-full` only when validating optional extras. The full profile
pulls heavier optional stacks such as semantic search and TTS dependencies.

## Optional Profiles

Use profile checks when a change touches a specific optional surface:

```bash
just test-web
just test-content
just test-semantic
```

If `test-semantic` skips because `numpy` or embedding dependencies are missing,
run:

```bash
just sync-semantic
just test-semantic
```

## Web And LAN Access

For local-only use:

```bash
studyloop web
```

For LAN use:

```bash
studyloop web --lan
```

Configured LAN passwords are not printed. Generated one-time passwords are
printed once. If a phone or tablet cannot connect, check that the shown LAN URL
uses the host's real LAN address and that the device is on the same network.

## Provider Credentials

Use the web Settings panel or environment variables for provider keys. Raw
provider keys must never appear in logs, screenshots, or issue reports.

For provider checks:

```bash
studyloop self-test
studyloop doctor --category deps
```

`studyloop self-test` only verifies that the web module imports. It does not
call OpenAI, OpenRouter, Gemini, Anthropic, Bedrock, Ollama, or other providers.

