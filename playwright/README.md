# Playwright evidence

This is the single top-level location for browser-test evidence.

```text
playwright/
├── artifacts/   # transient screenshots, HTML, traces, logs, and buffers
└── snapshots/   # reviewed visual baselines used by screenshot assertions
```

`artifacts/` is ignored by Git and is uploaded by CI when the browser suite
fails. `snapshots/` is intentionally not ignored: visual baselines are test
inputs and must be reviewed alongside the test that owns them.

The current pytest-Playwright suite produces diagnostic screenshots and other
failure evidence. It does not yet contain Playwright visual-regression
assertions (`to_have_screenshot`); adding one should place its approved
baseline under `snapshots/`.

## Hermetic server for agent-browser

Use the long-lived launcher when an interactive browser driver needs to exercise
CRUD workflows outside pytest:

```bash
uv run --all-packages python playwright/serve_hermetic.py
```

The launcher prints one JSON connection record, then keeps the server alive:

```json
{"base_url": "http://127.0.0.1:18612", "fake_agent": true, "pid": 12345}
```

It reuses the pytest `TestWorld` boundary, creates a temporary HOME/config/
session database/plans directory, and uses the deterministic fake agent by
default. No LAN authentication is enabled. Stop it with `Ctrl-C`; its temporary
world and child server are cleaned up together.

For a different shell, connect with the installed headless driver:

```bash
agent-browser --session studyloop-crud open http://127.0.0.1:18612
agent-browser --session studyloop-crud snapshot -i
```

`--real-agent` is available only as an explicit opt-out and should not be used
for deterministic CRUD assertions.
